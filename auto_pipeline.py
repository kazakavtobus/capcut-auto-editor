"""Song-only experimental workflow: Pinterest/stock -> editable CapCut draft.
Does not modify the original CapCut project. See README for Pinterest limits."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from builder import build, detect_beats, media_info, MICRO
from caption_engine import obtain_captions
from semantic_captions import clean_caption
from video_history import VideoHistory, fingerprint

BASE = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CapCutAutoEditor'
CACHE_DIR = CONFIG_DIR / 'search_cache'
API_CACHE_SECONDS = 24 * 3600
MAX_VIDEO_BYTES = 115 * 1024 * 1024
USER_AGENT = 'CapCutAutoEditorPersonal/3.0 (local video editor)'

class StockError(RuntimeError):
    pass

def unique_project_name(folder: Path, audio: Path) -> str:
    # Preserve original song's filename as closely as Windows allows.
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', audio.stem).strip().rstrip('.') or 'Музыка'
    if stem.upper() in {'CON','PRN','AUX','NUL','COM1','COM2','LPT1','LPT2'}:
        stem += '_'
    # Avoid Windows path-length errors in CapCut's already nested draft folder.
    stem=stem[:100].rstrip()
    if not (folder/stem).exists(): return stem
    for i in range(2,1000):
        proposed = f'{stem} ({i})'
        if not (folder/proposed).exists(): return proposed
    raise FileExistsError('Не удалось создать уникальное имя проекта.')

def _http_json(url: str, headers: dict | None = None) -> dict:
    hdrs={'User-Agent': USER_AGENT, 'Accept':'application/json'}
    if headers: hdrs.update(headers)
    req=Request(url, headers=hdrs)
    try:
        with urlopen(req, timeout=30) as r:
            raw=r.read(12*1024*1024)
        return json.loads(raw.decode('utf-8'))
    except HTTPError as exc:
        detail=exc.read(250).decode('utf-8', errors='replace')
        if exc.code==401 or exc.code==403:
            raise StockError('Источник видео отклонил API-ключ. Проверь ключ в настройках.') from exc
        if exc.code==429:
            raise StockError('Превышен лимит запросов к источнику видео. Попробуй позже.') from exc
        raise StockError(f'Ошибка видеостока HTTP {exc.code}: {detail}') from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise StockError(f'Не удалось связаться с источником видео: {exc}') from exc

def _cached_json(provider: str, query: str, url: str, headers: dict | None = None) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Include auth in the *hash*, never in the cache filename or its contents.
    digest=hashlib.sha256(f'{provider}|{query}|{url}|{headers}'.encode()).hexdigest()[:20]
    path=CACHE_DIR/f'{digest}.json'
    if path.exists() and time.time()-path.stat().st_mtime<API_CACHE_SECONDS:
        try: return json.loads(path.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError): pass
    data=_http_json(url, headers)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    tmp.replace(path)
    return data

def _allowed_media_url(url: str, provider: str) -> bool:
    parsed=urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname: return False
    host=parsed.hostname.lower()
    if provider=='pixabay':
        return host=='pixabay.com' or host.endswith('.pixabay.com')
    if provider=='pexels':
        return host=='pexels.com' or host.endswith('.pexels.com')
    return False

def _pixabay(query: str, api_key: str) -> list[dict]:
    url='https://pixabay.com/api/videos/?'+urlencode({
        'key':api_key,'q':query,'per_page':35,'safesearch':'true','order':'popular',
        'video_type':'film'})
    data=_cached_json('pixabay',query,url)
    out=[]
    for hit in data.get('hits',[]):
        renditions=hit.get('videos',{})
        options=[v for k in ('medium','small','large') if (v:=renditions.get(k))
                 and v.get('url') and v.get('width') and v.get('height')
                 and 0<int(v.get('size') or 0)<=MAX_VIDEO_BYTES]
        if not options: continue
        # Prefer upright / near-square clips. Choose medium when available.
        options.sort(key=lambda v: (v['height']>=v['width'], min(v['height'],1920),
                                    -(v.get('size') or 0)),reverse=True)
        v=options[0]
        if not _allowed_media_url(v['url'],'pixabay'): continue
        out.append({'id':f"pixabay-{hit['id']}", 'url':v['url'],
                    'page':hit.get('pageURL',''), 'creator':hit.get('user',''),
                    'query':query, 'duration':float(hit.get('duration') or 0),
                    'width':int(v['width']), 'height':int(v['height']),
                    'bytes':int(v.get('size') or 0), 'provider':'pixabay'})
    return out

def _pexels(query: str, api_key: str) -> list[dict]:
    url='https://api.pexels.com/v1/videos/search?'+urlencode({
        'query':query, 'orientation':'portrait', 'per_page':30})
    data=_cached_json('pexels',query,url,{'Authorization':api_key})
    out=[]
    for hit in data.get('videos',[]):
        options=[v for v in hit.get('video_files',[])
                 if v.get('link','').startswith('https://') and
                 (v.get('file_type') in ('video/mp4', None)) and
                 v.get('width') and v.get('height') and
                 _allowed_media_url(v['link'],'pexels')]
        if not options: continue
        options.sort(key=lambda v: (v['height']>=v['width'],
                   -abs(int(v['height'])-1280),-abs(int(v['width'])-720)),reverse=True)
        v=options[0]
        out.append({'id':f"pexels-{hit['id']}",'url':v['link'],
                    'page':hit.get('url',''), 'creator':(hit.get('user') or {}).get('name',''),
                    'query':query,'duration':float(hit.get('duration') or 0),
                    'width':int(v['width']), 'height':int(v['height']),
                    'bytes':0, 'provider':'pexels'})
    return out

def search_stock(provider: str, key: str, query: str) -> list[dict]:
    if not key.strip():
        raise StockError('Для автоматического скачивания видео нужен API-ключ Pixabay или Pexels.\n'
                         'Настрой его один раз в окне программы — потом потребуется только MP3.')
    if provider=='pixabay': return _pixabay(query, key.strip())
    if provider=='pexels': return _pexels(query, key.strip())
    raise StockError(f'Неизвестный источник видео: {provider}')

# Every search phrase within one theme stays visually coherent.
THEME_QUERIES = {
    'rain': ['rainy city streets night','wet city pavement rain','night rain city bokeh',
             'rain drops window city','rain on urban street','rainy skyscrapers','rain street lights',
             'urban rain evening','rainy neon city','rainy street reflection',
             'city rainfall night','rain wet asphalt'],
    'night': ['city skyline at night','city night lights','night city buildings',
              'urban night traffic','city neon at night','city street lights night',
              'aerial city night','city skyscrapers night','city night architecture',
              'street lamps city night','city after dark','night downtown'],
    'love': ['golden hour city rooftops','sunset city skyline','sunset urban streets',
             'golden hour buildings','city skyline sunset','sunset city silhouettes',
             'golden hour city view','sunset city balcony','pink sky city rooftops',
             'sunset street buildings','dusk skyline city','twilight city sunset'],
    'road': ['night car driving pov','highway driving at night','night motorway lights',
             'car windshield city night','car drive after dark','night road dashcam',
             'city night car windows','driving highway night lights','urban driving night',
             'night traffic from car','night road reflections','night road pov'],
    'energetic': ['neon city cyberpunk night','neon street night','neon storefront city',
                   'purple city lights','neon buildings city','city neon light reflections',
                   'neon lights street','neon lights downtown','night futuristic urban',
                   'blue purple neon city','urban city neon rain','night signs city'],
    'calm': ['foggy mountain forest','misty forest trees','foggy pine forest',
              'mist drifting through trees','quiet forest mist','forest nature haze',
              'mountains in mist','forest fog morning','misty woodland',
              'soft fog in forest','misty mountain trees','forest in fog'],
    'cinematic': ['cinematic city skyline dusk','cinematic urban skyline',
                  'city downtown cinematic','city rooftops cinematic','cinematic city architecture',
                  'urban cityscape cinematic','city high rise aerial','cinematic city buildings',
                  'city street cinematic','urban downtown street','dramatic skyline city',
                  'cinematic city view'],
}

def choose_theme(subtitles: list[tuple[int,int,str]], beats: list[int]) -> tuple[str,list[str]]:
    text=' '.join(x[2] for x in subtitles).lower()
    groups=[
        ('rain', ('дожд','слёз','слез','плак','пустот','один','боль','ушл','не верн','разлук')),
        ('night', ('ноч','темнот','луна','звёзд','звезд','бессон','фонар','ночн')),
        ('love', ('люб','сердц','нежн','солнц','обним','тепл','красив')),
        ('road', ('дорог','пути','уед','машин','бегу','беж','свобод')),
    ]
    for name,words in groups:
        if any(word in text for word in words): return name,list(THEME_QUERIES[name])
    if len(beats)>5:
        diff=sorted((b-a)/MICRO for a,b in zip(beats,beats[1:]) if b>a)
        if diff:
            mid=diff[len(diff)//2]
            if mid<.40:return 'energetic',list(THEME_QUERIES['energetic'])
            if mid>.72:return 'calm',list(THEME_QUERIES['calm'])
    return 'cinematic',list(THEME_QUERIES['cinematic'])

def pick_stock_videos(provider: str, key: str, searches: list[str], seed: str,
                      progress=None) -> list[dict]:
    status=progress or (lambda _:None)
    rng=random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:10],16))
    selected=[];used=set()
    # Keep requests few; cache Pixabay responses for at least 24h.
    queries=list(dict.fromkeys(searches[:3]+['city','nature','night','sunset']))
    for query in queries[:7]:
        if len(selected)>=3:break
        status(f'Ищу футажи: {query} ({len(selected)}/3)')
        candidates=search_stock(provider,key,query)
        rng.shuffle(candidates)
        candidates.sort(key=lambda c:(c['height']>c['width'],
                      c['height']/max(c['width'],1), c['height']>=720,
                      c['duration']>=8),reverse=True)
        for video in candidates:
            if video['id'] in used or video['duration'] < 5.0: continue
            if video['height']<480:continue
            selected.append(video);used.add(video['id'])
            break
    if len(selected)<3:
        raise StockError(f'Источник нашёл только {len(selected)} подходящих видео из трёх. '
                         'Попробуй другой API-ключ или повтори позже.')
    return selected

def download_video(item: dict, target: Path, progress=None) -> None:
    url=item['url']
    if not _allowed_media_url(url,item['provider']):
        raise StockError('Источник вернул неожиданный адрес видео — скачивание остановлено.')
    headers={'User-Agent': USER_AGENT}
    req=Request(url,headers=headers)
    tmp=target.with_suffix('.part')
    count=0
    try:
        with urlopen(req,timeout=60) as rsp, open(tmp,'wb') as f:
            final_url=rsp.geturl()
            if not _allowed_media_url(final_url,item['provider']):
                raise StockError('Видео переадресовано на неподдерживаемый сайт.')
            declared=int(rsp.headers.get('Content-Length') or 0)
            if declared>MAX_VIDEO_BYTES: raise StockError('Видео слишком большое для загрузки (>115 МБ).')
            while True:
                chunk=rsp.read(1024*1024)
                if not chunk:break
                count+=len(chunk)
                if count>MAX_VIDEO_BYTES:
                    raise StockError('Видео превысило ограничение 115 МБ.')
                f.write(chunk)
        if count<5000:
            raise StockError('Загружен подозрительно маленький файл. Попробуй другой ролик.')
        tmp.replace(target)
    finally:
        if tmp.exists():tmp.unlink(missing_ok=True)

def convert_for_capcut(src: Path, dst: Path) -> None:
    """Normalize footage using the verified packaged FFmpeg, with actionable errors."""
    import sys
    # The Windows installer places a standalone FFmpeg beside the application.
    bundled = Path(sys.executable).resolve().parent / 'ffmpeg.exe'
    exe = str(bundled) if getattr(sys, 'frozen', False) and bundled.is_file() else (
        shutil.which('ffmpeg') or 'ffmpeg')
    filt='scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,format=yuv420p'
    cmd=[exe,'-hide_banner','-loglevel','error','-y','-i',str(src),
         '-map','0:v:0','-t','18','-vf',filt,'-an',
         '-c:v','libx264','-crf','22','-preset','veryfast',
         '-movflags','+faststart',str(dst)]
    try:
        result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',
                              errors='replace',timeout=240,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f'FFmpeg не найден: {exe}. Переустанови последнюю версию приложения.') from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('FFmpeg превысил время обработки видео (240 секунд).') from exc
    except OSError as exc:
        raise RuntimeError(f'FFmpeg не удалось запустить ({exe}): {exc}') from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()[-1800:] or '(FFmpeg не выдал текст ошибки)'
        code = f'{result.returncode} / 0x{result.returncode & 0xffffffff:08X}'
        raise RuntimeError(
            f'FFmpeg не смог подготовить футаж {src.name}.\\n'
            f'Код завершения: {code}\\n'
            f'Исполняемый файл: {exe}\\n'
            f'{stderr}')
    if not dst.is_file() or dst.stat().st_size < 10_000:
        raise RuntimeError('FFmpeg не создал корректный MP4 после обработки.')
    if media_info(dst,'video')['duration'] < 4_500_000:
        raise RuntimeError('Скачанный ролик слишком короткий — нужен другой футаж.')


def to_srt(rows: list[tuple[int,int,str]], target: Path) -> None:
    def stamp(micro: int) -> str:
        ms=micro//1000
        return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    parts=[]
    for i,(st,en,txt) in enumerate(rows,1):
        txt = clean_caption(txt)
        if en>st and txt.strip():
            parts.append(f'{i}\n{stamp(st)} --> {stamp(en)}\n{txt}\n')
    target.write_text('\n'.join(parts),encoding='utf-8')

def run_auto(audio_path: str, projects_folder: str, provider: str,
             api_key: str, whisper_model: str = 'medium', progress=None,
             captions_override=None, beats_override=None,
             separate_vocals=False,
             search_override=None, project_name_override=None) -> tuple[Path,dict]:
    status=progress or (lambda _: None)
    audio=Path(audio_path).expanduser().resolve()
    target_folder=Path(projects_folder).expanduser().resolve()
    if not target_folder.is_dir(): raise ValueError('Не найдена папка проектов CapCut. Укажи её в настройках.')
    if not audio.is_file(): raise ValueError('Не найден музыкальный файл.')
    if provider != 'pinterest' and not api_key and search_override is None:
        raise StockError('Для этого видеостока нужен API-ключ. Выбери Pinterest в настройках.')
    name=project_name_override or unique_project_name(target_folder,audio)
    status('Анализ песни и ритма...')
    aud=media_info(audio,'audio')
    if aud['duration']>180*MICRO:
        raise ValueError('Поддерживаются песни до 3 минут.')
    beats=beats_override if beats_override is not None else detect_beats(audio)
    status('Подготовка субтитров...')
    captions=captions_override if captions_override is not None else obtain_captions(
        audio, aud['duration'], whisper_model, progress=status,
        separate_vocals=separate_vocals)
    captions = [(a,b,clean_caption(t)) for a,b,t in captions if clean_caption(t)]
    if not captions:
        raise RuntimeError('Не удалось создать субтитры. Проект не создан.')
    mood,queries=choose_theme(captions,beats)
    history=VideoHistory(CONFIG_DIR/'video_history.json')
    status(f'Тема ролика: {mood}. История видеоряда: без повторов 7 дней.')
    with tempfile.TemporaryDirectory(prefix='capcut_auto_v4_') as temp_dir:
        work=Path(temp_dir)
        if search_override is not None:
            clips = search_override
        elif provider == 'pinterest':
            from pinterest_source import download_three
            clips = download_three(queries, name, work/'pinterest_downloads', status, history=history,theme=mood)
        else:
            clips = pick_stock_videos(provider,api_key,queries,audio.name,status)
        if len(clips)!=3:raise ValueError('Нужно подобрать три видео.')
        paths=[]
        for i,item in enumerate(clips,1):
            status(f'Скачиваю видео {i}/3: {item.get("query", "футаж")}')
            raw=work/f'original_{i:02d}.mp4'
            if 'local_test_path' in item: shutil.copy2(item['local_test_path'],raw)
            else: download_video(item,raw)
            normalized=work/f'clip_{i:02d}.mp4'
            status(f'Подготавливаю видео {i}/3: 9:16, H.264, без звука...')
            convert_for_capcut(raw,normalized)
            paths.append(str(normalized))
            # Pinterest already checked the content in download_three.
            # For alternate providers and test sources, check here as well.
            if 'checked_sha256' not in item:
                sha,visual=fingerprint(raw)
                reason=history.reason(item,sha,visual)
                if reason:raise StockError(f'Видео {i}: {reason}. Не использую повторно.')
                history.add_candidate(item,sha,visual,mood)
        subtitle_srt=work/'lyrics.srt'
        to_srt(captions,subtitle_srt)
        status(f'Собираю редактируемый проект CapCut ({len(captions)} субтитров)...')
        project,info=build(str(audio),paths,str(target_folder),name,
                           srt_file=str(subtitle_srt),snap_to_beat=True,
                           beats_override=beats,embed_assets=True,
                           progress=status)
    # Build has moved all sources into the project's own AutoAssets folder.
    sources={'provider':provider,'mood':mood,'queries':queries,
             'credits':[{'page':it.get('page',''),'creator':it.get('creator',''),
                         'id':it.get('id','')} for it in clips]}
    assets_dir=project/'AutoAssets'
    (assets_dir/'sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2),encoding='utf-8')
    srt_target=assets_dir/'lyrics.srt'
    to_srt(captions,srt_target)
    history.commit()
    info.update({'mood':mood,'project':str(project),'stock_provider':provider,
                 'source_links':[c.get('page','') for c in clips]})
    status(f'Готово! Проект создан: {name}')
    return project,info

def settings_file() -> Path:
    return CONFIG_DIR/'settings.json'

def load_settings() -> dict:
    default={'provider':'pinterest','api_key':'',
             'projects_folder':str(Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) /
                      'CapCut'/'User Data'/'Projects'/'com.lveditor.draft'),
             'whisper_model':'medium','separate_vocals':False}
    p=settings_file()
    try:
        data=json.loads(p.read_text(encoding='utf-8'))
        default.update({k:v for k,v in data.items() if k in default and isinstance(v,type(default[k]))})
    except (OSError,json.JSONDecodeError):pass
    if default['whisper_model']=='small':
        default['whisper_model']='medium'
    # Migrating from V3: unused stock providers without an API key now use Pinterest.
    if default['provider'] in ('pixabay','pexels') and not default['api_key']:
        default['provider']='pinterest'
    return default

def save_settings(data:dict) -> None:
    CONFIG_DIR.mkdir(parents=True,exist_ok=True)
    p=settings_file()
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(p)
