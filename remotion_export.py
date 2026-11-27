"""Experimental local Remotion backend. Never drives CapCut or sends Telegram."""
import json, os, shutil, subprocess, sys, tempfile, queue, threading, time, logging, hashlib, math
from collections import deque
from pathlib import Path
from song_library import APPDATA
from native_export import ExportError, export_batch, export_one
from builder import media_info

FPS=30
ASSETS=Path(__file__).resolve().parent/'assets'/'remotion'
RUNTIME=APPDATA/'remotion'
BUNDLED=Path(sys.executable).resolve().parent/'remotion-runtime'

def bundled_runtime():
    return BUNDLED if getattr(sys,'frozen',False) and (BUNDLED/'node.exe').is_file() else None
LUT_NAME='Clayton 33.CUBE'

def frame(us):return round(int(us)*FPS/1_000_000)

def local_material(project,material):
    # Generated drafts embed their media. Never follow an arbitrary external path.
    name=Path(str(material['path']).replace('\\','/')).name
    base=(Path(project)/'AutoAssets').resolve()
    p=(base/name).resolve()
    if not p.is_relative_to(base) or not p.is_file():
        raise ExportError('Не найден локальный материал проекта: '+name)
    return p

def timeline(project):
    doc=json.loads((Path(project)/'draft_content.json').read_text(encoding='utf-8-sig'))
    materials=doc['materials']
    tracks=doc['tracks']
    if [t['type'] for t in tracks]!=['video','text','audio']:
        raise ExportError('Remotion: поддерживаются только видео, субтитры и одна музыка.')
    maps={k:{x['id']:x for x in materials[k]} for k in ('videos','texts','audios')}
    refs={x['id']:x for arr in materials.values() if isinstance(arr,list) for x in arr if isinstance(x,dict) and 'id' in x}
    duration=frame(doc['duration'])
    def times(seg):
        tr=seg['target_timerange']
        start=frame(tr['start']);end=frame(tr['start']+tr['duration'])
        return start,end-start
    videos=[];captions=[];expected=0
    for seg in tracks[0]['segments']:
        start,frames=times(seg)
        if start!=expected or frames<=0:raise ExportError('Remotion: некорректные границы видеоряда.')
        expected+=frames
        extras=[refs[x] for x in seg['extra_material_refs'] if x in refs]
        transition=next((x for x in extras if x.get('type')=='transition'),{})
        effects={x['type']:x.get('value') for x in extras if x.get('type') in ('brightness','contrast','lut')}
        videos.append(dict(path=str(local_material(project,maps['videos'][seg['material_id']])),start=start,frames=frames,
            sourceFrame=frame(seg['source_timerange']['start']),transition=frame(transition.get('duration',0)),
            brightness=float(effects.get('brightness',0) or 0),contrast=float(effects.get('contrast',0) or 0),
            lut=bool(effects.get('lut',0)),flip=bool((seg.get('clip') or {}).get('flip',{}).get('horizontal',False))))
    if expected!=duration:raise ExportError('Remotion: видеоряд не совпадает с длительностью проекта.')
    font=None
    for seg in tracks[1]['segments']:
        start,frames=times(seg)
        if frames<=0:continue
        text=maps['texts'][seg['material_id']]
        content=json.loads(text['content']);styles=content.get('styles') or [{}]
        font_path=styles[0].get('font',{}).get('path') or text.get('font_path')
        if not font_path:raise ExportError('Remotion: в эталоне не указан шрифт.')
        filename=Path(font_path.replace('\\','/')).name
        if font is not None and font!=filename:raise ExportError('Remotion: пока поддерживается один шрифт на проект.')
        font=filename
        transform=(seg.get('clip') or {}).get('transform') or {}
        anims=[a for rid in seg['extra_material_refs'] for a in refs.get(rid,{}).get('animations',[])]
        enter=next((frame(a['duration']) for a in anims if a.get('type')=='in'),0)
        exit=next((frame(a['duration']) for a in anims if a.get('type')=='out'),0)
        # Calibrated approximate CSS pixel size; CapCut's font unit is not CSS pixels.
        captions.append(dict(start=start,frames=frames,text=content['text'],fontSize=float(text.get('font_size',15))*4.6,
            color=text.get('text_color','#ffffff'),italic='italic' in filename.lower(),x=float(transform.get('x',0))*540,y=-float(transform.get('y',0))*960,
            enter=min(enter,frames),exit=min(exit,frames)))
    if not font or not captions:raise ExportError('Remotion: нет субтитров или шрифта.')
    if len(tracks[2]['segments'])!=1:raise ExportError('Remotion: нужна одна музыкальная дорожка.')
    seg=tracks[2]['segments'][0];start,frames=times(seg)
    audio=dict(path=str(local_material(project,maps['audios'][seg['material_id']])),start=start,frames=frames,
        sourceFrame=frame(seg['source_timerange']['start']),volume=float(seg.get('volume',1)))
    if start!=0 or frames!=duration:raise ExportError('Remotion: музыка должна покрывать весь проект.')
    account=str(json.loads((Path(project)/'AutoAssets'/'sources.json').read_text(encoding='utf-8')).get('account',''))
    if account not in CAPTION_FONTS:raise ExportError('Не определён аккаунт для выбора шрифта.')
    expected,style=CAPTION_FONTS[account]
    # Explicit per-account style takes priority over inconsistent CapCut metadata.
    for caption in captions:caption['italic']=style=='italic'
    return dict(durationFrames=duration,videos=videos,captions=captions,audio=audio,fontName=expected,fontStyle=style,fontWeight=600,account=account)

LUT_DIR=APPDATA/'remotion'/'luts'
CACHE_DIR=APPDATA/'remotion'/'clip-cache'

def import_lut(source):
    source=Path(source)
    if source.suffix.lower()!='.cube' or source.stat().st_size>25_000_000:
        raise ExportError('Нужен корректный файл .CUBE размером до 25 МБ.')
    data=source.read_bytes()
    size=None;count=0
    for line in data.decode('utf-8-sig').splitlines():
        line=line.split('#',1)[0].strip()
        if not line:continue
        parts=line.split()
        if parts[0]=='LUT_3D_SIZE':
            if len(parts)!=2 or size is not None:raise ExportError('Некорректный заголовок LUT.')
            size=int(parts[1])
            if not 2<=size<=128:raise ExportError('Неподдерживаемый размер 3D LUT.')
        elif parts[0] in ('TITLE','DOMAIN_MIN','DOMAIN_MAX'):continue
        else:
            if len(parts)!=3 or not all(math.isfinite(float(x)) for x in parts):
                raise ExportError('Некорректные данные 3D LUT.')
            count+=1
    if size is None or count!=size**3:raise ExportError('Неполный или некорректный 3D LUT.')
    LUT_DIR.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(data).hexdigest()
    target=LUT_DIR/(digest[:16]+'_'+source.name)
    if not target.is_file():
        with tempfile.NamedTemporaryFile(dir=LUT_DIR,delete=False) as f:
            tmp=Path(f.name);f.write(data)
        try:os.replace(tmp,target)
        finally:tmp.unlink(missing_ok=True)
    return target

def lut_label(settings):
    try:
        p=find_lut(settings)
        name=p.name.split('_',1)[-1] if p.parent==LUT_DIR else p.name
        return '✓ LUT подключён: '+name
    except (OSError,ValueError,ExportError):return 'LUT не подключён · выбери .CUBE'

def find_lut(settings):
    candidates=[Path(settings['remotion_lut'])] if settings.get('remotion_lut') else []
    candidates.extend([APPDATA/'remotion'/LUT_NAME,
        Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CapCut'/'User Data'/'Resources'/'Lut'/'Clayton 33'/LUT_NAME])
    for p in candidates:
        try:
            if p.is_file():return p
        except OSError:continue
    raise ExportError('Помести Clayton 33.CUBE в '+str(APPDATA/'remotion')+' или укажи путь remotion_lut в настройках.')

CAPTION_FONTS={'1':('InterTight-SemiBoldItalic.ttf','italic'),'2':('Onest-SemiBold.ttf','normal')}
FONT_DIR=APPDATA/'remotion'/'fonts'

def _font_signature(name):
    if name==CAPTION_FONTS['1'][0]:return 'intertight',True
    if name==CAPTION_FONTS['2'][0]:return 'onest',False
    raise ExportError('Неизвестный профиль шрифта: '+str(name))

def _validate_font(path,name,text=''):
    from fontTools.ttLib import TTFont
    family,italic=_font_signature(name)
    try:
        with TTFont(str(path),lazy=True) as font:
            names=[''.join(c for c in (font['name'].getDebugName(i) or '').lower() if c.isalnum()) for i in (1,4,6,16)]
            if not any(n.startswith(family) for n in names):raise ValueError('неверное семейство')
            os2=font['OS/2']
            actual_italic=bool(os2.fsSelection&1) or bool(font['head'].macStyle&2) or bool(font['post'].italicAngle)
            if actual_italic!=italic:raise ValueError('неверное курсивное начертание')
            axes={a.axisTag:a for a in font['fvar'].axes} if 'fvar' in font else {}
            if 'wght' in axes:
                if not axes['wght'].minValue<=600<=axes['wght'].maxValue:raise ValueError('нет веса 600')
            elif os2.usWeightClass!=600:raise ValueError('нужен SemiBold (600)')
            chars=font.getBestCmap() or {}
            missing=sorted({c for c in text if c.isalnum() and ord(c) not in chars})
            if missing:raise ValueError('отсутствуют символы: '+''.join(missing)[:40])
    except Exception as exc:raise ExportError(f'{path.name}: {exc}') from exc
    return Path(path)

def _font_candidates(name):
    family,_=_font_signature(name)
    roots=[FONT_DIR,Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts',
           Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Microsoft'/'Windows'/'Fonts']
    for root in roots:
        for suffix in ('.ttf','.otf'):
            yield root/(Path(name).stem+suffix)
        try:
            for p in root.iterdir():
                if p.suffix.lower() in ('.ttf','.otf') and family in ''.join(c for c in p.stem.lower() if c.isalnum()):yield p
        except OSError:pass
    if os.name=='nt':
        import winreg
        for hive,root in ((winreg.HKEY_LOCAL_MACHINE,roots[1]),(winreg.HKEY_CURRENT_USER,roots[2])):
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as k:
                    for i in range(winreg.QueryInfoKey(k)[1]):
                        label,value,_=winreg.EnumValue(k,i)
                        if family in ''.join(c for c in label.lower() if c.isalnum()) and isinstance(value,str):
                            p=Path(os.path.expandvars(value));yield p if p.is_absolute() else root/p
            except OSError:pass

def find_font(name,text=''):
    seen=set()
    for p in _font_candidates(name):
        if p in seen:continue
        seen.add(p)
        try:
            if p.is_file():return _validate_font(p,name,text)
        except (OSError,ExportError):continue
    raise ExportError('Не найден точный шрифт '+name+' с нужными символами. Настройки → Профили аккаунтов → Импорт шрифта (.ttf/.otf).')

def import_caption_font(account,source):
    name,_=CAPTION_FONTS[str(account)]
    source=Path(source)
    if source.suffix.lower() not in ('.ttf','.otf') or source.stat().st_size>30_000_000:
        raise ExportError('Выбери файл шрифта TTF или OTF.')
    _validate_font(source,name,'АБВабвЁёABCabc012')
    FONT_DIR.mkdir(parents=True,exist_ok=True)
    target=FONT_DIR/(Path(name).stem+source.suffix.lower())
    with tempfile.NamedTemporaryFile(dir=FONT_DIR,delete=False) as f:temp=Path(f.name)
    try:shutil.copy2(source,temp);os.replace(temp,target)
    finally:temp.unlink(missing_ok=True)
    return target

def caption_font_status(account):
    name,_=CAPTION_FONTS[str(account)]
    try:
        find_font(name,'АБВабвЁёABCabc012')
        return '✓ '+Path(name).stem+' · найден'
    except ExportError:return Path(name).stem+' · не найден'

def ffmpeg_exe():
    bundled=Path(sys.executable).resolve().parent/'ffmpeg.exe'
    return str(bundled) if getattr(sys,'frozen',False) and bundled.is_file() else (shutil.which('ffmpeg') or 'ffmpeg')

def run_command(args,cwd,timeout=1800):
    try:
        proc=subprocess.run(list(map(str,args)),cwd=str(cwd),capture_output=True,encoding='utf-8',errors='replace',
            timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired) as exc:raise ExportError('Remotion: не удалось выполнить команду: '+str(exc)) from exc
    if proc.returncode:raise ExportError('Remotion: '+(proc.stderr or proc.stdout)[-3000:])
    return proc.stdout

def run_render_stream(args,cwd,progress,timeout=3600):
    """Drain merged output continuously; keep bounded diagnostics and a watchdog."""
    logger=logging.getLogger('capcut_auto_editor')
    proc=subprocess.Popen(list(map(str,args)),cwd=str(cwd),stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',bufsize=1,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    lines=queue.Queue();tail=deque(maxlen=60)
    def reader():
        try:
            for line in proc.stdout:lines.put(line.rstrip())
        finally:lines.put(None)
    threading.Thread(target=reader,daemon=True).start()
    started=last_event=time.monotonic();last_stage='Запуск Remotion';ended=False
    try:
        while not ended or proc.poll() is None:
            now=time.monotonic()
            if now-started>timeout:raise ExportError('Remotion: превышен лимит времени рендера.')
            try:line=lines.get(timeout=1)
            except queue.Empty:
                if now-last_event>=15:
                    progress(last_stage+' · прошло '+str(int(now-started))+' с')
                    last_event=now
                continue
            if line is None:
                ended=True;continue
            tail.append(line)
            if line.startswith('PROGRESS '):
                try:pct=max(0,min(100,int(line.split()[1])))
                except (ValueError,IndexError):continue
                last_stage='Рендер Remotion: '+str(pct)+'%'
                progress(last_stage);last_event=now
            elif line.startswith(('STAGE:','ENCODER','GPU render failed')):
                last_stage=line;progress(line);last_event=now
            if not line.startswith('PROGRESS '):logger.info('Remotion: %s',line)
        if proc.wait()!=0:raise ExportError('Remotion: '+('\n'.join(tail))[-5000:])
    finally:
        if proc.poll() is None:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
            else:proc.kill()
            proc.wait(timeout=15)
        proc.stdout.close()

def prepare_runtime():
    packaged=bundled_runtime()
    if packaged:
        for name in ('render.cjs','index.jsx','node_modules/remotion/package.json','browser/chrome-headless-shell.exe'):
            if not (packaged/name).is_file():raise ExportError('Неполная установка Remotion: '+name)
        return str(packaged/'node.exe')
    node=shutil.which('node')
    if not node:raise ExportError('Установи Node.js 22 LTS, затем перезапусти Studio.')
    if int(run_command([node,'--version'],ASSETS,30).strip().lstrip('v').split('.')[0])<22:
        raise ExportError('Для Remotion нужен Node.js 22 или новее.')
    RUNTIME.mkdir(parents=True,exist_ok=True)
    package=(ASSETS/'package.json').read_bytes()
    marker=RUNTIME/'installed.json'
    for name in ('package.json','index.jsx','render.cjs'):
        shutil.copy2(ASSETS/name,RUNTIME/name)
    if not marker.is_file() or marker.read_bytes()!=package or not (RUNTIME/'node_modules'/'remotion'/'package.json').is_file():
        npm=shutil.which('npm')
        if os.name=='nt':
            candidates=[Path(node).parent/'node_modules'/'npm'/'bin'/'npm-cli.js']
            if npm:candidates.append(Path(npm).parent/'node_modules'/'npm'/'bin'/'npm-cli.js')
            cli=next((p for p in candidates if p.is_file()),None)
            if not cli:raise ExportError('Node.js установлен без npm.')
            command=[node,cli]
        elif npm:command=[npm]
        else:raise ExportError('npm не найден.')
        run_command(command+['install','--omit=dev','--no-audit','--no-fund'],RUNTIME,1800)
        marker.write_bytes(package)
    return node

def stage_assets(plan,work,settings,progress=lambda _:None):
    public=work/'public';public.mkdir()
    progress('Remotion: проверяю шрифт и LUT')
    expected=plan.pop('fontName')
    font=find_font(expected,''.join(c['text'] for c in plan['captions']))
    progress('Remotion: точный шрифт '+expected)
    font_name='caption'+font.suffix.lower();shutil.copy2(font,public/font_name);plan['font']=font_name
    plan['fontFamily']='StudioCaptionExact'+plan['account']
    lut_digest='none'
    if any(v['lut'] for v in plan['videos']):
        shutil.copy2(find_lut(settings),work/'lut.cube')
        lut_digest=hashlib.sha256((work/'lut.cube').read_bytes()).hexdigest()
    CACHE_DIR.mkdir(parents=True,exist_ok=True)
    seen={}
    total=len({(v['path'],v['brightness'],v['contrast'],v['lut']) for v in plan['videos']})
    for v in plan['videos']:
        source=v.pop('path');bright=v.pop('brightness');contrast=v.pop('contrast');lut=v.pop('lut')
        key=(source,bright,contrast,lut)
        if key not in seen:
            progress(f'Remotion: обработка футажа {len(seen)+1}/{total} · цветокоррекция')
            name=f'clip_{len(seen):03d}.mp4'
            filters='scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30'
            if lut:filters+=',lut3d=file=lut.cube'
            filters+=f',eq=brightness={bright}:contrast={1+contrast},format=yuv420p'
            from native_export import file_digest
            cache_key=hashlib.sha256(json.dumps(['v1',file_digest(Path(source)),filters,lut_digest if lut else 'none','libx264','veryfast','18']).encode()).hexdigest()
            cached=CACHE_DIR/(cache_key+'.mp4')
            if cached.is_file() and cached.stat().st_size>0:
                try:
                    shutil.copy2(cached,public/name);os.utime(cached,None)
                    progress(f'Remotion: футаж {len(seen)+1}/{total} из кэша')
                except OSError:
                    (public/name).unlink(missing_ok=True)
            if not (public/name).is_file():
                run_command([ffmpeg_exe(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',source,'-map','0:v:0','-an',
                  '-vf',filters,'-c:v','libx264','-preset','veryfast','-crf','18',public/name],work)
                try:
                    with tempfile.NamedTemporaryFile(dir=CACHE_DIR,delete=False) as f:temp=Path(f.name)
                    try:shutil.copy2(public/name,temp);os.replace(temp,cached)
                    finally:temp.unlink(missing_ok=True)
                except OSError:pass
            seen[key]=name
        v['file']=seen[key]
    try:
        files=sorted(CACHE_DIR.glob('*.mp4'),key=lambda x:x.stat().st_mtime,reverse=True)
        size=0
        for cached in files:
            size+=cached.stat().st_size
            if size>3_000_000_000:cached.unlink(missing_ok=True)
    except OSError:pass
    audio=plan['audio'];source=Path(audio.pop('path'));name='audio'+source.suffix.lower()
    shutil.copy2(source,public/name);audio['file']=name
    manifest=work/'manifest.json';manifest.write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
    return manifest,public

def render_to_folder(project,folder,settings,node=None,progress=lambda _:None):
    node=node or prepare_runtime()
    progress('Remotion: читаю таймлайн проекта')
    plan=timeline(project)
    with tempfile.TemporaryDirectory(prefix='remotion-',dir=folder) as tmp:
        work=Path(tmp);manifest,public=stage_assets(plan,work,settings,progress)
        output=Path(folder)/'video.mp4'
        runtime=bundled_runtime() or RUNTIME
        browser=runtime/'browser'/'chrome-headless-shell.exe'
        args=[node,runtime/'render.cjs',manifest,public,output,'auto',ffmpeg_exe()]
        if browser.is_file():args.append(browser)
        progress('Remotion: запуск движка и браузера')
        run_render_stream(args,runtime,progress)
        progress('Remotion: проверка готового MP4')
    if not output.is_file():raise ExportError('Remotion не создал MP4.')

def render_batch_background(projects,settings,progress=None):
    # The existing publisher validates MP4 and writes the same delivery receipts.
    # No close callback: no CapCut window exists in this flow.
    try:
        if progress:progress('Remotion: проверка локального движка и зависимостей…')
        node=prepare_runtime()
    except Exception as exc:return {'rows':[],'error':str(exc),'remaining':list(map(str,projects))}
    def exporter(project,config):
        def start(p,folder):render_to_folder(p,folder,config,node,progress or (lambda _:None))
        return export_one(project,config,start=start,engine='remotion-font-v2')
    return export_batch(projects,settings,progress,exporter=exporter,close=lambda *a,**kw:None)
