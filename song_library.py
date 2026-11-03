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


# A CapCut project keeps the ORIGINAL, automatically produced subtitles in
# AutoAssets/lyrics.srt, while user's edits live in its draft_content.json.
# Never consider an untouched auto transcript to be a verified correction.
def _caption_rows_differ(left, right, tolerance_us: int = 80_000) -> bool:
    if len(left) != len(right):
        return True
    for (a, b, text), (c, d, other) in zip(left, right):
        if clean_caption(text) != clean_caption(other):
            return True
        if abs(a - c) > tolerance_us or abs(b - d) > tolerance_us:
            return True
    return False


def _project_timeline(project: Path, baseline):
    """Find the most recently saved DIFFERENT text timeline. Read-only."""
    from subtitle_editor import _project_data
    root = Path(project)
    candidates = [root / 'draft_content.json']
    candidates.extend((root / 'Timelines').glob('*/draft_content.json'))
    candidates = [p for p in candidates if p.is_file()]
    for candidate in sorted(candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True):
        try:
            rows, _ = _project_data(candidate.parent)
            valid = _valid_rows(rows)
            if not _caption_rows_differ(valid, baseline):
                continue
            return valid, candidate.stat().st_mtime
        except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError):
            continue
    return None


def sync_previous_capcut_edits(audio: Path, projects_folder: Path,
                               *, library: SongLibrary | None = None, progress=None):
    """Import newer corrections from saved CapCut projects of the EXACT same audio.

    An unchanged project's original subtitles are never imported as human work.
    No existing CapCut project is modified.
    """
    from builder import parse_srt
    say = progress or (lambda _message: None)
    audio = Path(audio)
    folder = Path(projects_folder)
    library = library or SongLibrary()
    if not folder.is_dir() or not audio.is_file():
        return None
    existing = library.load(audio)
    saved_timestamp = 0.0
    if existing and existing.get('verified'):
        try:
            saved_timestamp = datetime.fromisoformat(existing['edited_utc']).timestamp()
        except (KeyError, TypeError, ValueError):
            pass
    fingerprint = song_hash(audio)
    audio_size = audio.stat().st_size
    matches = []
    for project in folder.iterdir():
        if not project.is_dir() or project.name.startswith('.'):
            continue
        assets = project / 'AutoAssets'
        baseline = assets / 'lyrics.srt'
        if not baseline.is_file():
            continue
        same_song = False
        for source in assets.glob('song.*'):
            if not source.is_file() or source.stat().st_size != audio_size:
                continue
            if song_hash(source) == fingerprint:
                same_song = True
                break
        if not same_song:
            continue
        try:
            initial = _valid_rows(parse_srt(baseline))
        except (ValueError, OSError, UnicodeDecodeError):
            continue
        saved = _project_timeline(project, initial)
        if saved is None:
            continue
        rows, edited_timestamp = saved
        # Never certify a damaged auto-generated placeholder project as
        # someone's lyrics. It must remain editable in CapCut instead.
        placeholder_count=sum(t=='[ДОПИШИ ТЕКСТ]' for _,_,t in rows)
        if (placeholder_count and
                placeholder_count / max(len(rows),1) >= 0.30):
            say(f'CapCut: пропускаю проект «{project.name}» — слишком много заглушек.')
            continue
        if edited_timestamp <= saved_timestamp + .01 or not rows:
            continue
        if existing and existing.get('verified') and not _caption_rows_differ(rows, existing['rows']):
            continue
        matches.append((edited_timestamp, project, rows))
    if not matches:
        return None
    _, project, rows = max(matches, key=lambda item: item[0])
    library.save(audio, rows, verified=True, source='capcut-previous-project',
                 display_name=project.name)
    say(f'CapCut: перенёс {len(rows)} исправленных субтитров из проекта «{project.name}».')
    return project
