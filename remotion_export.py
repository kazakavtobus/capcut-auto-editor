"""Experimental local Remotion backend. Never drives CapCut or sends Telegram."""
import json, os, shutil, subprocess, sys, tempfile
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
    return dict(durationFrames=duration,videos=videos,captions=captions,audio=audio,fontName=font)

def find_lut(settings):
    candidates=[Path(settings['remotion_lut'])] if settings.get('remotion_lut') else []
    candidates.extend([APPDATA/'remotion'/LUT_NAME,
        Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CapCut'/'User Data'/'Resources'/'Lut'/'Clayton 33'/LUT_NAME])
    for p in candidates:
        if p.is_file():return p
    raise ExportError('Помести Clayton 33.CUBE в '+str(APPDATA/'remotion')+' или укажи путь remotion_lut в настройках.')

def find_font(name):
    if Path(name).name!=name:raise ExportError('Некорректное имя шрифта.')
    candidates=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name,
        Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Microsoft'/'Windows'/'Fonts'/name]
    for p in candidates:
        if p.is_file():return p
    raise ExportError('Установи точный шрифт из эталона: '+name)

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

def stage_assets(plan,work,settings):
    public=work/'public';public.mkdir()
    font=find_font(plan.pop('fontName'))
    font_name='caption'+font.suffix.lower();shutil.copy2(font,public/font_name);plan['font']=font_name
    if any(v['lut'] for v in plan['videos']):shutil.copy2(find_lut(settings),work/'lut.cube')
    seen={}
    for v in plan['videos']:
        source=v.pop('path');bright=v.pop('brightness');contrast=v.pop('contrast');lut=v.pop('lut')
        key=(source,bright,contrast,lut)
        if key not in seen:
            name=f'clip_{len(seen):03d}.mp4'
            filters='scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30'
            if lut:filters+=',lut3d=file=lut.cube'
            filters+=f',eq=brightness={bright}:contrast={1+contrast},format=yuv420p'
            run_command([ffmpeg_exe(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',source,'-map','0:v:0','-an',
              '-vf',filters,'-c:v','libx264','-preset','veryfast','-crf','18',public/name],work)
            seen[key]=name
        v['file']=seen[key]
    audio=plan['audio'];source=Path(audio.pop('path'));name='audio'+source.suffix.lower()
    shutil.copy2(source,public/name);audio['file']=name
    manifest=work/'manifest.json';manifest.write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
    return manifest,public

def render_to_folder(project,folder,settings,node=None):
    node=node or prepare_runtime()
    plan=timeline(project)
    with tempfile.TemporaryDirectory(prefix='remotion-',dir=folder) as tmp:
        work=Path(tmp);manifest,public=stage_assets(plan,work,settings)
        output=Path(folder)/'video.mp4'
        runtime=bundled_runtime() or RUNTIME
        browser=runtime/'browser'/'chrome-headless-shell.exe'
        args=[node,runtime/'render.cjs',manifest,public,output,'auto',ffmpeg_exe()]
        if browser.is_file():args.append(browser)
        run_command(args,runtime,3600)
    if not output.is_file():raise ExportError('Remotion не создал MP4.')

def render_batch_background(projects,settings,progress=None):
    # The existing publisher validates MP4 and writes the same delivery receipts.
    # No close callback: no CapCut window exists in this flow.
    try:
        if progress:progress('Remotion: проверка локального движка и зависимостей…')
        node=prepare_runtime()
    except Exception as exc:return {'rows':[],'error':str(exc),'remaining':list(map(str,projects))}
    def exporter(project,config):
        def start(p,folder):render_to_folder(p,folder,config,node)
        return export_one(project,config,start=start,engine='remotion')
    return export_batch(projects,settings,progress,exporter=exporter,close=lambda *a,**kw:None)
