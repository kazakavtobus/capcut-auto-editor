"""Local, versioned CapCut style profiles. No private templates in GitHub."""
from pathlib import Path
from datetime import datetime
import json, os, shutil, tempfile, uuid, zipfile
from builder import USER_TEMPLATE_ZIP, template_zip, load_original_zip, build, media_info
from song_library import APPDATA
from studio_media import ffmpeg

def profile_path(account, root=None):
    if str(account) not in ('1','2'):raise ValueError('Неизвестный аккаунт.')
    return Path(root or APPDATA/'studio')/('account_'+str(account)+'.zip') if root is not None or str(account)=='2' else USER_TEMPLATE_ZIP

def active_template(account,root=None):
    p=profile_path(account,root)
    if p.is_file():return p
    if str(account)=='1' and root is None:return template_zip()
    raise FileNotFoundError('Для аккаунта '+str(account)+' ещё нет эталона. Открой Настройки → Эталоны.')

def validate_template(path):
    with zipfile.ZipFile(path) as z:
        if z.testzip():raise ValueError('Повреждённый ZIP.')
        if any('\\' in n or n.startswith('/') or any(p in ('..','.') or ':' in p for p in n.split('/')) for n in z.namelist()):raise ValueError('Небезопасные имена файлов в ZIP.')
    d,m,t,_,_=load_original_zip(path)
    tracks=d['tracks'];materials=d['materials']
    if [x['type'] for x in tracks]!=['video','text','audio']:
        raise ValueError('Эталон должен иметь три дорожки: видео, субтитры, музыка. Без дополнительных дорожек.')
    if not all(x.get('segments') for x in tracks):raise ValueError('На каждой дорожке нужен хотя бы один элемент.')
    if len(tracks[2]['segments'])!=1:raise ValueError('Оставь одну музыкальную дорожку с одним аудиофрагментом.')
    if not all(materials.get(k) for k in ('videos','texts','audios')):raise ValueError('Не хватает материалов шаблона.')
    refs={x['id'] for k in ('videos','texts','audios') for x in materials[k]}
    for track in tracks:
        if any(s.get('material_id') not in refs for s in track['segments']):raise ValueError('В эталоне отсутствуют ссылки на материалы.')
    last=0
    for s in tracks[0]['segments']:
        r=s['target_timerange']
        if r['duration']<=0 or r['start']!=last:raise ValueError('Убери пустые промежутки и наложения на видеодорожке.')
        last=r['start']+r['duration']
    return d

def versions(account,root=None):
    p=profile_path(account,root)
    folder=p.parent/'profile_history'/('account_'+str(account))
    return sorted(folder.glob('*.zip'),reverse=True)

def install_template(account, source,root=None):
    """Validate before replacing, keep all prior versions. Source is ZIP or saved draft folder."""
    dest=profile_path(account,root);dest.parent.mkdir(parents=True,exist_ok=True)
    source=Path(source).resolve()
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        candidate=Path(tmp)/'candidate.zip'
        if source.is_dir():
            draft=source/'draft_content.json'
            if not draft.is_file():raise ValueError('Выбери папку отдельного проекта, содержащую draft_content.json.')
            data=json.loads(draft.read_text(encoding='utf-8-sig'))
            nested=source/'Timelines'/data['id']/'draft_content.json'
            if nested.is_file() and nested.stat().st_mtime_ns>draft.stat().st_mtime_ns:
                # CapCut may save the main timeline separately.
                newer=json.loads(nested.read_text(encoding='utf-8-sig'))
                if newer.get('id')==data['id']:data=newer
            with zipfile.ZipFile(candidate,'w',zipfile.ZIP_DEFLATED) as z:
                for f in source.rglob('*'):
                    if not f.is_file() or f.is_symlink():continue
                    rel=f.relative_to(source)
                    if rel.parts[0]=='AutoAssets' or f.name in ('draft_content.json','draft_content.json.bak','template-2.tmp'):
                        continue
                    # Large source videos aren't needed to preserve native styling.
                    if f.suffix.lower() in ('.mp4','.mov','.mkv','.avi','.webm','.mp3','.wav','.m4a','.flac'):continue
                    z.write(f,'template/'+rel.as_posix())
                content=json.dumps(data,ensure_ascii=False)
                z.writestr('template/draft_content.json',content)
                z.writestr('template/Timelines/'+data['id']+'/draft_content.json',content)
        else:shutil.copy2(source,candidate)
        validate_template(candidate)
        if dest.is_file():
            history=dest.parent/'profile_history'/('account_'+str(account));history.mkdir(parents=True,exist_ok=True)
            saved=history/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8]+'.zip')
            shutil.copy2(dest,saved)
        os.replace(candidate,dest)
    return dest

def create_reference(account,projects_folder,root=None,progress=None):
    """Generate a real, separate native draft to edit in CapCut. Never counts as production footage."""
    account=str(account)
    folder=Path(projects_folder).resolve()
    if not folder.is_dir():raise ValueError('Сначала выбери папку проектов CapCut.')
    try:template=active_template(account,root)
    except FileNotFoundError:
        template=active_template('1',root)
    validate_template(template)
    name='Эталон — Аккаунт '+account+' — '+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:5]
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        video=tmp/'sample.mp4';audio=tmp/'sample.wav';srt=tmp/'lyrics.srt'
        # Neutral calibration footage is ONLY for editing a style reference.
        ffmpeg(['-f','lavfi','-i','color=c=gray:size=720x1280:rate=30:duration=5','-an','-c:v','libx264','-pix_fmt','yuv420p',video])
        ffmpeg(['-f','lavfi','-i','anullsrc=r=44100:cl=stereo','-t','10','-c:a','pcm_s16le',audio])
        duration=media_info(audio,'audio')['duration']
        srt.write_text('1\n00:00:00,000 --> 00:00:03,000\nПример текста\n\n2\n00:00:03,000 --> 00:00:06,000\nНовый стиль\n\n3\n00:00:06,000 --> 00:00:09,500\nСлова песни\n',encoding='utf-8')
        # Keep original cut rhythm rather than force a new template rhythm.
        from studio_pipeline import bounded_cuts
        d=load_original_zip(template)[0]
        reference=[s['target_timerange']['start']+s['target_timerange']['duration'] for s in d['tracks'][0]['segments']]
        bounds=bounded_cuts(reference,duration,[])
        project,_=build(str(audio),[str(video)]*len(bounds),str(folder),name,
                         srt_file=str(srt),beats_override=[],local_boundaries=bounds,
                         template_path=template,progress=progress)
    return project
