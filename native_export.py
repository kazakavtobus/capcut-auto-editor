"""Native CapCut export, validation, receipts. Never sends Telegram messages."""
import hashlib,json,os,subprocess,sys,time,uuid
from pathlib import Path
from song_library import APPDATA,SongLibrary,project_song
from diagnostics import report_exception,LOG_DIR
from export_names import publish_export

class ExportError(RuntimeError):pass

def activate_capcut_from_studio():
    """Best effort from the GUI thread while Studio owns the foreground.
    Do not select an ambiguous window or send synthetic input to other apps.
    """
    if sys.platform!='win32':return False
    try:
        import ctypes as ct
        from ctypes import wintypes as wt
        u=ct.WinDLL('user32',use_last_error=True)
        k=ct.WinDLL('kernel32',use_last_error=True)
        callback=ct.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
        u.EnumWindows.argtypes=[callback,wt.LPARAM];u.EnumWindows.restype=wt.BOOL
        u.GetWindowThreadProcessId.argtypes=[wt.HWND,ct.POINTER(wt.DWORD)];u.GetWindowThreadProcessId.restype=wt.DWORD
        u.IsWindowVisible.argtypes=[wt.HWND];u.IsWindowVisible.restype=wt.BOOL
        u.IsIconic.argtypes=[wt.HWND];u.IsIconic.restype=wt.BOOL
        u.GetClassNameW.argtypes=[wt.HWND,wt.LPWSTR,ct.c_int];u.GetClassNameW.restype=ct.c_int
        u.GetWindowTextW.argtypes=[wt.HWND,wt.LPWSTR,ct.c_int];u.GetWindowTextW.restype=ct.c_int
        u.ShowWindowAsync.argtypes=[wt.HWND,ct.c_int];u.ShowWindowAsync.restype=wt.BOOL
        u.SetForegroundWindow.argtypes=[wt.HWND];u.SetForegroundWindow.restype=wt.BOOL
        u.GetForegroundWindow.restype=wt.HWND
        k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD];k.OpenProcess.restype=wt.HANDLE
        k.QueryFullProcessImageNameW.argtypes=[wt.HANDLE,wt.DWORD,wt.LPWSTR,ct.POINTER(wt.DWORD)];k.QueryFullProcessImageNameW.restype=wt.BOOL
        k.CloseHandle.argtypes=[wt.HANDLE];k.CloseHandle.restype=wt.BOOL
        candidates=[]
        @callback
        def visit(hwnd,_):
            if not u.IsWindowVisible(hwnd):return True
            title=ct.create_unicode_buffer(512);cls=ct.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd,title,len(title));u.GetClassNameW(hwnd,cls,len(cls))
            name=title.value.strip().casefold();kind=cls.value.casefold()
            if not (name=='capcut' or name.startswith('capcut - ') or name.endswith(' - capcut')):return True
            if 'tooltip' in kind or 'splash' in kind or 'tray' in kind:return True
            if not ('qwindowicon' in kind or 'homepagex' in kind or 'mainwindow' in kind):return True
            pid=wt.DWORD();u.GetWindowThreadProcessId(hwnd,ct.byref(pid))
            process=k.OpenProcess(0x1000,False,pid.value)
            if not process:return True
            try:
                path=ct.create_unicode_buffer(32768);length=wt.DWORD(len(path))
                if k.QueryFullProcessImageNameW(process,0,path,ct.byref(length)) and Path(path.value).name.casefold()=='capcut.exe':
                    candidates.append(hwnd)
            finally:k.CloseHandle(process)
            return True
        u.EnumWindows(visit,0)
        foreground=u.GetForegroundWindow()
        if foreground in candidates and not u.IsIconic(foreground):return True
        if len(candidates)!=1:return False
        hwnd=candidates[0]
        if u.IsIconic(hwnd):u.ShowWindowAsync(hwnd,9)
        return bool(u.SetForegroundWindow(hwnd))
    except Exception:
        return False

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

def visual_fallback_allowed(mode,stderr):
    # Never retry automatically after an export may already have started.
    if mode=='close':return any(line.startswith('STAGE: close exact project |') for line in stderr.splitlines())
    return mode=='start' and any(line.startswith((
        'STAGE: open exact project |','STAGE: find editor export button |'
    )) for line in stderr.splitlines())

def _run_export_script(script,data,timeout):
    return subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',str(script)],
        input=data+'\n',text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=timeout,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

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
        proc=_run_export_script(script,data,260)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ExportError('Не удалось запустить управление CapCut. Открой нужный проект вручную.') from exc
    expected='EXPORT_STARTED' if mode=='start' else 'CLOSE_ATTEMPTED'
    native_stderr=proc.stderr
    if proc.returncode or expected not in proc.stdout:
        visual=script.with_name('capcut_visual_export.ps1')
        if visual.is_file() and visual_fallback_allowed(mode,native_stderr):
            try:
                proc=_run_export_script(visual,data,240)
                if proc.returncode==0 and expected in proc.stdout:return
                visual_stderr=proc.stderr
            except (OSError,subprocess.TimeoutExpired) as exc:
                visual_stderr='STAGE: visual execution | '+str(exc)
            report_text='UI Automation:\n'+native_stderr+'\nVisual fallback:\n'+visual_stderr
            first=next((line for line in visual_stderr.splitlines() if line.startswith('STAGE:')),visual_stderr[:500] or 'Visual fallback did not confirm export')
        else:
            report_text=native_stderr
            first=next((line for line in native_stderr.splitlines() if line.startswith('STAGE:')),native_stderr.splitlines()[0] if native_stderr.splitlines() else 'Нет ответа UI Automation')
        report=LOG_DIR/'capcut-export.txt'
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text('Project: '+str(project)+'\nMode: '+mode+'\nExit code: '+str(proc.returncode)+'\n'+report_text[:50000],encoding='utf-8')
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

def export_one(project,settings,start=native_command,wait=wait_export,engine='capcut'):
    info=project_info(project);existing=receipt(project)
    if existing and existing.get('draft_sha256')==info['draft_sha256'] and existing.get('engine','capcut')==engine:
        try:
            verify_mp4(existing['path'],info['duration'])
            if file_digest(existing['path'])==existing.get('export_sha256'):return existing
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
    row=dict(info,path=str(p.resolve()),export_sha256=digest,engine=engine)
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
