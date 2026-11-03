"""Robust subtitle detection for musical audio.
Known uploaded reference is matched by SHA256; all other songs use local faster-whisper.
Never silently publish an obviously broken one-caption transcript.
"""
from __future__ import annotations
from pathlib import Path
import math
import tempfile, subprocess

from builder import MICRO
from semantic_captions import phrase_rows, clean_caption
from song_library import SongLibrary

class CaptionsNotRecognized(RuntimeError):
    pass


def transcription_quality(rows, duration_us):
    valid=[(s,e,t) for s,e,t in rows if e>s and t.strip()]
    duration=sum(max(0,e-s) for s,e,_ in valid)
    return {'count':len(valid), 'ratio':duration/max(duration_us,1),
            'chars':sum(len(t.strip()) for _,_,t in valid)}


def good_enough(rows, duration_us):
    m=transcription_quality(rows,duration_us)
    if duration_us < 5*MICRO:return m['count']>=1 and m['chars']>=5
    if duration_us < 12*MICRO:return m['count']>=2 and m['chars']>=12
    # A 2-3 line transcript for a full verse is an ASR failure, not a
    # usable project. Old releases accidentally accepted it.
    seconds = duration_us / MICRO
    min_phrases = max(4, math.ceil(seconds / 7.5)) if seconds >= 20 else 3
    return (m['count'] >= min_phrases
            and m['chars'] >= max(22, min_phrases * 6)
            and m['ratio'] >= 0.22)


def _group_words(words, duration_us):
    """Semantic segmentation: clause/punctuation/pause before visual line limits."""
    return phrase_rows(words, duration_us)


def _transcribe(audio, model_name, duration_us, progress):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('Не установлен faster-whisper. Запусти install.bat.') from exc
    progress('Загрузка Whisper '+model_name+' (первый запуск скачивает модель)...')
    model=WhisperModel(model_name,device='cpu',compute_type='int8')
    segments,_=model.transcribe(str(audio),language='ru',word_timestamps=True,
        vad_filter=False,beam_size=7,condition_on_previous_text=False,
        temperature=0.0)
    words=[]
    for segment in segments:
        for wi, word in enumerate(segment.words or []):
            if word.word.strip():
                words.append((float(word.start),float(word.end),word.word.strip(),
                              float(word.probability) if word.probability is not None else None,
                              wi == 0))
    rows=_group_words(words,duration_us)
    good=[w[3] for w in words if w[3] is not None and w[3]>=0.12]
    avg_conf=sum(good)/len(good) if good else 0.0
    m=transcription_quality(rows,duration_us)
    # Confidence is only a rough estimate; high confidence can still be wrong.
    score=avg_conf*0.78+min(0.85,m['ratio'])*0.16+min(1,m['chars']/max(duration_us/MICRO*5,1))*0.06
    return rows,score


def enhance_for_recognition(audio:Path, out:Path):
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(audio),'-vn',
         '-af','highpass=f=120,lowpass=f=4600,dynaudnorm=f=75:g=10',
         '-ar','16000','-ac','1','-c:a','pcm_s16le',str(out)]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)


def _separate_vocals(audio:Path, workdir:Path, progress):
    """Optional high-quality vocal separation. Requires opt-in install of Demucs."""
    import importlib.util,sys
    if getattr(sys,'frozen',False):
        # sys.executable is our GUI executable, NOT a Python interpreter.
        # Running it with `-m demucs` would recursively launch another GUI.
        progress('В EXE отделение вокала Demucs пока недоступно: использую аудиофильтрацию.')
        return None
    if importlib.util.find_spec('demucs') is None:
        progress('Demucs не установлен: использую улучшенную фильтрацию вместо выделения вокала.')
        return None
    progress('Отделяю вокал Demucs; на CPU это может занять несколько минут...')
    cmd=[sys.executable,'-m','demucs','--two-stems','vocals','-n','htdemucs',
         '-o',str(workdir/'stems'),str(audio)]
    try:
        r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
              text=True,encoding='utf-8',errors='replace',timeout=1800)
        if r.returncode:
            progress('Demucs не смог отделить вокал: '+r.stderr[-250:]);return None
        candidates=list((workdir/'stems').glob('**/vocals.wav'))
        return candidates[0] if candidates else None
    except (OSError,subprocess.TimeoutExpired) as exc:
        progress('Не удалось запустить Demucs: '+str(exc));return None



MISSING_LYRICS = '[ДОПИШИ ТЕКСТ]'


def _voice_regions(audio: Path, progress=None):
    """Speech-only hints from Silero VAD, not a guarantee of vocals in music."""
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        signal = decode_audio(str(audio), sampling_rate=16000)
        options = VadOptions(min_speech_duration_ms=500, min_silence_duration_ms=250,
                             speech_pad_ms=0)
        spans = get_speech_timestamps(signal, vad_options=options, sampling_rate=16000)
        return [(int(p['start'] / 16000 * MICRO), int(p['end'] / 16000 * MICRO))
                for p in spans]
    except Exception as exc:
        if progress:
            progress('Не удалось определить пропущенные вокальные фразы: ' + str(exc)[:100])
        return []


def fill_unrecognized_vocals(rows, voice_regions, duration_us: int):
    """Create editable placeholders ONLY in suspected voiced, untranscribed gaps."""
    rows = sorted((int(a), int(b), clean_caption(t)) for a,b,t in rows if b>a and t.strip())
    # CRITICAL: voice activity on a song does not imply recognizable lyrics.
    # Never fabricate a timeline made entirely of [ДОПИШИ ТЕКСТ].
    if len(rows) < 2 or not voice_regions:
        return rows
    if sum(len(t.replace(' ', '')) for _,_,t in rows) < 12:
        return rows
    max_placeholders = min(3, max(1, len(rows) // 6))
    window = max(0,int(duration_us))
    # Whole-track speech detection is often a false positive on instrumentals.
    if any(b-a > 11_000_000 for a,b in voice_regions):
        return rows
    placeholders=[]
    for start,end in voice_regions:
        start=max(0,int(start));end=min(window,int(end))
        if end-start < 650_000:
            continue
        free=[(start,end)]
        for a,b,_ in rows:
            covered=(max(0,a-180_000), min(window,b+180_000))
            fragments=[]
            for left,right in free:
                if covered[1]<=left or covered[0]>=right:
                    fragments.append((left,right))
                else:
                    if left<covered[0]:fragments.append((left,covered[0]))
                    if covered[1]<right:fragments.append((covered[1],right))
            free=fragments
        for left,right in free:
            if right-left<700_000:
                continue
            nearest=min((min(abs(left-b), abs(right-a)) for a,b,_ in rows),default=0)
            if rows and nearest>3_000_000:
                continue
            # Conservative: one short suspected missing phrase, not a whole
            # instrumental section split into repeated placeholders.
            if right-left > 2_800_000:
                continue
            if len(placeholders) >= max_placeholders:
                break
            placeholders.append((left,right,MISSING_LYRICS))
    if not placeholders:
        return rows
    all_rows=sorted(rows+placeholders)
    safe=[]
    for row in all_rows:
        if not safe or row[0]>=safe[-1][1]:
            safe.append(row)
        elif row[2] != MISSING_LYRICS:
            safe=[x for x in safe if x[2]!=MISSING_LYRICS or x[1]<=row[0]]
            if not safe or safe[-1][1]<=row[0]:safe.append(row)
    return safe


def _cached_captions(audio:Path):
    record = SongLibrary().load(audio)
    return record if record is not None else None


def obtain_captions(audio: Path, duration_us:int, chosen_model='medium', progress=None,
                    separate_vocals=False):
    say=progress or (lambda _:None)
    cached=_cached_captions(audio)
    if cached and cached['verified']:
        placeholders=sum(t==MISSING_LYRICS for _,_,t in cached['rows'])
        if placeholders and placeholders/max(len(cached['rows']),1) >= 0.30:
            say('В библиотеке найден повреждённый набор с заглушками. '
                'Игнорирую его и заново распознаю песню.')
        else:
            say('Библиотека песен: использую '+str(len(cached['rows']))+
                ' подтверждённых фраз (источник: '+str(cached.get('source','неизвестен'))+').')
            return cached['rows']
    if cached:
        say('Найдён непроверенный авто-черновик. Перераспознаю для улучшения качества.')
    model=chosen_model if chosen_model in ('medium','large-v3') else 'medium'
    # V6 prioritizes quality over V5's small-model speed.
    say('Распознаю песню на '+model+' (точность важнее скорости)...')
    first,first_score=_transcribe(audio,model,duration_us,say)
    with tempfile.TemporaryDirectory(prefix='capcut_v6_recognition_') as tmp:
        root=Path(tmp)
        second_source=None
        if separate_vocals:
            second_source=_separate_vocals(audio,root,say)
        if second_source is None:
            second_source=root/'enhanced.wav'
            try:enhance_for_recognition(audio,second_source)
            except (OSError,subprocess.CalledProcessError) as exc:
                say('Фильтрация вокала недоступна: '+str(exc));second_source=None
        second=[];second_score=-1.0
        if second_source is not None:
            say('Перепроверяю слова и тайминги на отдельной обработке аудио...')
            second,second_score=_transcribe(second_source,model,duration_us,say)
    # Always report BOTH attempts so the user can distinguish a cache hit from
    # a model failure. NEVER proceed with too few captions.
    options=[(first,first_score),(second,second_score)]
    for label,(rows,score) in zip(('оригинал','фильтрация'),options):
        stats=transcription_quality(rows,duration_us)
        say(f'Whisper ({label}): {stats["count"]} фраз, {stats["chars"]} символов, '
            f'покрытие {stats["ratio"]:.0%}.')
    valid=[item for item in options if good_enough(item[0],duration_us)]
    if not valid:
        best=max(options,key=lambda x:(transcription_quality(x[0],duration_us)['count'],
                                      transcription_quality(x[0],duration_us)['ratio']))
        stats=transcription_quality(best[0],duration_us)
        expected=max(4,math.ceil(duration_us/MICRO/7.5)) if duration_us>=20*MICRO else 3
        raise CaptionsNotRecognized(
            f'Whisper распознал слишком мало текста: {stats["count"]} фраз '
            f'на {duration_us/MICRO:.1f} сек. Для надёжного автоматического '
            f'монтажа нужно хотя бы {expected} фраз и достаточное покрытие песни. '
            'Проект с обрезанными субтитрами НЕ создан. '
            'Можно выбрать large-v3 или импортировать исправления из CapCut.')
    # Prefer a more COMPLETE transcript over a higher average confidence from
    # a model that missed most of the lyrics.
    result,score=max(valid,key=lambda item:(
        transcription_quality(item[0],duration_us)['count'],
        transcription_quality(item[0],duration_us)['chars'],
        transcription_quality(item[0],duration_us)['ratio'],
        item[1]))
    # Optional forced alignment: not required for ordinary editing.
    try:
        from alignment import available, align_existing
        if available() and not any(t == MISSING_LYRICS for _,_,t in result):
            say('Пробую точное выравнивание WhisperX (подтверждённый текст не меняю)…')
            result=align_existing(audio,result,progress=say)
    except Exception as exc:
        say('WhisperX не смог уточнить тайминги, оставляю оценку Whisper: '+str(exc)[:120])
    # Automatic VAD-based gap fillers are intentionally DISABLED: Silero
    # identifies musical instruments as voice and damaged real caption tracks.
    # A future explicit manual opt-in can re-enable them after validation.
    say(f'Сформировано {len(result)} смысловых блоков. Распознавание песен может ошибаться: '
        'для исправлений используй корректор субтитров.')
    try:
        SongLibrary().save(audio,result,verified=False,source='whisper')
    except Exception as err:
        say('Не удалось записать черновик субтитров в библиотеку: '+str(err))
    return result
