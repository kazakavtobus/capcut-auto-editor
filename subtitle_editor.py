"""Non-destructive subtitle editor for generated CapCut drafts.
Keeps video/audio tracks intact and patches both timeline copies of draft JSON.
Close CapCut before editing so its in-memory draft won't overwrite changes.
"""
from __future__ import annotations
import copy
import uuid
import logging
import hashlib
import json
import os
import shutil
from pathlib import Path
from semantic_captions import clean_caption
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

MICRO=1_000_000


def _clock(value: float) -> str:
    m=int(value)//60
    s=value-60*m
    return f'{m:02d}:{s:06.3f}'


def _srt_time(seconds: float) -> str:
    total=round(seconds*1000)
    return f'{total//3600000:02d}:{total//60000%60:02d}:{total//1000%60:02d},{total%1000:03d}'


def _project_data(path:Path):
    f=path/'draft_content.json'
    if not f.is_file():raise ValueError('В папке не найден draft_content.json')
    d=json.loads(f.read_text(encoding='utf-8-sig'))
    track=next((t for t in d['tracks'] if t['type']=='text'),None)
    if track is None:raise ValueError('В проекте нет текстовой дорожки.')
    mat={m['id']:m for m in d['materials']['texts']}
    rows=[]
    for seg in track['segments']:
        obj=mat.get(seg['material_id'])
        if obj is None:raise ValueError('Текстовый материал не найден.')
        st=seg['target_timerange']['start']/MICRO
        en=st+seg['target_timerange']['duration']/MICRO
        content=json.loads(obj['content'])
        rows.append({'id':seg['id'],'start':st,'end':en,'text':content['text']})
    rows.sort(key=lambda r:r['start'])
    return rows,d


def apply_changes(path: Path, rows: list[dict]):
    """Update, insert and delete editable subtitle segments across CapCut timeline copies.

    New blocks clone the project's own text style and native animation references;
    operations are validated and staged before the original JSON files are touched.
    """
    rows = [{**row, 'text': clean_caption(str(row['text']))} for row in rows]
    rows.sort(key=lambda r: float(r['start']))
    seen = set()
    prev = -1.0
    for row in rows:
        if not row['text'].strip():
            raise ValueError('Есть пустые субтитры.')
        a, b = float(row['start']), float(row['end'])
        if a < 0 or b <= a:
            raise ValueError('Встречается отрицательное время или конец раньше начала.')
        if a < prev - 0.001:
            raise ValueError('Субтитры пересекаются. Исправь начало и конец строк.')
        prev = b
        if not row.get('id'):
            row['id'] = str(uuid.uuid4()).upper()
        if row['id'] in seen:
            raise ValueError('Повторяется ID субтитра.')
        seen.add(row['id'])

    datafiles = [path/'draft_content.json',path/'draft_content.json.bak',path/'template-2.tmp']
    datafiles += list((path/'Timelines').glob('*/draft_content.json'))
    datafiles += list((path/'Timelines').glob('*/draft_content.json.bak'))
    datafiles += list((path/'Timelines').glob('*/template-2.tmp'))
    datafiles = list(dict.fromkeys(f for f in datafiles if f.is_file()))
    if not datafiles:
        raise ValueError('Не найдены JSON-файлы проекта.')

    # Read the application's original subtitle template only if a project has no
    # text blocks left. The archive ships with the app, not with an online API.
    from builder import load_original_zip
    original_template = None
    prepared = []
    for file in datafiles:
        d = json.loads(file.read_text(encoding='utf-8-sig'))
        mats = d['materials']
        tr = next((x for x in d['tracks'] if x['type']=='text'), None)
        if tr is None:
            raise ValueError('Отсутствует текстовая дорожка: '+str(file))
        original_segments = {s['id']:s for s in tr['segments']}
        text_materials = {m['id']:m for m in mats['texts']}
        objects = {m['id']:(kind,m) for kind,arr in mats.items()
                   if isinstance(arr,list) for m in arr if isinstance(m,dict) and m.get('id')}
        if original_segments:
            template_segment = next(iter(original_segments.values()))
            template_text = text_materials[template_segment['material_id']]
            template_objects = objects
        else:
            if original_template is None:
                original_template = load_original_zip()[0]
            sample = original_template
            template_segment = next(s for t in sample['tracks'] if t['type']=='text'
                                    for s in t['segments'])
            template_text = next(m for m in sample['materials']['texts']
                                 if m['id']==template_segment['material_id'])
            template_objects = {m['id']:(kind,m) for kind,arr in sample['materials'].items()
                                if isinstance(arr,list) for m in arr
                                if isinstance(m,dict) and m.get('id')}

        replacement_segments=[]
        replacement_texts=[]
        for row in rows:
            rid=row['id']
            exists=rid in original_segments
            seg=copy.deepcopy(original_segments[rid] if exists else template_segment)
            mat=copy.deepcopy(text_materials[seg['material_id']] if exists else template_text)
            if not exists:
                seg['id']=rid
                mat['id']=str(uuid.uuid5(uuid.NAMESPACE_URL,rid+':material')).upper()
                seg['material_id']=mat['id']
                refs=[]
                for ref in seg.get('extra_material_refs',[]):
                    found=template_objects.get(ref)
                    if not found:
                        refs.append(ref)
                        continue
                    bucket,obj=found
                    extra=copy.deepcopy(obj)
                    new_ref=str(uuid.uuid5(uuid.NAMESPACE_URL,rid+':'+ref)).upper()
                    extra['id']=new_ref
                    # Native text animation durations must fit inside the segment.
                    for anim in extra.get('animations',[]):
                        if 'duration' in anim:
                            anim['duration']=min(anim['duration'],int((row['end']-row['start'])*MICRO)//3)
                    if not any(x.get('id')==new_ref for x in mats[bucket]):
                        mats[bucket].append(extra)
                    refs.append(new_ref)
                seg['extra_material_refs']=refs
            seg['target_timerange']={'start':round(row['start']*MICRO),
                                     'duration':round((row['end']-row['start'])*MICRO)}
            content=json.loads(mat['content'])
            content['text']=row['text']
            for style in content.get('styles',[]):
                style['range']=[0,len(row['text'].encode('utf-16-le'))//2]
            mat['content']=json.dumps(content,ensure_ascii=False,separators=(',',':'))
            replacement_segments.append(seg)
            replacement_texts.append(mat)

        tr['segments']=replacement_segments
        # Only remove subtitle text materials; never touch video/audio/effect tracks.
        retained_ids=set(s['material_id'] for s in original_segments.values())
        mats['texts']=[m for m in mats['texts'] if m['id'] not in retained_ids]+replacement_texts
        prepared.append((file,json.dumps(d,ensure_ascii=False,separators=(',',':'))))

    backup=path/'AutoAssets'/'draft_content_before_subtitle_edits.json'
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():
        shutil.copy2(path/'draft_content.json',backup)
    staged=[]
    try:
        for file,text in prepared:
            target=file.with_name(file.name+'.subtitle.new')
            target.write_text(text,encoding='utf-8')
            staged.append((file,target))
        for file,target in staged:
            target.replace(file)
    finally:
        for _,target in staged:
            target.unlink(missing_ok=True)

    srt='\n'.join(f"{i}\n{_srt_time(r['start'])} --> {_srt_time(r['end'])}\n{r['text']}\n"
                  for i,r in enumerate(rows,1))
    (path/'AutoAssets'/'lyrics.srt').write_text(srt,encoding='utf-8')
    song=next(iter((path/'AutoAssets').glob('song.*')),None)
    if song:
        from song_library import SongLibrary
        SongLibrary().save(song, rows, verified=True, source='editor', display_name=path.name)
        local=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CapCutAutoEditor'/'corrected_captions'
        local.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256(song.read_bytes()).hexdigest()
        (local/(digest+'.srt')).write_text(srt,encoding='utf-8')
    return len(datafiles)

def open_subtitle_editor(parent:tk.Misc, project_folder:str=''):
    if not project_folder or not Path(project_folder).is_dir():
        project_folder=filedialog.askdirectory(title='Выбери папку проекта CapCut',parent=parent)
    if not project_folder:return
    folder=Path(project_folder)
    try:rows,_=_project_data(folder)
    except Exception as exc:
        messagebox.showerror('Не удалось открыть проект',str(exc),parent=parent);return
    window=tk.Toplevel(parent)
    window.title('Корректор субтитров — '+folder.name)
    window.geometry('980x680');window.minsize(740,580)
    frame=ttk.Frame(window,padding=12);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Выбери строку, исправь текст или точные секунды и нажми «Применить».',
              font=('Segoe UI',11,'bold')).pack(anchor='w',pady=4)
    ttk.Label(frame,text='Перед сохранением закрой CapCut. Изменяется только текстовая дорожка; футажи и музыка не трогаются.',
              foreground='#765420').pack(anchor='w',pady=(0,8))
    cols=('n','start','end','text')
    tree=ttk.Treeview(frame,columns=cols,show='headings',height=15)
    for c,label,w in [('n','№',38),('start','Начало',105),('end','Конец',105),('text','Текст',600)]:
        tree.heading(c,text=label);tree.column(c,width=w,stretch=c=='text',anchor='w')
    tree.pack(fill='both',expand=True)
    def refresh(select=0):
        tree.delete(*tree.get_children())
        for i,r in enumerate(rows):
            tree.insert('', 'end', iid=str(i),values=(i+1,_clock(r['start']),_clock(r['end']),r['text']))
        if rows:
            k=str(max(0,min(select,len(rows)-1)))
            tree.selection_set(k);tree.see(k)
    editing=ttk.LabelFrame(frame,text='Редактирование выбранного блока',padding=9);editing.pack(fill='x',pady=10)
    sel=tk.IntVar(value=0)
    st=tk.StringVar();en=tk.StringVar();words=tk.StringVar()
    ttk.Label(editing,text='Начало (сек.)').grid(row=0,column=0,sticky='w')
    ttk.Entry(editing,textvariable=st,width=13).grid(row=1,column=0,sticky='w',padx=(0,12))
    ttk.Label(editing,text='Конец (сек.)').grid(row=0,column=1,sticky='w')
    ttk.Entry(editing,textvariable=en,width=13).grid(row=1,column=1,sticky='w',padx=(0,12))
    ttk.Label(editing,text='Текст').grid(row=0,column=2,sticky='w')
    ttk.Entry(editing,textvariable=words,width=72).grid(row=1,column=2,sticky='ew',padx=(0,10))
    editing.columnconfigure(2,weight=1)
    def chosen(_event=None):
        if not tree.selection():return
        n=int(tree.selection()[0]);sel.set(n);r=rows[n]
        st.set(f"{r['start']:.3f}");en.set(f"{r['end']:.3f}");words.set(r['text'])
    def update_row():
        n=sel.get()
        try:
            a=float(st.get().replace(',','.'));b=float(en.get().replace(',','.'))
            if b<=a or a<0:raise ValueError()
        except ValueError:
            messagebox.showerror('Неверное время','Введи секунды: например, 2.450 и 4.100',parent=window);return
        rows[n].update(start=a,end=b,text=words.get().strip())
        if not rows[n]['text']:
            messagebox.showerror('Пустой текст','Введи текст субтитра',parent=window);return
        refresh(n)
    tree.bind('<<TreeviewSelect>>',chosen)
    ttk.Button(editing,text='Применить строку',command=update_row).grid(row=1,column=3)
    shift_row=ttk.Frame(frame);shift_row.pack(fill='x')
    seconds=tk.StringVar(value='0.20')
    ttk.Label(shift_row,text='Общий сдвиг (сек):').pack(side='left')
    ttk.Entry(shift_row,textvariable=seconds,width=9).pack(side='left',padx=7)
    def shift(sign):
        try:value=float(seconds.get().replace(',','.'))*sign
        except ValueError:
            messagebox.showerror('Ошибка','Введи число в секундах.',parent=window);return
        if any(r['start']+value<0 for r in rows):
            messagebox.showwarning('Ошибка','Нельзя сдвинуть начало раньше нуля.',parent=window);return
        for row in rows:row['start']+=value;row['end']+=value
        refresh(sel.get())
    ttk.Button(shift_row,text='Раньше',command=lambda:shift(-1)).pack(side='left',padx=4)
    ttk.Button(shift_row,text='Позже',command=lambda:shift(1)).pack(side='left',padx=4)
    def save():
        if not messagebox.askyesno('Сохранить субтитры?',
             'CapCut сейчас закрыт? Программа обновит текстовые дорожки проекта.',parent=window):return
        try:count=apply_changes(folder,rows)
        except Exception as exc:
            messagebox.showerror('Ошибка сохранения',str(exc),parent=window);return
        messagebox.showinfo('Сохранено',f'Обновлено {count} файлов проекта.\nИзменённый SRT сохранён для повторного монтажа этой песни.\nОткрой CapCut заново.',parent=window)
    ttk.Button(shift_row,text='Сохранить изменения в проект',command=save).pack(side='right')
    refresh()
    chosen()
