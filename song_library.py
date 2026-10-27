"""Persistent, local, opt-in song caption library.

Verified human edits outrank every speech recognition model. The data directory
never lives in the application or GitHub checkout, and JSON writes are atomic.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from semantic_captions import clean_caption

MICRO = 1_000_000
APPDATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CapCutAutoEditor'


def song_hash(audio: Path) -> str:
    h = hashlib.sha256()
    with Path(audio).open('rb') as fd:
        for chunk in iter(lambda: fd.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _valid_rows(rows):
    result = []
    for row in rows:
        if isinstance(row, dict):
            a = round(float(row['start']) * MICRO)
            b = round(float(row['end']) * MICRO)
            txt = row['text']
        else:
            a, b, txt = row
            a, b = int(a), int(b)
        txt = clean_caption(str(txt))
        if not txt or a < 0 or b <= a:
            raise ValueError('Неверный текст или таймкод сохранённой фразы.')
        result.append((a, b, txt))
    result.sort(key=lambda x: x[0])
    for p, q in zip(result, result[1:]):
        if q[0] < p[1] - 1000:
            raise ValueError('В субтитрах обнаружено пересечение временных блоков.')
    return result


class SongLibrary:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else APPDATA / 'song_library'

    def _path(self, audio: Path) -> Path:
        return self.directory / (song_hash(audio) + '.json')

    def load(self, audio: Path):
        path = self._path(audio)
        if not path.is_file():
            # Migration of V6/V7 files, which saved hand-edited captions as SRT.
            legacy = APPDATA / 'corrected_captions' / (song_hash(audio) + '.srt')
            if legacy.is_file():
                from builder import parse_srt
                rows = _valid_rows(parse_srt(legacy))
                if rows:
                    self.save(audio, rows, verified=True, source='legacy-editor')
                    return self.load(audio)
            return None
        doc = json.loads(path.read_text(encoding='utf-8'))
        if doc.get('sha256') != song_hash(audio):
            raise ValueError('Не совпал отпечаток файла песни.')
        doc['rows'] = _valid_rows(doc.get('captions', []))
        return doc

    def save(self, audio: Path, rows, *, verified: bool, source: str, display_name: str | None = None):
        audio = Path(audio)
        clean = _valid_rows(rows)
        if not clean:
            raise ValueError('Нельзя сохранить пустой набор субтитров.')
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(audio)
        prior = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        if prior and prior.get('verified') and not verified:
            # Machine-generated captions must NEVER overwrite verified edits.
            return path
        title = re.sub(r'^Автомонтаж\s*[—-]\s*', '', display_name or audio.name,flags=re.I).strip()
        doc = {
            'format_version': 1,
            'sha256': song_hash(audio),
            'filename': title or audio.name,
            'verified': bool(verified),
            'source': source,
            'edited_utc': datetime.now(timezone.utc).isoformat(),
            'captions': [{'start': a / MICRO, 'end': b / MICRO, 'text': t}
                         for a, b, t in clean],
        }
        fd, temp = tempfile.mkstemp(prefix='.song-', suffix='.json', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(doc, out, ensure_ascii=False, indent=2)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return path


def project_song(project: Path) -> Path:
    assets = Path(project) / 'AutoAssets'
    songs = [f for f in assets.glob('song.*') if f.is_file()]
    if len(songs) != 1:
        raise ValueError('Не найден один исходный файл песни в AutoAssets/song.*')
    return songs[0]


def import_project_corrections(project: Path, library: SongLibrary | None = None):
    """Import user edits made IN CapCut (after CapCut is closed)."""
    from subtitle_editor import _project_data
    project = Path(project)
    rows, _ = _project_data(project)
    if not rows:
        raise ValueError('В проекте нет субтитров для импорта.')
    path = (library or SongLibrary()).save(project_song(project), rows,
                                          verified=True, source='capcut-import', display_name=project.name)
    return len(rows), path
