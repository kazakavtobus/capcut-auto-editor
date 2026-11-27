"""Persistent local footage library. No network sources."""
import hashlib
import itertools
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
import re
from song_library import APPDATA, song_hash, project_song

LENGTH=5_000_000
MIN_FOOTAGE_US=3_000_000
RECENT=4
MAX_RECENT=25
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
            CREATE TABLE IF NOT EXISTS renders(id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT,path TEXT UNIQUE,created REAL,sequence TEXT, song TEXT);
            CREATE TABLE IF NOT EXISTS used(render_id INTEGER,clip_id TEXT,position INTEGER,PRIMARY KEY(render_id,position));
            """)
            c.execute('BEGIN IMMEDIATE')
            # Remove global uniqueness without deleting past projects or clip usage.
            unique_sequence=False
            for idx in c.execute('PRAGMA index_list(renders)').fetchall():
                if idx['unique']:
                    name=idx['name'].replace('"','""')
                    if [r['name'] for r in c.execute(f'PRAGMA index_info("{name}")')]==['sequence']:
                        unique_sequence=True
            if unique_sequence:
                seq=c.execute("SELECT seq FROM sqlite_sequence WHERE name='renders'").fetchone()
                c.execute("""CREATE TABLE renders_v813(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account TEXT,path TEXT UNIQUE,created REAL,sequence TEXT,song TEXT)""")
                c.execute("""INSERT INTO renders_v813(id,account,path,created,sequence,song)
                    SELECT id,account,path,created,sequence,song FROM renders""")
                c.execute('DROP TABLE renders')
                c.execute('ALTER TABLE renders_v813 RENAME TO renders')
                if seq:
                    c.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='renders'",(seq[0],))
            c.execute('CREATE INDEX IF NOT EXISTS used_clip_history ON used(clip_id,render_id)')
            c.execute('CREATE INDEX IF NOT EXISTS render_sequence_history ON renders(sequence,id)')
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
        count=duration//LENGTH+int(duration%LENGTH>=MIN_FOOTAGE_US)
        if not count:
            say(f'{source.name}: пропущено, видео короче 3 секунд')
            return 0
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
                if actual<MIN_FOOTAGE_US:
                    say(f'{source.name}: пропущен фрагмент короче 3 секунд')
                    continue
                ffmpeg(['-ss',str(min(1,actual/2_000_000)),'-i',clip,'-frames:v','1','-vf','scale=180:-1',preview])
                if not preview.is_file():ffmpeg(['-i',clip,'-frames:v','1','-vf','scale=180:-1',preview])
                if not preview.is_file():raise RuntimeError('Не удалось получить кадр видео.')
                rows.append((key,digest,i,str(self.root/'clips'/clip.name),str(self.root/'previews'/preview.name),actual))
            if not rows:return 0
            with self.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('SELECT 1 FROM sources WHERE id=?',(digest,)).fetchone():return 0
                shutil.move(tmp/original.name,original)
                for key,_,i,clip,preview,_duration in rows:
                    shutil.move(tmp/(key+'.mp4'),clip);shutil.move(tmp/(key+'.jpg'),preview)
                c.execute('INSERT INTO sources VALUES(?,?,?,?)',(digest,source.name,str(original.relative_to(self.root)),category))
                c.executemany('INSERT INTO clips(id,source,idx,path,preview,duration_us) VALUES(?,?,?,?,?,?)',[(key,d,i,str(Path(p).relative_to(self.root)),str(Path(v).relative_to(self.root)),length) for key,d,i,p,v,length in rows])
        return len(rows)
    def refresh_durations(self,progress=None):
        """Recheck real video durations once per batch, including legacy database rows."""
        from builder import media_info
        updates=[]
        if progress:progress('Проверка длительности футажей медиатеки…')
        for row in self.clips():
            if not row['enabled']:continue
            try:actual=int(media_info(Path(row['path']),'video')['duration'])
            except Exception:actual=0
            if actual!=row['duration_us']:updates.append((max(0,actual),row['id']))
        if updates:
            with self.connect() as c:c.executemany('UPDATE clips SET duration_us=? WHERE id=?',updates)
    def choose(self,count,distinct_sources=False,song=None):
        """Prefer fresh and rare footage, but never block solely on usage history."""
        if count<=0:raise ValueError('Нет монтажных интервалов.')
        pool=[r for r in self.clips() if r['enabled'] and r['duration_us']>=MIN_FOOTAGE_US and Path(r['path']).is_file()]
        if len(pool)<count:
            raise LibraryShortage(f'Нужно минимум {count} разных активных фрагментов от 3 секунд, доступно {len(pool)}.')
        # Dynamic shared history, with soft fallback for small libraries.
        recent_limit=min(MAX_RECENT,max(RECENT,(len(pool)-count)//count))
        with self.connect() as c:
            ids=[r[0] for r in c.execute('SELECT id FROM renders ORDER BY id DESC LIMIT ?',(recent_limit,))]
            song_uses={r[0]:r[1] for r in c.execute('SELECT used.clip_id,count(*) FROM used JOIN renders ON renders.id=used.render_id WHERE renders.song=? GROUP BY used.clip_id',(song,))} if song else {}
            recent={}
            for i,rid in enumerate(ids):
                for row in c.execute('SELECT clip_id FROM used WHERE render_id=?',(rid,)):
                    recent[row[0]]=max(recent.get(row[0],0),len(ids)-i)
            sequences={r[0]:r[1] for r in c.execute('SELECT sequence,max(id) FROM renders GROUP BY sequence')}
            last=c.execute('SELECT sequence FROM renders ORDER BY id DESC LIMIT 1').fetchone()
        previous=json.loads(last[0]) if last else []
        rng=random.SystemRandom()
        selected=[];sources=set()
        for _ in range(count):
            best=min(pool,key=lambda r:(recent.get(r['id'],0),song_uses.get(r['id'],0),int(distinct_sources and r['source'] in sources),r['uses'],r['last_use'] or 0,rng.random()))
            selected.append(best);sources.add(best['source']);pool.remove(best)
        def score(order):
            ids=[r['id'] for r in order]
            return (sequences.get(json.dumps(ids),0),
                    int(bool(previous) and ids[0]==previous[0]),
                    sum(a['source']==b['source'] for a,b in zip(order,order[1:])),
                    sum(a==b for a,b in zip(ids,previous)),rng.random())
        orders=itertools.permutations(selected) if count<=6 else [selected]+[rng.sample(selected,count) for _ in range(80)]
        result=list(min(orders,key=score))
        for row in result:row['recent_reuse']=bool(recent.get(row['id'],0))
        return result
    def record(self,account,path,clips,song):
        ids=[x['id'] for x in clips]
        with self.connect() as c:
            cursor=c.execute('INSERT INTO renders(account,path,created,sequence,song) VALUES(?,?,?,?,?)',(account,str(path),time.time(),json.dumps(ids),song))
            c.executemany('INSERT INTO used VALUES(?,?,?)',[(cursor.lastrowid,x,i) for i,x in enumerate(ids)])
    def projects(self):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM renders ORDER BY id DESC')]
    def find_song(self,key):
        if not re.fullmatch(r'[a-f0-9]{64}',str(key)):return None
        for p in (self.root/'songs').glob(key+'.*'):
            try:
                if p.is_file() and song_hash(p)==key:return p
            except OSError:continue
        # Recover legacy library audio from previously generated embedded projects.
        for row in self.projects():
            if row.get('song')!=key:continue
            try:
                p=project_song(Path(row['path']))
                if song_hash(p)==key:return self.store_song(p)
            except (OSError,ValueError):continue
        return None

    def store_song(self,audio):
        p=Path(audio); key=song_hash(p)
        target=self.root/'songs'/(key+p.suffix.lower())
        if not target.exists() or song_hash(target)!=key:
            with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:tmp=Path(f.name)
            try:shutil.copy2(p,tmp);os.replace(tmp,target)
            finally:tmp.unlink(missing_ok=True)
        return target
