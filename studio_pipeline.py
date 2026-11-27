"""Offline CapCut generation using the existing native template builder."""
from pathlib import Path
import json
import tempfile, shutil, uuid, os
from semantic_captions import clean_caption, two_line_layout
from builder import build,media_info,detect_beats,cut_ends,load_original_zip,template_zip
from caption_engine import obtain_captions
from song_library import APPDATA, SongLibrary, song_hash, sync_previous_capcut_edits
from auto_pipeline import to_srt,unique_project_name
from studio_media import MediaLibrary,ffmpeg,MIN_FOOTAGE_US
from account_names import account_name

from studio_profiles import active_template as profile_template

def bounded_cuts(reference,total,beats):
    # Each prepared file is 5 seconds. Keep the original montage rhythm.
    original=cut_ends(reference,total,beats)
    result=[];prev=0
    for end in original:
        while end-prev>4_950_000:
            prev+=4_950_000;result.append(prev)
        if end>prev:result.append(end);prev=end
    return result

def cycle_cuts(reference,total,beats,minimum=3):
    result=bounded_cuts(reference,total,beats)
    if minimum<3 or total<minimum*60_000:raise ValueError('Слишком короткая песня для выбранного числа фрагментов.')
    while len(result)<minimum:
        left,right=max(zip([0]+result,result),key=lambda x:x[1]-x[0])
        result.append((left+right)//2);result.sort()
    return result

def prepare_cycle_files(clips,folder,progress=None):
    """Keep stored clips unchanged; extend short clips only for this draft."""
    paths=[]
    for i,row in enumerate(clips):
        p=Path(row['path'])
        duration=media_info(p,'video')['duration']
        if duration<MIN_FOOTAGE_US:raise ValueError('Футаж короче 3 секунд: '+p.name)
        if duration<4_950_000:
            dest=Path(folder)/f'loop_{i}.mp4'
            if progress:progress('Подготовка короткого футажа: '+p.name)
            ffmpeg(['-stream_loop','-1','-i',p,'-t','5','-map','0:v:0','-an',
                    '-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',dest])
            if media_info(dest,'video')['duration']<4_950_000:raise ValueError('Не удалось зациклить короткий футаж.')
            p=dest
        paths.append(str(p))
    return paths

def factory_project_root(settings):
    return Path(settings.get('factory_projects_folder') or APPDATA/'factory_projects').expanduser()

def reference_style(account):
    """Read the saved legacy style only as local data; no editor installation required."""
    account=str(account)
    base={'reference':[4266666,8016666,11316666,14600000,17216666,19383333,21500000,22550000] if account=='1' else [4266666,8016666,10000000],
          'font':'InterTight-SemiBoldItalic.ttf' if account=='1' else 'Onest-SemiBold.ttf',
          'font_size':15,'color':'#ffffff','transform':{'x':0,'y':0},
          'effects':[{'type':'brightness','value':-0.11564625850340138},{'type':'contrast','value':0.12244897959183665},{'type':'lut','value':1}],
          'transition':233333,'animations':[{'type':'in','duration':183333},{'type':'out','duration':216666}]}
    try:doc=load_original_zip(profile_template(account))[0]
    except FileNotFoundError:return base
    tracks=doc['tracks'];mats=doc['materials']
    ref={m['id']:m for arr in mats.values() if isinstance(arr,list) for m in arr if isinstance(m,dict) and 'id' in m}
    base['reference']=[s['target_timerange']['start']+s['target_timerange']['duration'] for s in tracks[0]['segments']]
    v=tracks[0]['segments'][0];t=tracks[1]['segments'][0];tm=ref[t['material_id']]
    base['font_size']=tm.get('font_size',15);base['color']=tm.get('text_color','#ffffff')
    base['transform']=(t.get('clip') or {}).get('transform') or {'x':0,'y':0}
    base['effects']=[{'type':m['type'],'value':m.get('value')} for rid in v.get('extra_material_refs',[]) if (m:=ref.get(rid,{})).get('type') in ('brightness','contrast','lut')]
    base['transition']=next((m.get('duration',233333) for m in mats.get('transitions',[]) if m.get('duration')),233333)
    base['animations']=[{'type':a['type'],'duration':a['duration']} for rid in t.get('extra_material_refs',[]) for a in ref.get(rid,{}).get('animations',[]) if a.get('type') in ('in','out')]
    return base

def build_factory(audio,videos,folder,name,bounds,rows,account,style):
    """Build a self-contained timeline, compatible with existing local subtitle tools."""
    duration=media_info(audio,'audio')['duration'];folder=Path(folder);project=folder/name
    def uid():return uuid.uuid4().hex
    mats={'videos':[],'texts':[],'audios':[],'effects':[],'transitions':[],'material_animations':[]}
    tracks=[{'type':k,'segments':[]} for k in ('video','text','audio')]
    def add(bucket,obj):
        obj=dict(obj,id=uid());mats[bucket].append(obj);return obj['id']
    def seg(mid,a,b,refs=(),**kw):
        return dict(id=uid(),material_id=mid,target_timerange={'start':a,'duration':b-a},source_timerange={'start':0,'duration':b-a},extra_material_refs=list(refs),**kw)
    with tempfile.TemporaryDirectory(prefix='.factory-',dir=folder) as tmp:
        work=Path(tmp);assets=work/'AutoAssets';assets.mkdir()
        video_ids=[]
        for i,v in enumerate(videos):
            dest=assets/f'video_{i+1:02d}.mp4';shutil.copy2(v,dest)
            video_ids.append(add('videos',{'path':dest.name}))
        audio_file=assets/('song'+Path(audio).suffix.lower());shutil.copy2(audio,audio_file)
        prev=0
        for i,end in enumerate(bounds):
            refs=[add('effects',e) for e in style['effects']]
            if i<len(bounds)-1:refs.append(add('transitions',{'type':'transition','duration':style['transition']}))
            tracks[0]['segments'].append(seg(video_ids[i%len(video_ids)],prev,end,refs,clip={'flip':{'horizontal':False,'vertical':False}},volume=0))
            prev=end
        for a,b,txt in rows:
            a=max(0,min(a,duration));b=max(a,min(b,duration));txt=clean_caption(txt)
            if b-a<60000 or not txt:continue
            txt=two_line_layout(txt) or txt
            mid=add('texts',{'content':json.dumps({'text':txt,'styles':[{'range':[0,len(txt.encode('utf-16-le'))//2],'font':{'path':style['font']}}]},ensure_ascii=False),
                             'font_size':style['font_size'],'text_color':style['color']})
            refs=[add('material_animations',{'animations':[dict(x,duration=min(x['duration'],(b-a)//3)) for x in style['animations']]})]
            tracks[1]['segments'].append(seg(mid,a,b,refs,clip={'transform':style['transform']}))
        if not tracks[1]['segments']:raise ValueError('Нет пригодных субтитров.')
        aid=add('audios',{'path':audio_file.name});tracks[2]['segments'].append(seg(aid,0,duration,volume=1))
        doc={'id':uid(),'name':name,'duration':duration,'format':'tiktok-factory-1','tracks':tracks,'materials':mats}
        (work/'draft_content.json').write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
        if project.exists():raise FileExistsError(project)
        # Move the complete local timeline atomically; no external editor paths.
        work.rename(project)
    return project,{'clips':len(bounds),'captions':len(tracks[1]['segments'])}

def render_batch(audio,settings,counts,progress=None,library=None):
    say=progress or (lambda x:None)
    lib=library or MediaLibrary(settings.get('media_root') or None)
    audio=Path(audio).resolve()
    folder=factory_project_root(settings).resolve();folder.mkdir(parents=True,exist_ok=True)
    total=sum(int(n) for n in counts.values())
    if total<1 or total>40:raise ValueError('Выбери от 1 до 40 проектов.')
    styles={a:reference_style(a) for a,n in counts.items() if n}
    duration=media_info(audio,'audio')['duration']
    if not 0<duration<=180_000_000:raise ValueError('Поддерживаются песни до 3 минут.')
    lib.refresh_durations(say)
    rows=obtain_captions(audio,duration,settings.get('whisper_model','medium'),progress=say,
                         separate_vocals=settings.get('separate_vocals',False))
    if not rows:raise ValueError('Нет субтитров.')
    lib.store_song(audio)
    record=SongLibrary().load(audio)
    title=Path(record.get('filename',audio.name)).stem if record else audio.stem
    beats=detect_beats(audio)
    footage_count=5
    track_hash=song_hash(audio)
    plans={}
    for account,style in styles.items():
        plans[account]=cycle_cuts(style['reference'],duration,beats,footage_count)
    projects=[];last_info={}
    with tempfile.TemporaryDirectory() as tmp:
        srt=Path(tmp)/'lyrics.srt';to_srt(rows,srt)
        for account,n in counts.items():
            for _ in range(n):
                label=account_name(settings,account)
                say(f'Проект {len(projects)+1}/{total} · {label}')
                bounds=plans[account]
                try:clips=lib.choose(footage_count,distinct_sources=True,song=track_hash)
                except ValueError as exc:raise ValueError(f'Уже создано {len(projects)} из {total} проектов. '+str(exc)) from exc
                name=unique_project_name(folder,Path(f'{label} — {title}.mp3'.replace('/', ' ').replace('\\',' ')))
                reused=sum(bool(r.get('recent_reuse')) for r in clips)
                say(f'Подбор: {footage_count-reused} свежих, {reused} недавних футажей')
                paths=prepare_cycle_files(clips,tmp,say)
                project,info=build_factory(audio,paths,folder,name,bounds,rows,account,styles[account])
                assets=project/'AutoAssets'
                to_srt(rows,assets/'lyrics.srt')
                (assets/'sources.json').write_text(json.dumps({'provider':'local','account':account,'account_name':label,'clips':[r['id'] for r in clips],'sequence':[clips[i%len(clips)]['id'] for i in range(len(bounds))]},ensure_ascii=False),encoding='utf-8')
                lib.record(account,project,clips,track_hash)
                projects.append(str(project));last_info=info
                say(f'Готово проектов: {len(projects)}/{total}')
    return Path(projects[-1]),dict(last_info,projects=projects,total=len(projects))
