"""Robust subtitle detection for musical audio.
Known uploaded reference is matched by SHA256; all other songs use local faster-whisper.
Never silently publish an obviously broken one-caption transcript.
"""
from __future__ import annotations
from pathlib import Path
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
    return m['count']>=3 and m['chars']>=18 and m['ratio']>=0.17


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


def _cached_captions(audio:Path):
    record = SongLibrary().load(audio)
    return record if record is not None else None


def obtain_captions(audio: Path, duration_us:int, chosen_model='medium', progress=None,
                    separate_vocals=False):
    say=progress or (lambda _:None)
    cached=_cached_captions(audio)
    if cached and cached['verified']:
        say('Библиотека песен: использую подтверждённые человеком слова и тайминги.')
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
    options=[(first,first_score),(second,second_score)]
    valid=[item for item in options if good_enough(item[0],duration_us)]
    if not valid:
        m=transcription_quality(first,duration_us)
        raise CaptionsNotRecognized('Не удалось надёжно распознать вокал: '
             f'{m["count"]} фраз. Проект не создан. Попробуй модель large-v3 и Demucs.')
    result,score=max(valid,key=lambda item:item[1])
    # Optional forced alignment: not required for ordinary editing.
    try:
        from alignment import available, align_existing
        if available():
            say('Пробую точное выравнивание WhisperX (подтверждённый текст не меняю)…')
            result=align_existing(audio,result,progress=say)
    except Exception as exc:
        say('WhisperX не смог уточнить тайминги, оставляю оценку Whisper: '+str(exc)[:120])
    say(f'Сформировано {len(result)} смысловых блоков. Распознавание песен может ошибаться: '
        'для исправлений используй корректор субтитров.')
    try:
        SongLibrary().save(audio,result,verified=False,source='whisper')
    except Exception as err:
        say('Не удалось записать черновик субтитров в библиотеку: '+str(err))
    return result
