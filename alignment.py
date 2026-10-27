"""Optional Russian forced word alignment via WhisperX.

It is separate from transcription, requires a local torch/whisperx installation,
and NEVER silently overwrites a confirmed human transcript. Any failure raises a
human-readable diagnostic; the calling UI can retain existing timings.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

from song_library import _valid_rows, MICRO

class AlignmentUnavailable(RuntimeError):
    pass


def available() -> bool:
    return importlib.util.find_spec('whisperx') is not None


def align_existing(audio: Path, rows: list, progress=None):
    if not available():
        raise AlignmentUnavailable('WhisperX не установлен. Сначала запусти install_alignment.bat из Python-версии.')
    import whisperx
    say = progress or (lambda _: None)
    rows = _valid_rows(rows)
    if not rows:
        raise ValueError('Нет фраз для синхронизации.')
    segments = [dict(start=a/MICRO, end=b/MICRO, text=t.replace('\n', ' '))
                for a,b,t in rows]
    say('WhisperX: загружаю русскую модель выравнивания…')
    model, metadata = whisperx.load_align_model(language_code='ru', device='cpu')
    say('WhisperX: выравниваю текст со звуком…')
    audio_data = whisperx.load_audio(str(audio))
    result = whisperx.align(segments, model, metadata, audio_data, 'cpu',
                            return_char_alignments=False)
    got = result.get('segments', [])
    out = []
    for (a,b,text), found in zip(rows,got):
        aligned = [w for w in found.get('words', [])
                   if isinstance(w.get('start'),(int,float)) and
                   isinstance(w.get('end'),(int,float)) and w['end']>w['start']]
        if aligned:
            new_a = max(0,round(float(aligned[0]['start'])*MICRO))
            new_b = round(float(aligned[-1]['end'])*MICRO)
            # Reject outliers: song lyrics can repeat and the model can align to
            # the wrong occurrence. Never move a block more than 750ms.
            if (new_b>new_a and abs(new_a-a)<=750_000 and abs(new_b-b)<=750_000):
                a,b = new_a,new_b
        out.append((a,b,text))
    # Keep all original text verbatim and reject overlaps. Caller approves changes.
    out = _valid_rows(out)
    if len(out)!=len(rows):
        raise RuntimeError('WhisperX вернул неполный результат — правки не применены.')
    say('Выравнивание закончено. Проверь тайминги перед сохранением.')
    return out
