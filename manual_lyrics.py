"""Manual caption editing for songs whose vocals Whisper cannot recognize."""
from pathlib import Path
from builder import parse_srt
from semantic_captions import clean_caption
from song_library import _valid_rows

def text_to_draft_rows(text: str, duration_us: int):
    lines=[clean_caption(line) for line in text.splitlines() if clean_caption(line)]
    if not lines:raise ValueError('Вставь текст песни: одна фраза на строку.')
    if len(lines)>150:raise ValueError('Можно добавить не больше 150 фраз.')
    if duration_us<=0 or duration_us<len(lines)*220_000:
        raise ValueError('Слишком много фраз для такой короткой песни.')
    margin=min(300_000,duration_us//50)
    width=(duration_us-margin)/len(lines)
    return _valid_rows([(round(margin+i*width),round(margin+(i+1)*width),text)
                        for i,text in enumerate(lines)])

def validate_manual_rows(rows, duration_us: int):
    if not rows:raise ValueError('Добавь хотя бы одну фразу.')
    rows=_valid_rows(rows)
    if any(t.upper() in ('ДОПИШИ ТЕКСТ','[ДОПИШИ ТЕКСТ]') for _,_,t in rows):
        raise ValueError('Замени заглушки на настоящий текст перед сохранением.')
    if rows[-1][1]>duration_us+100_000:
        raise ValueError('Последняя фраза заканчивается позже песни.')
    return rows

def import_srt_rows(path: Path, duration_us: int):
    return validate_manual_rows(parse_srt(Path(path)),duration_us)
