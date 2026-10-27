"""Generate a separate editable CapCut draft using the user's verified CapCut template.

This is an experimental, unofficial manipulation of CapCut Desktop draft JSON.
Never edits the original draft. Tested structurally, not opened in CapCut Desktop.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from semantic_captions import clean_caption, two_line_layout

MICRO = 1_000_000
BASE = Path(__file__).resolve().parent
TEMPLATE_ZIP = BASE / 'template_original.zip'
USER_TEMPLATE_ZIP = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CapCutAutoEditor' / 'template_original.zip'

def template_zip():
    """Keep user-owned original CapCut drafts outside public releases."""
    if USER_TEMPLATE_ZIP.is_file():return USER_TEMPLATE_ZIP
    if TEMPLATE_ZIP.is_file():return TEMPLATE_ZIP
    raise FileNotFoundError('Сначала импортируй файл template_original.zip из V7.3 в настройках.')

def new_id() -> str:
    return str(uuid.uuid4()).upper()

def media_info(file: Path, media: str) -> dict:
    if not file.is_file():
        raise ValueError(f'Файл не найден: {file}')
    try:
        proc = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries',
            'format=duration:stream=codec_type,width,height', '-of', 'json', str(file)
        ], text=True, encoding='utf-8', errors='replace', capture_output=True, check=True)
        info = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise RuntimeError('Не удалось прочитать медиа через ffprobe. Установи FFmpeg и перезапусти программу.\n' + str(exc)) from exc
    dur = float(info.get('format', {}).get('duration', 0))
    if dur <= 0:
        raise ValueError(f'Нулевая длительность: {file.name}')
    streams = [s for s in info.get('streams', []) if s.get('codec_type') == media]
    if not streams:
        raise ValueError(f'В файле {file.name} нет дорожки типа {media}')
    return {'duration': int(dur * MICRO), 'width': int(streams[0].get('width', 0)),
            'height': int(streams[0].get('height', 0))}

def parse_srt(file: Path) -> list[tuple[int,int,str]]:
    raw = file.read_text(encoding='utf-8-sig').replace('\r\n', '\n').strip()
    result = []
    for block in re.split(r'\n\s*\n', raw):
        lines = block.strip().split('\n')
        line_ix = next((i for i, line in enumerate(lines) if '-->' in line), -1)
        if line_ix < 0:
            continue
        match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*'
                          r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})', lines[line_ix])
        if not match:
            raise ValueError(f'Не удалось разобрать таймкод SRT: {lines[line_ix]}')
        vals = list(map(int, match.groups()))
        def sec(a):
            return ((a[0]*3600+a[1]*60+a[2])*MICRO + int(str(a[3]).ljust(3,'0'))*1000)
        start, end = sec(vals[:4]), sec(vals[4:])
        caption = clean_caption(' '.join(lines[line_ix+1:]))
        if caption and end > start:
            result.append((start,end,caption))
    return sorted(result)

def whisper_captions(audio: Path, model_size: str = 'small') -> list[tuple[int,int,str]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('Для авто-субтитров запусти install_whisper.bat (потребуется интернет).') from exc
    model = WhisperModel(model_size, device='cpu', compute_type='int8')
    segments, _ = model.transcribe(str(audio), language='ru', word_timestamps=True,
                                   vad_filter=False, beam_size=5)
    words=[]
    for seg in segments:
        for w in seg.words or []:
            if w.word.strip():
                words.append((float(w.start), float(w.end), w.word.strip()))
    rows=[]
    block=[]
    for st,en,word in words:
        if block and ((en-block[0][0])>1.9 or (st-block[-1][1])>0.5 or len(block)>=6):
            rows.append((int(block[0][0]*MICRO),int(block[-1][1]*MICRO),' '.join(x[2] for x in block)))
            block=[]
        block.append((st,en,word))
    if block:
        rows.append((int(block[0][0]*MICRO),int(block[-1][1]*MICRO),' '.join(x[2] for x in block)))
    return rows

def detect_beats(audio: Path) -> list[int]:
    try:
        import librosa
        y, sr = librosa.load(str(audio), sr=11025, mono=True)
        _, frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=256, trim=False)
        return [int(x*MICRO) for x in librosa.frames_to_time(frames, sr=sr, hop_length=256)]
    except Exception as exc:
        raise RuntimeError('Не удалось найти доли музыки (librosa): '+str(exc)) from exc

def cut_ends(reference: list[int], total: int, beats: list[int]) -> list[int]:
    if not reference or total <= 0:
        raise ValueError('Некорректная структура шаблона')
    lengths = [reference[0]] + [reference[i]-reference[i-1] for i in range(1,len(reference))]
    raw=[]
    t=0
    while t < total:
        for length in lengths:
            t = min(t+length, total)
            raw.append(t)
            if t == total:
                break
    # Retain the reference's ~1–4 second editing rhythm, snap only near a detected beat.
    if beats:
        snapped=[]
        for i,target in enumerate(raw[:-1]):
            candidates = [b for b in beats if abs(b-target)<=80_000]
            proposed=min(candidates, key=lambda b:abs(b-target)) if candidates else target
            prev=snapped[-1] if snapped else 0
            if proposed-prev<650_000 or raw[i+1]-proposed<650_000:
                proposed=target
            snapped.append(proposed)
        raw=snapped+[total]
    return raw

def load_original_zip() -> tuple[dict,dict,dict,dict,str]:
    with zipfile.ZipFile(template_zip()) as z:
        root = z.namelist()[0].split('/')[0]
        def read(rel): return json.loads(z.read(root+'/'+rel))
        return read('draft_content.json'), read('draft_meta_info.json'),\
               read('Timelines/project.json'), read('Timelines/'+read('draft_content.json')['id']+'/attachment_editing.json'), root

def build(audio_file: str, video_files: list[str], projects_folder: str, project_name: str,
          srt_file: str = '', automatic_captions: bool = False, snap_to_beat: bool = True,
          progress=None, beats_override=None, embed_assets: bool = True) -> tuple[Path,dict]:
    def status(msg):
        if progress: progress(msg)
    audio=Path(audio_file).expanduser().resolve()
    videos=[Path(p).expanduser().resolve() for p in video_files]
    if len(videos)!=3:
        raise ValueError('Выбери ровно три видеоролика.')
    if not project_name.strip() or any(c in project_name for c in r'<>:"/\\|?*'):
        raise ValueError('В названии проекта запрещённые символы или оно пустое.')
    if not projects_folder:
        raise ValueError('Не указана папка проектов CapCut.')
    folder=Path(projects_folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError('Папка проектов CapCut не существует.')
    project_folder=folder/project_name
    if project_folder.exists():
        raise FileExistsError('Проект с таким названием уже существует. Выбери другое имя.')
    status('Проверка исходных файлов...')
    audinfo=media_info(audio,'audio'); vinfos=[media_info(v,'video') for v in videos]
    if audinfo['duration']>180*MICRO:
        raise ValueError('Текущая версия поддерживает песни длиной до 3 минут.')
    status('Чтение оригинального проекта...')
    data, meta, timeline_proj, _, root=load_original_zip()
    old_timeline=data['id']; old_draft=meta['draft_id']; new_timeline=new_id();new_draft=new_id()
    original_clips=data['tracks'][0]['segments']
    original_vid_mats=copy.deepcopy(data['materials']['videos'])
    original_vid_sources=list(dict.fromkeys(x['path'] for x in original_vid_mats))
    assert len(original_vid_sources)==3
    referenced_videos=[project_folder/'AutoAssets'/f'video_{i+1:02d}.mp4' for i in range(3)] if embed_assets else videos
    referenced_audio=(project_folder/'AutoAssets'/('song'+audio.suffix.lower())) if embed_assets else audio
    media_by_old={src:(referenced_videos[i],vinfos[i]) for i,src in enumerate(original_vid_sources)}
    original_txt=data['tracks'][1]['segments'][0]
    text_template=copy.deepcopy(next(x for x in data['materials']['texts'] if x['id']==original_txt['material_id']))
    refmap={x['id']:(cat,x) for cat,arr in data['materials'].items() if isinstance(arr,list)
              for x in arr if isinstance(x,dict) and x.get('id')}
    template_duration=data['duration']
    reference=[seg['target_timerange']['start']+seg['target_timerange']['duration']
               for seg in original_clips]
    status('Поиск ритма...' if snap_to_beat else 'Подготовка видеонарезки...')
    beat_points=(beats_override if beats_override is not None else detect_beats(audio)) if snap_to_beat else []
    boundaries=cut_ends(reference, audinfo['duration'], beat_points)
    mat=data['materials']
    expanded=[]; tstart=0
    # New objects point to original CapCut native LUT, transition and text animations.
    for j,tend in enumerate(boundaries):
        template_segment=original_clips[j % len(original_clips)]
        seg=copy.deepcopy(template_segment)
        old_vid=refmap[seg['material_id']][1]
        source_path=old_vid['path']
        new_path, mi=media_by_old[source_path]
        nlen=tend-tstart
        if mi['duration'] < nlen:
            raise ValueError(f'Видео {new_path.name} слишком короткое для фрагмента {nlen/MICRO:.2f} с. '
                             'Возьми ролик подлиннее (желательно от 6 секунд).')
        if j >= len(original_clips):
            # Duplicate all referenced effect/material objects with fresh IDs.
            vmat=copy.deepcopy(old_vid);vmat['id']=new_id();mat['videos'].append(vmat)
            refmap[vmat['id']]=('videos',vmat)
            seg['material_id']=vmat['id']
            newrefs=[]
            for rid in seg['extra_material_refs']:
                if rid not in refmap:
                    newrefs.append(rid); continue
                bucket,obj=refmap[rid]
                newobj=copy.deepcopy(obj);newobj['id']=new_id();mat[bucket].append(newobj)
                refmap[newobj['id']]=(bucket,newobj)
                newrefs.append(newobj['id'])
            seg['extra_material_refs']=newrefs
            seg['id']=new_id()
        # Use the original native transition on every internal clip boundary.
        transitions=[rid for rid in seg['extra_material_refs'] if refmap.get(rid,(None,))[0]=='transitions']
        if j==len(boundaries)-1:
            seg['extra_material_refs']=[rid for rid in seg['extra_material_refs'] if rid not in transitions]
        elif not transitions:
            trans=copy.deepcopy(mat['transitions'][0]);trans['id']=new_id()
            mat['transitions'].append(trans)
            refmap[trans['id']]=('transitions',trans)
            seg['extra_material_refs'].append(trans['id'])
        seg['target_timerange']={'start':tstart,'duration':nlen}
        # Original reference edit starts each source from the first frame.
        # Random offsets in V4 created inconsistent framing on repeated clips.
        seg['source_timerange']={'start':0,'duration':nlen}
        seg['render_timerange']={'start':0,'duration':0}
        seg['volume']=0.0;seg['clip']['flip']['horizontal']=True
        if j>=len(original_clips):
            vmat['path']=new_path.as_posix();vmat['duration']=mi['duration'];
            vmat['width']=mi['width'];vmat['height']=mi['height'];vmat['has_audio']=False
            vmat['material_name']=new_path.name
        expanded.append(seg);tstart=tend
    data['tracks'][0]['segments']=expanded
    # Update all original 8 video materials as well.
    for vmat in original_vid_mats:
        pass
    for vmat in mat['videos']:
        if vmat['path'] in media_by_old:
            dest, inf=media_by_old[vmat['path']]
            vmat['path']=dest.as_posix();vmat['duration']=inf['duration']
            vmat['width']=inf['width'];vmat['height']=inf['height'];vmat['has_audio']=False
            vmat['material_name']=dest.name
    status('Подготовка субтитров...')
    if srt_file:
        subtitles=parse_srt(Path(srt_file).expanduser().resolve())
    elif automatic_captions:
        subtitles=whisper_captions(audio)
    else:
        subtitles=[]
    text_segments=[]
    mat['texts']=[]
    for start,end,txt in subtitles:
        txt = clean_caption(txt)
        # A real newline is stored in the CapCut text material, not a fake space.
        # Transcriptions from the word-aware engine always fit; legacy/manual SRT
        # may be longer, so preserve its words rather than truncate them silently.
        txt = two_line_layout(txt) or txt
        start=max(0,min(start,audinfo['duration']));end=max(start,min(end,audinfo['duration']))
        if end-start<60_000:
            continue
        tmat=copy.deepcopy(text_template);tmat['id']=new_id()
        content=json.loads(tmat['content']);content['text']=txt
        for style in content.get('styles',[]):
            style['range']=[0,len(txt.encode('utf-16-le'))//2]
        tmat['content']=json.dumps(content,ensure_ascii=False,separators=(',',':'))
        mat['texts'].append(tmat)
        tseg=copy.deepcopy(original_txt);tseg['id']=new_id();tseg['material_id']=tmat['id']
        tseg['target_timerange']={'start':start,'duration':end-start}
        newrefs=[]
        for rid in tseg['extra_material_refs']:
            if rid not in refmap:
                newrefs.append(rid);continue
            bucket,obj=refmap[rid]
            obj=copy.deepcopy(obj);obj['id']=new_id();mat[bucket].append(obj)
            # Clamp animation time to caption length.
            for anim in obj.get('animations',[]):
                anim['duration']=min(anim['duration'], (end-start)//3)
            newrefs.append(obj['id'])
        tseg['extra_material_refs']=newrefs
        text_segments.append(tseg)
    data['tracks'][1]['segments']=text_segments
    for aud in mat['audios']:
        aud['path']=referenced_audio.as_posix();aud['name']=referenced_audio.name;aud['duration']=audinfo['duration']
    trackaudio=data['tracks'][2]['segments'][0]
    trackaudio['target_timerange']={'start':0,'duration':audinfo['duration']}
    trackaudio['source_timerange']={'start':0,'duration':audinfo['duration']}
    # Replace old beat markers. Old AI .beat file belongs to the old song.
    if mat['beats']:
        mat['beats'][0]['enable_ai_beats']=False
        for key in ['beats_path','beats_url','melody_path','melody_url']:
            mat['beats'][0].get('ai_beats',{})[key]=''
    for mark in mat['time_marks']:
        mark['mark_items']=[{'id':new_id(),'time_range':{'start':t,'duration':0},
                             'color':'#00c1cd','title':f'Маркер {i+1:02d}'}
                            for i,t in enumerate([16666]+boundaries[:-1])]
    data['duration']=audinfo['duration'];data['id']=new_timeline
    data['name']=project_name;data['update_time']=int(time.time()*MICRO)
    meta['draft_id']=new_draft;meta['draft_name']=project_name
    meta['draft_fold_path']=project_folder.as_posix()
    meta['draft_root_path']=folder.as_posix()
    for k in ('tm_draft_create','tm_draft_modified'):
        meta[k]=int(time.time()*MICRO)
    meta['tm_duration']=audinfo['duration']
    # CapCut browser's media inventory must follow the new source paths.
    for grp in meta.get('draft_materials',[]):
        for item in grp.get('value',[]):
            orig=item.get('file_Path','').replace('\\','/')
            if orig in media_by_old:
                dst,inf=media_by_old[orig]
                item['file_Path']=dst.as_posix();item['extra_info']=dst.name
                item['duration']=inf['duration'];item['width']=inf['width'];item['height']=inf['height']
            elif orig.endswith('.mp3') or orig.endswith('.wav') or orig.endswith('.m4a'):
                item['file_Path']=referenced_audio.as_posix();item['extra_info']=referenced_audio.name
                item['duration']=audinfo['duration']
    timeline_proj['main_timeline_id']=new_timeline
    for timeline in timeline_proj.get('timelines',[]):
        timeline['id']=new_timeline
        timeline['create_time']=int(time.time()*MICRO)
        timeline['update_time']=int(time.time()*MICRO)
    timeline_proj['id']=new_id()
    status('Создание новой папки проекта...')
    workfolder=Path(tempfile.mkdtemp(prefix='.capcut_auto_',dir=folder))
    try:
        if embed_assets:
            media_dir=workfolder/'AutoAssets'
            media_dir.mkdir(parents=True,exist_ok=True)
            shutil.copy2(audio,media_dir/referenced_audio.name)
            for i,src in enumerate(videos):
                shutil.copy2(src,media_dir/referenced_videos[i].name)
        # Read specific files only; avoid zip path traversal.
        with zipfile.ZipFile(template_zip()) as z:
            for member in z.infolist():
                parts=Path(member.filename).parts
                if not parts or parts[0]!=root or member.is_dir():
                    continue
                rel=Path(*parts[1:]);
                if not rel.parts or any(part=='..' for part in rel.parts):
                    continue
                rel=Path(*[new_timeline if part==old_timeline else part for part in rel.parts])
                dest=workfolder/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                suffix=rel.name
                if suffix in {'draft_content.json','draft_content.json.bak','template-2.tmp'}:
                    dest.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
                elif suffix=='draft_meta_info.json':
                    dest.write_text(json.dumps(meta,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
                elif rel.as_posix()=='Timelines/project.json' or rel.as_posix()=='Timelines/project.json.bak':
                    dest.write_text(json.dumps(timeline_proj,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
                elif suffix=='draft_settings':
                    s=z.read(member).decode('utf-8',errors='replace')
                    s=s.replace('timeline_use_auto_beats=true','timeline_use_auto_beats=false')
                    dest.write_text(s,encoding='utf-8')
                elif suffix.endswith('.json'):
                    # Update timeline references in editable metadata/attachment JSON.
                    s=z.read(member).decode('utf-8',errors='replace')
                    s=s.replace(old_timeline,new_timeline).replace(old_draft,new_draft)
                    dest.write_text(s,encoding='utf-8')
                else:
                    dest.write_bytes(z.read(member))
        workfolder.rename(project_folder)
    except Exception:
        shutil.rmtree(workfolder,ignore_errors=True)
        raise
    status('Готово! Открой проект в CapCut.')
    return project_folder,{'duration':audinfo['duration']/MICRO,
                           'clips':len(expanded),'captions':len(text_segments),
                           'markers':len(boundaries),'beats_found':len(beat_points)}
