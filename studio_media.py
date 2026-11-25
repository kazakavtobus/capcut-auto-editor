"""Persistent local footage library. No network sources."""
import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
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
    def connect(self):
        c=sqlite3.connect(self.db,timeout=20)
        c.row_factory=sqlite3.Row
        return c
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
    def import_video(self,source,category,progress=None):
        from builder import media_info
        say=progress or (lambda x:None)
        source=Path(source).resolve()
        if category not in CATEGORIES:raise ValueError('Выбери категорию видео.')
        digest=song_hash(source)
        with self.connect() as c:
            if c.execute('SELECT 1 FROM sources WHERE id=?',(digest,)).fetchone():return 0
        duration=media_info(source,'video')['duration']
        count=duration//LENGTH
        if not count:raise ValueError('Исходник должен быть не короче 5 секунд.')
        original=self.root/'originals'/(digest+source.suffix.lower())
        rows=[]
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            tmp=Path(tmp)
            shutil.copy2(source,tmp/original.name)
            for i in range(count):
                say(f'{source.name}: фрагмент {i+1}/{count}')
                key=f'{digest}-{i:05d}'
                clip=tmp/(key+'.mp4'); preview=tmp/(key+'.jpg')
                ffmpeg(['-ss',str(i*5),'-i',source,'-t','5','-map','0:v:0','-an',
                    '-vf','scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,hue=s=0,format=yuv420p',
                    '-c:v','libx264','-crf','19','-preset','veryfast','-movflags','+faststart',clip])
                if media_info(clip,'video')['duration']<4_950_000:raise RuntimeError('Не удалось получить полный пятисекундный фрагмент.')
                ffmpeg(['-ss','1','-i',clip,'-frames:v','1','-vf','scale=180:-1',preview])
                rows.append((key,digest,i,str(self.root/'clips'/clip.name),str(self.root/'previews'/preview.name)))
            with self.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('SELECT 1 FROM sources WHERE id=?',(digest,)).fetchone():return 0
                shutil.move(tmp/original.name,original)
                for key,_,i,clip,preview in rows:
                    shutil.move(tmp/(key+'.mp4'),clip);shutil.move(tmp/(key+'.jpg'),preview)
                c.execute('INSERT INTO sources VALUES(?,?,?,?)',(digest,source.name,str(original.relative_to(self.root)),category))
                c.executemany('INSERT INTO clips(id,source,idx,path,preview) VALUES(?,?,?,?,?)',[(key,d,i,str(Path(p).relative_to(self.root)),str(Path(v).relative_to(self.root))) for key,d,i,p,v in rows])
        return len(rows)
    def choose(self,count):
        if count<=0:raise ValueError('Нет монтажных интервалов.')
        with self.connect() as c:
            recent={r[0] for r in c.execute('SELECT clip_id FROM used WHERE render_id IN (SELECT id FROM renders ORDER BY id DESC LIMIT ?)',(RECENT,))}
            sequences={r[0] for r in c.execute('SELECT sequence FROM renders')}
        available=[r for r in self.clips() if r['enabled'] and r['id'] not in recent and Path(r['path']).is_file()]
        if len(available)<count:raise LibraryShortage(f'Нужно {count} свежих фрагментов, доступно {len(available)}. Пополни базу: повторы в последних 4 проектах запрещены.')
        rng=random.SystemRandom()
        for attempt in range(80):
            pool=available.copy();result=[]
            for i in range(count):
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
