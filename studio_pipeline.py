"""Offline CapCut generation using the existing native template builder."""
from pathlib import Path
import json
import tempfile
from builder import build,media_info,detect_beats,cut_ends,load_original_zip,template_zip
from caption_engine import obtain_captions
from song_library import APPDATA, SongLibrary, song_hash, sync_previous_capcut_edits
from auto_pipeline import to_srt,unique_project_name
from studio_media import MediaLibrary,ffmpeg
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

def cycle_cuts(reference,total,beats):
    result=bounded_cuts(reference,total,beats)
    if total<180_000:raise ValueError('Слишком короткая песня для трёх фрагментов.')
    while len(result)<3:
        left,right=max(zip([0]+result,result),key=lambda x:x[1]-x[0])
        result.append((left+right)//2);result.sort()
    return result

def prepare_cycle_files(clips,folder,progress=None):
    """Keep stored clips unchanged; extend short clips only for this draft."""
    paths=[]
    for i,row in enumerate(clips):
        p=Path(row['path'])
        if media_info(p,'video')['duration']<4_950_000:
            dest=Path(folder)/f'loop_{i}.mp4'
            if progress:progress('Подготовка короткого футажа: '+p.name)
            ffmpeg(['-stream_loop','-1','-i',p,'-t','5','-map','0:v:0','-an',
                    '-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',dest])
            if media_info(dest,'video')['duration']<4_950_000:raise ValueError('Не удалось зациклить короткий футаж.')
            p=dest
        paths.append(str(p))
    return paths

def render_batch(audio,settings,counts,progress=None,library=None):
    say=progress or (lambda x:None)
    lib=library or MediaLibrary(settings.get('media_root') or None)
    audio=Path(audio).resolve()
    folder=Path(settings['projects_folder']).resolve()
    if not folder.is_dir():raise ValueError('Укажи папку проектов CapCut.')
    total=sum(int(n) for n in counts.values())
    if total<1 or total>40:raise ValueError('Выбери от 1 до 40 проектов.')
    templates={a:profile_template(a) for a,n in counts.items() if n}
    duration=media_info(audio,'audio')['duration']
    if not 0<duration<=180_000_000:raise ValueError('Поддерживаются песни до 3 минут.')
    sync_previous_capcut_edits(audio,folder,progress=say)
    rows=obtain_captions(audio,duration,settings.get('whisper_model','medium'),progress=say,
                         separate_vocals=settings.get('separate_vocals',False))
    if not rows:raise ValueError('Нет субтитров.')
    lib.store_song(audio)
    record=SongLibrary().load(audio)
    title=Path(record.get('filename',audio.name)).stem if record else audio.stem
    beats=detect_beats(audio)
    plans={}
    for account,template in templates.items():
        data=load_original_zip(template)[0]
        reference=[s['target_timerange']['start']+s['target_timerange']['duration'] for s in data['tracks'][0]['segments']]
        plans[account]=cycle_cuts(reference,duration,beats)
    projects=[];last_info={}
    with tempfile.TemporaryDirectory() as tmp:
        srt=Path(tmp)/'lyrics.srt';to_srt(rows,srt)
        for account,n in counts.items():
            for _ in range(n):
                label=account_name(settings,account)
                say(f'Проект {len(projects)+1}/{total} · {label}')
                bounds=plans[account]
                try:clips=lib.choose(3,distinct_sources=True)
                except ValueError as exc:raise ValueError(f'Уже создано {len(projects)} из {total} проектов. '+str(exc)) from exc
                name=unique_project_name(folder,Path(f'{label} — {title}.mp3'.replace('/', ' ').replace('\\',' ')))
                reused=sum(bool(r.get('recent_reuse')) for r in clips)
                say(f'Подбор: {3-reused} свежих, {reused} недавних футажей')
                paths=prepare_cycle_files(clips,tmp,say)
                project,info=build(str(audio),paths,str(folder),name,
                    srt_file=str(srt),beats_override=beats,embed_assets=True,
                    local_boundaries=bounds,template_path=templates[account],progress=say,local_cycle=True)
                assets=project/'AutoAssets'
                to_srt(rows,assets/'lyrics.srt')
                (assets/'sources.json').write_text(json.dumps({'provider':'local','account':account,'account_name':label,'clips':[r['id'] for r in clips],'sequence':[clips[i%3]['id'] for i in range(len(bounds))]},ensure_ascii=False),encoding='utf-8')
                lib.record(account,project,clips,song_hash(audio))
                projects.append(str(project));last_info=info
                say(f'Готово проектов: {len(projects)}/{total}')
    return Path(projects[-1]),dict(last_info,projects=projects,total=len(projects))
