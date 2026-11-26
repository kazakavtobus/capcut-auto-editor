"""Native CapCut export, validation, receipts. Never sends Telegram messages."""
import hashlib,json,os,subprocess,sys,time,uuid
from pathlib import Path
from song_library import APPDATA,SongLibrary,project_song
from diagnostics import report_exception,LOG_DIR
from export_names import publish_export

class ExportError(RuntimeError):pass

def export_root(settings):
    return Path(settings.get('export_root') or APPDATA/'exports').expanduser().resolve()

def project_info(path):
    p=Path(path).resolve()
    draft=(p/'draft_content.json').read_bytes()
    doc=json.loads(draft.decode('utf-8-sig'))
    duration=int(doc.get('duration',0))
    if not 0<duration<=180_000_000:raise ExportError('Не удалось проверить длительность проекта.')
    audio=project_song(p);record=SongLibrary().load(audio)
    if not record or not record.get('verified') or not record.get('rows'):
        raise ExportError('Сначала сохрани проверенные субтитры этой песни в библиотеке.')
    src=json.loads((p/'AutoAssets'/'sources.json').read_text(encoding='utf-8'))
    account=str(src.get('account',''))
    if account not in ('1','2'):raise ExportError('Не определён аккаунт проекта.')
    return {'project':str(p),'account':account,'song':Path(record.get('filename',audio.name)).stem,'duration':duration,'draft_sha256':hashlib.sha256(draft).hexdigest()}

def verify_mp4(path,duration):
    import av
    p=Path(path)
    if p.suffix.lower()!='.mp4' or not p.is_file() or not p.stat().st_size:raise ExportError('MP4 не найден.')
    try:
        with av.open(str(p),mode='r') as c:
            v=next((s for s in c.streams if s.type=='video'),None)
            a=next((s for s in c.streams if s.type=='audio'),None)
            if v is None or a is None:raise ExportError('В экспорте нет видео или звука.')
            fps=float(v.average_rate or 0)
            if (v.width,v.height)!=(1080,1920) or abs(fps-30)>0.01:
                raise ExportError(f'Ожидалось 1080×1920 / 30 FPS; получено {v.width}×{v.height} / {fps:g} FPS.')
            if abs(int(c.duration or 0)-duration)>max(250_000,round(duration*0.005)):
                raise ExportError('Длительность MP4 не совпадает с проектом.')
            if next(c.decode(video=0),None) is None:raise ExportError('Видео не декодируется.')
        with av.open(str(p),mode='r') as c:
            if next(c.decode(audio=0),None) is None:raise ExportError('Звук не декодируется.')
    except ExportError:raise
    except Exception as exc:raise ExportError('MP4 ещё не завершён или повреждён.') from exc
    return p

def native_command(project,folder='',mode='start'):
    if sys.platform!='win32':raise ExportError('Автоэкспорт CapCut доступен только на Windows.')
    script=Path(__file__).resolve().parent/'assets'/'capcut_export.ps1'
    if not script.is_file():raise ExportError('Не найден модуль Windows UI Automation.')
    # Folder names are normally identical to display titles, but CapCut may
    # retain a distinct draft_name in metadata. Use the saved display title.
    name=Path(project).name
    try:
        meta=json.loads((Path(project)/'draft_meta_info.json').read_text(encoding='utf-8-sig'))
        value=meta.get('draft_name')
        if isinstance(value,str) and value.strip():name=value
    except (OSError,ValueError,AttributeError):pass
    data=json.dumps({'project':name,'folder':str(folder),'mode':mode},ensure_ascii=True)
    try:
        proc=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)],
            input=data+'\n',text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=260,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ExportError('Не удалось запустить управление CapCut. Открой нужный проект вручную.') from exc
    expected='EXPORT_STARTED' if mode=='start' else 'CLOSE_ATTEMPTED'
    if proc.returncode or expected not in proc.stdout:
        report=LOG_DIR/'capcut-export.txt'
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text('Project: '+str(project)+'\nMode: '+mode+'\nExit code: '+str(proc.returncode)+'\n'+proc.stderr[:50000],encoding='utf-8')
        first=next((line for line in proc.stderr.splitlines() if line.startswith('STAGE:')),proc.stderr.splitlines()[0] if proc.stderr.splitlines() else 'Нет ответа UI Automation')
        raise ExportError('CapCut не подтвердил действие.\n'+first[:500]+'\nДиагностика: '+str(report))

def wait_export(path,duration,timeout=900):
    deadline=time.monotonic()+timeout;last=None;stable=0;reason='Файл не появился.'
    while time.monotonic()<deadline:
        try:
            st=Path(path).stat();state=(st.st_size,st.st_mtime_ns)
            stable=stable+1 if state==last and st.st_size>0 else 0;last=state
            if stable>=3:
                try:return verify_mp4(path,duration)
                except ExportError as exc:reason=str(exc)
        except OSError:pass
        time.sleep(1)
    raise ExportError('Экспорт не подтверждён: '+reason)

def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def receipt(project):
    try:
        r=json.loads((Path(project)/'AutoAssets'/'export.json').read_text(encoding='utf-8'))
        if Path(r['path']).is_file() and r.get('account') in ('1','2') and isinstance(r.get('duration'),int):
            return r
    except (OSError,ValueError,KeyError,TypeError):pass
    return None

def export_one(project,settings,start=native_command,wait=wait_export):
    info=project_info(project);existing=receipt(project)
    if existing and existing.get('draft_sha256')==info['draft_sha256']:
        try:verify_mp4(existing['path'],info['duration']);return existing
        except ExportError:pass
    root=export_root(settings)
    folder=root/'.pending'/uuid.uuid4().hex
    folder.mkdir(parents=True,exist_ok=False)
    start(project,folder)
    p=wait(folder/'video.mp4',info['duration']);verify_mp4(p,info['duration'])
    # CapCut may save the draft during export; retain its actual final fingerprint.
    info['draft_sha256']=hashlib.sha256((Path(project)/'draft_content.json').read_bytes()).hexdigest()
    digest=file_digest(p)
    p=publish_export(p,root,settings,info['account'],info['song'])
    row=dict(info,path=str(p.resolve()),export_sha256=digest)
    dst=Path(project)/'AutoAssets'/'export.json';tmp=dst.with_suffix('.tmp')
    tmp.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(dst)
    try:folder.rmdir()
    except OSError:pass
    return row

def export_batch(projects,settings,progress=None,exporter=export_one,close=native_command):
    rows=[]
    for i,project in enumerate(projects,1):
        if progress:progress(f'Экспорт {i}/{len(projects)}: {Path(project).name}')
        try:rows.append(exporter(project,settings))
        except Exception as exc:
            report_exception(exc,'Автоэкспорт CapCut · '+str(project))
            return {'rows':rows,'error':str(exc),'remaining':list(map(str,projects[i-1:]))}
        if i<len(projects):
            try:close(project,mode='close')
            except Exception as exc:
                report_exception(exc,'Переход к следующему проекту CapCut')
                return {'rows':rows,'error':str(exc),'remaining':list(map(str,projects[i:]))}
    return {'rows':rows,'error':'','remaining':[]}
