"""Seven-day history of *used* source videos, stored outside application versions.

Pin IDs and URLs are checked before downloading. Hashes from downloaded assets catch
re-uploads and different encoding. We record only after the CapCut project succeeds.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

WEEK_SECONDS = 7 * 86400


def normalized_url(url: str) -> str:
    try:
        u=urlsplit(str(url))
        return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path.rstrip('/'),'',''))
    except (ValueError, TypeError):
        return ''


def source_id(item: dict) -> str:
    page=normalized_url(item.get('page',''))
    pin=re.search(r'/pin/(\d+)(?:/|$)',page)
    if pin:return 'pinterest:'+pin.group(1)
    val=str(item.get('id',''))
    if val and not re.fullmatch(r'pinterest-\d+',val):
        return str(item.get('provider',''))+':'+val
    return page


def sha_file(file: Path) -> str:
    h=hashlib.sha256()
    with file.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def _frame_hash(file: Path, second: float) -> str:
    """64-bit difference hash AND the mean RGB color of a sampled frame.

    A grayscale perceptual hash alone can falsely match different flat-color
    footage. Store color together with the hash to reduce those false matches.
    """
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-ss',str(second),'-i',str(file),
         '-frames:v','1','-vf','scale=9:8,format=rgb24','-f','rawvideo','pipe:1']
    try:
        proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=25)
        if proc.returncode or len(proc.stdout)!=9*8*3:return ''
    except (OSError,subprocess.TimeoutExpired):return ''
    pix=proc.stdout
    gray=[]
    for j in range(0,len(pix),3):
        r,g,b=pix[j:j+3]
        gray.append((77*r+150*g+29*b)//256)
    dhash=0
    for y in range(8):
        for x in range(8):
            dhash=(dhash<<1)|int(gray[y*9+x]>gray[y*9+x+1])
    mean=[sum(pix[j::3])//72 for j in (0,1,2)]
    return f'{dhash:016x}:'+''.join(f'{v:02x}' for v in mean)

def fingerprint(file: Path) -> tuple[str,list[str]]:
    return sha_file(file),[_frame_hash(file,sec) for sec in (0.5,2.5,4.5)]


def visually_same(a: list[str],b: list[str]) -> bool:
    if len(a)!=3 or len(b)!=3:return False
    distances=[]
    for x,y in zip(a,b):
        # Ignore old/partial signatures; exact SHA and pin ID still apply.
        if not x or not y or ':' not in x or ':' not in y:return False
        try:
            ha,ca=x.split(':');hb,cb=y.split(':')
            rgb_a=bytes.fromhex(ca);rgb_b=bytes.fromhex(cb)
            if len(rgb_a)!=3 or len(rgb_b)!=3:return False
            color=max(abs(i-j) for i,j in zip(rgb_a,rgb_b))
            distances.append(((int(ha,16)^int(hb,16)).bit_count(),color))
        except ValueError:return False
    return (sum(d<=6 and color<=24 for d,color in distances)>=2
            and min((d for d,color in distances if color<=24),default=65)<=3)


class VideoHistory:
    def __init__(self, path: Path, now=None):
        self.path=Path(path)
        self.now=now or time.time
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            entries=data['entries'] if isinstance(data,dict) else data
            if not isinstance(entries,list):raise ValueError('invalid history')
        except FileNotFoundError:
            entries=[]
        except (OSError, ValueError,KeyError) as exc:
            raise RuntimeError(f'История видео повреждена: {self.path}. Не буду повторять старые видео вслепую. '+str(exc)) from exc
        self.entries=[e for e in entries if isinstance(e,dict)]
        self.session=[]

    def _recent(self):
        threshold=self.now()-WEEK_SECONDS
        return (e for e in self.entries+self.session if float(e.get('used_at',0))>threshold)

    def reason(self, item:dict, sha='',visual=None):
        sid=source_id(item)
        url=normalized_url(item.get('page',''))
        for row in self._recent():
            if sid and row.get('source_id')==sid:return 'пин уже использован за последние 7 дней'
            if url and row.get('page')==url:return 'ссылка уже использована за последние 7 дней'
            if sha and row.get('sha256')==sha:return 'файл совпадает с ранее использованным'
            if visual and visually_same(visual,row.get('visual',[])):
                return 'кадры совпадают с ранее использованными'
        return ''

    def add_candidate(self,item,sha,visual,theme):
        if self.reason(item,sha,visual):raise ValueError('Повторное видео')
        self.session.append({'used_at':self.now(), 'source_id':source_id(item),
                             'page':normalized_url(item.get('page','')),
                             'sha256':sha,'visual':visual,'provider':item.get('provider',''),
                             'theme':theme})

    def commit(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        # No changes to history until a *complete* draft exists.
        threshold=self.now()-90*86400
        prev=[e for e in self.entries if float(e.get('used_at',0))>=threshold]
        obj={'version':1,'entries':prev+self.session}
        tmp=self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,self.path)
        self.entries=obj['entries']
        self.session=[]
