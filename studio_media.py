"""Persistent local footage library. No network sources."""
import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
from contextlib import contextmanager
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from song_library import APPDATA, song_hash

LENGTH=5_000_000
RECENT=4
CATEGORIES=('Город','Природа','Машины')
class LibraryShortage(ValueError): pass

def ffmpeg(args):
    bundled=Path(sys.executable).resolve().parent/'ffmpeg.exe'
    exe=str(bundled) if getattr(sys,'frozen',False) and bundled.is_file() else (shutil.which('ffmpeg') or 'ffmpeg')
    r=subprocess.run([exe,'-hide_banner','-loglevel','error','-nostdin','-y',*map(str,args)],
        capture_output=True,encoding='utf-8',errors='replace',timeout=300,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if r.returncode:raise RuntimeError('FFmpeg: '+r.stderr[-1400:])

class MediaLibrary:
    def __init__(self,root=None):
        self.root=(Path(root) if root else APPDATA/'studio').expanduser().resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        for name in ('originals','clips','previews','songs'):
            (self.root/name).mkdir(exist_ok=True)
        self.db=self.root/'library.sqlite3'
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,name TEXT,path TEXT,category TEXT);
            CREATE TABLE IF NOT EXISTS clips(id TEXT PRIMARY KEY,source TEXT,idx INTEGER,path TEXT,preview TEXT,enabled INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS renders(id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT,path TEXT UNIQUE,created REAL,sequence TEXT UNIQUE, song TEXT);
            CREATE TABLE IF NOT EXISTS used(render_id INTEGER,clip_id TEXT,position INTEGER,PRIMARY KEY(render_id,position));
            """)
            if not any(r[1]=="duration_us" for r in c.execute("PRAGMA table_info(clips)")):
                c.execute("ALTER TABLE clips ADD COLUMN duration_us INTEGER NOT NULL DEFAULT 5000000")
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=20)
        c.row_factory=sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()
    def clips(self):
        with self.connect() as c:
            rows=[dict(r) for r in c.execute("""SELECT clips.*,sources.name,sources.category,
            (SELECT count(*) FROM used WHERE clip_id=clips.id) AS uses,
            (SELECT max(render_id) FROM used WHERE clip_id=clips.id) AS last_use
            FROM clips JOIN sources ON sources.id=clips.source ORDER BY sources.name,idx""")]
        for row in rows:
            row['path']=str(self.root/row['path']);row['preview']=str(self.root/row['preview'])
        return rows
    def enabled(self,clip_id,value):
        with self.connect() as c:c.execute('UPDATE clips SET enabled=? WHERE id=?',(int(value),clip_id))
    def rename_source(self,source_id,name):
        name=name.strip()
        if not name or len(name)>120:raise ValueError('Укажи название до 120 символов.')
        with self.connect() as c:
            c.execute('UPDATE sources SET name=? WHERE id=?',(name,source_id))

    def remove_media(self,clip_id,whole_source=False):
        """Remove from active library; keep history and move only owned files to trash."""
        import uuid
        moved=[]
        trash=self.root/'trash'/uuid.uuid4().hex
        try:
            with self.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute('SELECT * FROM clips WHERE id=?',(clip_id,)).fetchone()
                if not row:raise ValueError('Фрагмент уже удалён.')
                sid=row['source']
                clips=c.execute('SELECT * FROM clips WHERE source=?',(sid,)).fetchall() if whole_source else [row]
                targets=[(r[k],folder) for r in clips for k,folder in (('path','clips'),('preview','previews'))]
                if whole_source:
                    src=c.execute('SELECT path FROM sources WHERE id=?',(sid,)).fetchone()
                    if src:targets.append((src['path'],'originals'))
                for value,folder in targets:
                    p=(self.root/value).resolve()
                    owned=(self.root/folder).resolve()
                    if not p.is_relative_to(owned):raise ValueError('Файл находится вне управляемой медиатеки.')
                    if p.is_file():
                        dest=trash/folder/p.name
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        shutil.move(p,dest);moved.append((p,dest))
                c.executemany('DELETE FROM clips WHERE id=?',[(r['id'],) for r in clips])
                if whole_source:c.execute('DELETE FROM sources WHERE id=?',(sid,))
        except Exception:
            for p,dest in reversed(moved):
                if dest.exists():shutil.move(dest,p)
            raise

    def import_video(self,source,category,progress=None):
        from builder import media_info
        say=progress or (lambda x:None)
        source=Path(source).resolve()
        if category not in CATEGORIES:raise ValueError('Выбери категорию видео.')
        digest=song_hash(source)
        with self.connect() as c:
            if c.execute('SELECT 1 FROM sources WHERE id=?',(digest,)).fetchone():return 0
        duration=media_info(source,'video')['duration']
        if duration<=0:raise ValueError('Не удалось определить длительность видео.')
        count=max(1,math.ceil(duration/LENGTH))
        # Keep short originals; ignore only sub-frame remnants of long files.
        if count>1 and duration-(count-1)*LENGTH<100_000:count-=1
        original=self.root/'originals'/(digest+source.suffix.lower())
        rows=[]
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            tmp=Path(tmp)
            shutil.copy2(source,tmp/original.name)
            for i in range(count):
                say(f'{source.name}: фрагмент {i+1}/{count}')
                key=f'{digest}-{i:05d}'
                clip=tmp/(key+'.mp4'); preview=tmp/(key+'.jpg')
                seconds=min(5,(duration-i*LENGTH)/1_000_000)
                ffmpeg(['-ss',str(i*5),'-i',source,'-t',str(seconds),'-map','0:v:0','-an',
                    '-vf','scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,hue=s=0,format=yuv420p',
                    '-c:v','libx264','-crf','19','-preset','veryfast','-movflags','+faststart',clip])
                actual=media_info(clip,'video')['duration']
                if actual<=0:raise RuntimeError('Пустой фрагмент.')
                ffmpeg(['-ss',str(min(1,actual/2_000_000)),'-i',clip,'-frames:v','1','-vf','scale=180:-1',preview])
                if not preview.is_file():ffmpeg(['-i',clip,'-frames:v','1','-vf','scale=180:-1',preview])
                if not preview.is_file():raise RuntimeError('Не удалось получить кадр видео.')
                rows.append((key,digest,i,str(self.root/'clips'/clip.name),str(self.root/'previews'/preview.name),actual))
            with self.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('SELECT 1 FROM sources WHERE id=?',(digest,)).fetchone():return 0
                shutil.move(tmp/original.name,original)
                for key,_,i,clip,preview,_duration in rows:
                    shutil.move(tmp/(key+'.mp4'),clip);shutil.move(tmp/(key+'.jpg'),preview)
                c.execute('INSERT INTO sources VALUES(?,?,?,?)',(digest,source.name,str(original.relative_to(self.root)),category))
                c.executemany('INSERT INTO clips(id,source,idx,path,preview,duration_us) VALUES(?,?,?,?,?,?)',[(key,d,i,str(Path(p).relative_to(self.root)),str(Path(v).relative_to(self.root)),length) for key,d,i,p,v,length in rows])
        return len(rows)
    def choose(self,count,distinct_sources=False):
        if count<=0:raise ValueError('Нет монтажных интервалов.')
        with self.connect() as c:
            recent={r[0] for r in c.execute('SELECT clip_id FROM used WHERE render_id IN (SELECT id FROM renders ORDER BY id DESC LIMIT ?)',(RECENT,))}
            sequences={r[0] for r in c.execute('SELECT sequence FROM renders')}
        available=[r for r in self.clips() if r['enabled'] and r['id'] not in recent and Path(r['path']).is_file()]
        if len(available)<count:raise LibraryShortage(f'Нужно {count} свежих фрагментов, доступно {len(available)}. Пополни базу: повторы в последних 4 проектах запрещены.')
        if distinct_sources and len({r['source'] for r in available})<count:
            raise LibraryShortage(f'Нужно {count} разных исходных видео со свежими фрагментами.')
        rng=random.SystemRandom()
        for attempt in range(80):
            pool=available.copy();result=[]
            for i in range(count):
                if distinct_sources:
                    used_sources={r['source'] for r in result}
                    options=[r for r in pool if r['source'] not in used_sources]
                else:
                    options=[r for r in pool if not result or r['source']!=result[-1]['source']]
                if not options:break
                options.sort(key=lambda r:(r['uses'],r['last_use'] or 0,rng.random()))
                best=options[0];result.append(best);pool.remove(best)
            if len(result)==count and json.dumps([r['id'] for r in result]) not in sequences:return result
        raise LibraryShortage('Не хватает разных исходников для уникальной последовательности. Добавь видео с другими сценами.')
    def record(self,account,path,clips,song):
        ids=[x['id'] for x in clips]
        with self.connect() as c:
            cursor=c.execute('INSERT INTO renders(account,path,created,sequence,song) VALUES(?,?,?,?,?)',(account,str(path),time.time(),json.dumps(ids),song))
            c.executemany('INSERT INTO used VALUES(?,?,?)',[(cursor.lastrowid,x,i) for i,x in enumerate(ids)])
    def projects(self):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM renders ORDER BY id DESC')]
    def store_song(self,audio):
        p=Path(audio); key=song_hash(p)
        target=self.root/'songs'/(key+p.suffix.lower())
        if not target.exists():
            with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:tmp=Path(f.name)
            try:shutil.copy2(p,tmp);os.replace(tmp,target)
            finally:tmp.unlink(missing_ok=True)
        return target
