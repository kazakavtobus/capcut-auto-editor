"""Studio dialogs and neutral light/dark theme; no Pinterest dependencies."""
from pathlib import Path
from datetime import datetime
import json, re
from PySide6.QtCore import Qt, QThread, Signal, QSize, QUrl
from PySide6.QtGui import QIcon,QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QComboBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QFileDialog,QMessageBox,
    QWidget,QFrame,QLineEdit,QScrollArea,QSizePolicy,QGridLayout)
from studio_media import MediaLibrary,CATEGORIES

def theme_style(dark=False):
    p=dict(bg='#1c1c1e' if dark else '#f5f5f7',
           side='#252527' if dark else '#ebedf0',
           card='#2c2c2e' if dark else '#ffffff',
           field='#202022' if dark else '#f7f7f9',
           text='#f5f5f7' if dark else '#1d1d1f',
           mute='#a1a1a6' if dark else '#6e6e73',
           border='#424245' if dark else '#d8d8dd',
           hover='#3a3a3c' if dark else '#e8e8ed',
           accent='#0a84ff' if dark else '#007aff',
           active='#26476a' if dark else '#dceaff')
    return f"""
    * {{ font-family:'Inter Tight','Segoe UI';color:{p['text']};font-size:13px; }}
    QMainWindow,QDialog {{background:{p['bg']};}}
    QWidget#background,QWidget#page {{background:transparent;}}
    QFrame#windowShell {{background:{p['bg']};border:1px solid {p['border']};border-radius:18px;}}
    QFrame#header {{background:{p['card']};border-bottom:1px solid {p['border']};border-top-left-radius:18px;border-top-right-radius:18px;}}
    QFrame#sidebar {{background:{p['side']};border-right:1px solid {p['border']};border-bottom-left-radius:18px;}}
    QFrame#card,QFrame#cardGlow,QFrame#smallCard {{background:{p['card']};border:1px solid {p['border']};border-radius:16px;}}
    QFrame#uploadZone {{background:{p['field']};border:1px dashed {p['border']};border-radius:14px;}}
    QLabel#muted,QLabel#micro {{color:{p['mute']};}} QLabel#micro {{font-size:11px;font-weight:600;}}
    QLabel#heading {{font-size:26px;font-weight:700;}} QLabel#cardHeading {{font-size:17px;font-weight:650;}}
    QLabel#badge,QLabel#successBadge {{background:{p['active']};padding:5px 10px;border-radius:9px;}}
    QPushButton {{background:{p['field']};border:1px solid {p['border']};border-radius:10px;padding:10px 14px;font-weight:600;}}
    QPushButton:hover {{background:{p['hover']};}} QPushButton:disabled {{color:{p['mute']};}}
    QPushButton#primary {{background:{p['accent']};color:white;border:none;border-radius:12px;padding:12px 18px;}}
    QPushButton#primary:disabled {{background:{p['mute']};}}
    QPushButton#nav {{text-align:left;border:none;background:transparent;padding:12px;}}
    QPushButton#nav:hover {{background:{p['hover']};}} QPushButton#nav:checked {{background:{p['active']};}}
    QPushButton#circle,QPushButton#close {{padding:0;min-width:34px;max-width:34px;min-height:34px;max-height:34px;border-radius:17px;}}
    QPushButton#close:hover {{background:#ff453a;color:white;}}
    QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QTextEdit {{background:{p['field']};border:1px solid {p['border']};border-radius:9px;padding:8px;selection-background-color:{p['accent']};}}
    QTableWidget {{background:{p['card']};alternate-background-color:{p['field']};gridline-color:{p['border']};border:1px solid {p['border']};border-radius:10px;selection-background-color:{p['active']};selection-color:{p['text']};}}
    QHeaderView::section {{background:{p['field']};border:none;padding:9px;font-weight:600;}}
    QProgressBar {{background:{p['border']};border:none;border-radius:3px;max-height:6px;}} QProgressBar::chunk {{background:{p['accent']};border-radius:3px;}}
    QScrollArea {{border:none;background:transparent;}}
    QScrollBar:vertical {{background:transparent;width:8px;}} QScrollBar::handle:vertical {{background:{p['border']};border-radius:4px;}}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
    """

def button(text,fn,primary=False):
    b=QPushButton(text);b.setObjectName('primary' if primary else 'secondary');b.clicked.connect(fn);return b

class ImportWorker(QThread):
    status=Signal(str)
    done=Signal(int,object)
    def __init__(self,lib,paths,category):
        super().__init__()
        self.lib=lib;self.paths=paths;self.category=category
    def run(self):
        count=0;errors=[]
        for i,path in enumerate(self.paths):
            try:count+=self.lib.import_video(path,self.category,self.status.emit)
            except Exception as e:errors.append(Path(path).name+': '+str(e))
            self.status.emit(f'Обработано файлов: {i+1}/{len(self.paths)}')
        self.done.emit(count,errors)

class MediaDialog(QDialog):
    def __init__(self,parent,root=None):
        super().__init__(parent)
        self.lib=MediaLibrary(root or None);self.worker=None;self.rows=[]
        self.setWindowTitle('Медиатека');self.resize(990,680)
        l=QVBoxLayout(self);l.setContentsMargins(20,20,20,20);l.setSpacing(12)
        title=QLabel('Медиатека');title.setObjectName('heading');l.addWidget(title)
        self.summary=QLabel();l.addWidget(self.summary)
        hint=QLabel('Город, природа, машины. Только свои материалы. Исходники сохраняются; фрагменты — 5 секунд, ЧБ, 9:16.');hint.setWordWrap(True);hint.setObjectName('muted');l.addWidget(hint)
        h=QHBoxLayout();self.category=QComboBox();self.category.addItems(list(CATEGORIES));h.addWidget(self.category)
        self.add=button('＋ Импорт видео',self.pick,True);self.folder=button('Импорт папки',self.pick_folder)
        h.addWidget(self.add);h.addWidget(self.folder);h.addStretch();l.addLayout(h)
        self.filter=QComboBox();self.filter.addItems(['Все категории',*CATEGORIES]);l.addWidget(self.filter)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['КАДР','ИСХОДНИК','КАТЕГОРИЯ','ФРАГМЕНТ','ИСПОЛЬЗОВАНИЙ','СТАТУС'])
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.table.setIconSize(QSize(49,85));self.table.verticalHeader().setDefaultSectionSize(90)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);l.addWidget(self.table,1)
        h=QHBoxLayout();h.addWidget(button('Просмотреть',self.preview));h.addWidget(button('Включить / исключить',self.toggle))
        h.addWidget(button('Открыть папку',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.lib.root)))));h.addStretch();l.addLayout(h)
        self.status=QLabel('Готово к импорту');self.status.setWordWrap(True);l.addWidget(self.status)
        self.filter.currentTextChanged.connect(self.refresh);self.setAcceptDrops(True);self.refresh()
    def refresh(self,*args):
        rows=self.lib.clips()
        self.summary.setText(f'{len(rows)} фрагментов · {sum(r["enabled"] for r in rows)} активных')
        self.rows=[r for r in rows if self.filter.currentText()=='Все категории' or r['category']==self.filter.currentText()]
        self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            self.table.setItem(i,0,QTableWidgetItem(QIcon(r['preview']), ''))
            for j,t in enumerate((r['name'],r['category'],str(r['idx']+1),str(r['uses']),'Активен' if r['enabled'] else 'Исключён'),1):
                self.table.setItem(i,j,QTableWidgetItem(t))
    def pick(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Выбери исходники','','Видео (*.mp4 *.mov *.mkv *.avi *.webm)')
        self.start(paths)
    def pick_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Выбери папку с видео')
        if folder:self.start([str(p) for p in Path(folder).iterdir() if p.suffix.lower() in ('.mp4','.mov','.mkv','.avi','.webm')])
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):
        self.start([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in ('.mp4','.mov','.mkv','.avi','.webm')])
        event.acceptProposedAction()
    def start(self,paths):
        if not paths or (self.worker and self.worker.isRunning()):return
        self.add.setEnabled(False);self.folder.setEnabled(False)
        self.worker=ImportWorker(self.lib,paths,self.category.currentText())
        self.worker.status.connect(self.status.setText);self.worker.done.connect(self.finished);self.worker.start()
    def finished(self,n,errors):
        self.add.setEnabled(True);self.folder.setEnabled(True)
        self.status.setText(f'Добавлено фрагментов: {n}. Повторные исходники пропущены.');self.refresh()
        if errors:QMessageBox.warning(self,'Часть файлов не импортирована','\n'.join(errors)[:2500])
    def preview(self):
        i=self.table.currentRow()
        if 0<=i<len(self.rows):QDesktopServices.openUrl(QUrl.fromLocalFile(self.rows[i]['path']))
    def toggle(self):
        i=self.table.currentRow()
        if 0<=i<len(self.rows):
            r=self.rows[i];self.lib.enabled(r['id'],not r['enabled']);self.refresh()
    def reject(self):
        if self.worker and self.worker.isRunning():return
        super().reject()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore();return
        super().closeEvent(event)

class ProjectsDialog(QDialog):
    """Responsive project history with per-project actions and real export state."""
    def __init__(self,parent,root=None,settings=None):
        super().__init__(parent);self.setWindowTitle('Проекты');self.resize(940,650)
        from desktop_ui import label,panel,button,icon
        self.host=parent;self.settings=dict(settings or {});self.library=MediaLibrary(root or None)
        self.rows=[];self.cards=[];self.page_size=24;self.page=0
        l=QVBoxLayout(self);l.setContentsMargins(28,24,28,24);l.setSpacing(16)
        header=QHBoxLayout();titles=QVBoxLayout();titles.setSpacing(5)
        titles.addWidget(label('Проекты','heading'))
        subtitle=label('История монтажа, готовые видео и быстрый повторный экспорт.','muted');subtitle.setWordWrap(True)
        titles.addWidget(subtitle);header.addLayout(titles,1)
        header.addWidget(button('Обновить',self.refresh));l.addLayout(header)
        metrics=QHBoxLayout();metrics.setSpacing(10);self.metrics={}
        for key,title in [('all','Всего проектов'),('ready','Видео готово'),('draft','Без экспорта')]:
            box=panel();v=QVBoxLayout(box);v.setContentsMargins(15,12,15,12);v.setSpacing(4)
            v.addWidget(label(title,'muted'));value=label('0','metric');v.addWidget(value);self.metrics[key]=value;metrics.addWidget(box,1)
        l.addLayout(metrics)
        filters=QHBoxLayout();filters.setSpacing(8)
        self.search=QLineEdit();self.search.setPlaceholderText('Найти песню или проект');self.search.addAction(icon('search'),QLineEdit.LeadingPosition);filters.addWidget(self.search,1)
        from account_names import account_name
        self.account_filter=QComboBox();self.account_filter.addItem('Все аккаунты','')
        for key in ('1','2'):self.account_filter.addItem(account_name(self.settings,key),key)
        filters.addWidget(self.account_filter)
        self.state_filter=QComboBox();self.state_filter.addItem('Все статусы','');self.state_filter.addItem('Видео готово','ready');self.state_filter.addItem('Без экспорта','draft');self.state_filter.addItem('Папка недоступна','missing');filters.addWidget(self.state_filter)
        l.addLayout(filters)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setMinimumHeight(220)
        self.body=QWidget();self.body.setObjectName('page');self.grid=QVBoxLayout(self.body);self.grid.setContentsMargins(0,0,8,0);self.grid.setSpacing(10)
        self.scroll.setWidget(self.body);l.addWidget(self.scroll,1)
        footer=QHBoxLayout();self.count_label=label('','muted');footer.addWidget(self.count_label,1)
        self.prev=button('Назад',lambda:self.turn(-1));self.next=button('Далее',lambda:self.turn(1));footer.addWidget(self.prev);footer.addWidget(self.next);l.addLayout(footer)
        self.search.textChanged.connect(self.reset_filter);self.account_filter.currentIndexChanged.connect(self.reset_filter);self.state_filter.currentIndexChanged.connect(self.reset_filter)
        self.refresh()
    def refresh(self,*args):
        from native_export import receipt
        from song_library import SongLibrary
        from account_names import account_name
        names={}
        self.rows=[]
        for raw in self.library.projects():
            row=dict(raw);path=Path(row['path']);key=row.get('song','')
            if key not in names:
                names[key]=''
                if re.fullmatch(r'[a-f0-9]{64}',str(key)):
                    try:
                        data=json.loads((SongLibrary().directory/(key+'.json')).read_text(encoding='utf-8'))
                        names[key]=Path(data.get('filename','')).stem
                    except (OSError,ValueError,TypeError):pass
            row['title']=names[key] or path.name
            row['account_label']=account_name(self.settings,str(row.get('account','1')))
            try:exists=path.is_dir()
            except OSError:exists=False
            saved=receipt(path) if exists else None
            row['receipt']=saved;row['state']='ready' if saved else 'draft' if exists else 'missing'
            self.rows.append(row)
        self.metrics['all'].setText(str(len(self.rows)))
        self.metrics['ready'].setText(str(sum(r['state']=='ready' for r in self.rows)))
        self.metrics['draft'].setText(str(sum(r['state']=='draft' for r in self.rows)))
        self.page=0;self.render_cards()
    def reset_filter(self,*args):
        self.page=0;self.render_cards()
    def turn(self,direction):
        self.page=max(0,self.page+direction);self.render_cards()
        self.scroll.verticalScrollBar().setValue(0)
    def render_cards(self):
        from desktop_ui import label,panel,button,icon
        self.cards=[]
        while self.grid.count():
            item=self.grid.takeAt(0)
            if item.widget():item.widget().deleteLater()
        q=self.search.text().strip().casefold();account=self.account_filter.currentData();state=self.state_filter.currentData()
        rows=[r for r in self.rows if (not account or str(r['account'])==account) and (not state or r['state']==state)
              and q in (r['title']+' '+Path(r['path']).name+' '+r['account_label']).casefold()]
        last=max(0,(len(rows)-1)//self.page_size);self.page=min(self.page,last);offset=self.page*self.page_size
        for row in rows[offset:offset+self.page_size]:
            card=panel();self.cards.append(card);v=QVBoxLayout(card);v.setContentsMargins(16,14,16,14);v.setSpacing(10)
            top=QHBoxLayout();glyph=QLabel();glyph.setPixmap(icon('projects','#3478f6',30).pixmap(30,30));top.addWidget(glyph,0,Qt.AlignTop)
            content=QVBoxLayout();content.setSpacing(5);name=label(row['title'],'cardHeading');name.setWordWrap(True);name.setToolTip(row['path']);content.addWidget(name)
            try:date=datetime.fromtimestamp(float(row['created'])).strftime('%d.%m.%Y · %H:%M')
            except (ValueError,TypeError,OSError,OverflowError):date='Дата неизвестна'
            meta=label(row['account_label']+'  ·  '+date,'muted');meta.setWordWrap(True);content.addWidget(meta);top.addLayout(content,1)
            status=label({'ready':'✓ Видео готово','draft':'Проект собран','missing':'Папка недоступна'}[row['state']],'successBadge' if row['state']=='ready' else 'muted');top.addWidget(status,0,Qt.AlignTop);v.addLayout(top)
            actions=QGridLayout();actions.setHorizontalSpacing(8);actions.setVerticalSpacing(8)
            folder=button('Папка проекта',lambda checked=False,r=row:self.open_project(r));folder.setEnabled(row['state']!='missing')
            export=button('Экспортировать',lambda checked=False,r=row:self.export_project(r),row['state']=='draft');export.setEnabled(row['state']!='missing')
            actions.addWidget(folder,0,0);actions.addWidget(export,0,1)
            if row['state']=='ready':
                video=button('Открыть MP4',lambda checked=False,r=row:self.open_video(r),False,'play')
                deliver=button('К отгрузке',lambda checked=False,r=row:self.deliver_project(r),True,'send')
                actions.addWidget(video,1,0);actions.addWidget(deliver,1,1)
            v.addLayout(actions);self.grid.addWidget(card)
        if not rows:
            empty=label('Нет проектов по выбранным фильтрам.' if self.rows else 'Здесь появятся проекты после первого монтажа.','muted');empty.setAlignment(Qt.AlignCenter);empty.setWordWrap(True);self.grid.addWidget(empty)
        self.grid.addStretch()
        self.count_label.setText(f'{offset+1 if rows else 0}–{min(offset+self.page_size,len(rows))} из {len(rows)}')
        self.prev.setEnabled(self.page>0);self.next.setEnabled(self.page<last)
    def export_project(self,row):
        if hasattr(self.host,'begin_export') and not self.host.busy():self.host.begin_export([row['path']])
    def deliver_project(self,row):
        if hasattr(self.host,'open_delivery'):self.host.open_delivery(row)
    def open_project(self,row):
        QDesktopServices.openUrl(QUrl.fromLocalFile(row['path']))
    def open_video(self,row):
        saved=row.get('receipt')
        if saved:QDesktopServices.openUrl(QUrl.fromLocalFile(saved['path']))


class ProfileWorker(QThread):
    done=Signal(object)
    failed=Signal(str)
    def __init__(self,account,folder):
        super().__init__();self.account=account;self.folder=folder
    def run(self):
        try:
            from studio_profiles import create_reference
            self.done.emit(create_reference(self.account,self.folder))
        except Exception as exc:self.failed.emit(str(exc))

class ProfilesDialog(QDialog):
    task=Signal(str,object)
    def __init__(self,parent,projects_folder,settings=None):
        super().__init__(parent)
        self.folder=Path(projects_folder);self.worker=None
        self.setWindowTitle('Эталоны аккаунтов');self.resize(810,500)
        l=QVBoxLayout(self);l.setContentsMargins(24,24,24,24);l.setSpacing(12)
        title=QLabel('Эталоны аккаунтов');title.setObjectName('heading');l.addWidget(title)
        hint=QLabel('Создай редактируемый эталон, измени его в CapCut, сохрани и закрой редактор. Затем выбери этот проект здесь. Старые эталоны сохраняются в истории.');hint.setWordWrap(True);l.addWidget(hint)
        self.states={};self.controls=[];self.titles={};self.names=dict(settings or {})
        for account in ('1','2'):
            from account_names import account_name
            row=QLabel(account_name(self.names,account));row.setWordWrap(True);row.setObjectName('cardHeading');self.titles[account]=row;l.addWidget(row)
            state=QLabel();state.setWordWrap(True);self.states[account]=state;l.addWidget(state)
            h=QHBoxLayout()
            for title,action,primary in [('Создать проект',self.create,True),('Из проекта CapCut',self.import_folder,False),('Из ZIP',self.import_zip,False),('История / откат',self.restore,False)]:
                w=button(title,lambda checked=False,a=account,fn=action:fn(a),primary);h.addWidget(w);self.controls.append(w)
            l.addLayout(h)
        self.status=QLabel('');self.status.setWordWrap(True);l.addWidget(self.status)
        l.addStretch();self.refresh()
    def set_names(self,settings):
        from account_names import account_name
        self.names=dict(settings)
        for key,w in self.titles.items():w.setText(account_name(self.names,key))

    def refresh(self):
        from studio_profiles import active_template,versions
        for a,w in self.states.items():
            try:p=active_template(a);status='Активный эталон: '+p.name
            except FileNotFoundError:status='Эталон пока не добавлен. Можно создать копию первого.'
            w.setText(status+' · резервных версий: '+str(len(versions(a))))
    def create(self,a):
        host=self.window()
        if (self.worker and self.worker.isRunning()) or (hasattr(host,'busy') and host.busy()):return
        for w in self.controls:w.setEnabled(False)
        self.status.setText('Создаю отдельный эталон CapCut…')
        self.task.emit('Создание эталона · '+self.titles[a].text(),None)
        self.worker=ProfileWorker(a,self.folder)
        self.worker.done.connect(self.created);self.worker.failed.connect(self.failed);self.worker.start()
    def created(self,p):
        for w in self.controls:w.setEnabled(True)
        self.status.setText('Создан: '+p.name)
        self.task.emit('Эталон создан',100)
        QMessageBox.information(self,'Эталон создан','Перезапусти CapCut, открой проект «'+p.name+'», настрой стиль всех субтитров, сохрани и закрой CapCut. Затем нажми «Из проекта CapCut» для нужного аккаунта.')
    def failed(self,msg):
        for w in self.controls:w.setEnabled(True)
        self.status.setText(msg);self.task.emit('Ошибка создания эталона: '+msg,0);QMessageBox.warning(self,'Не удалось создать эталон',msg)
    def install(self,a,p):
        host=self.window()
        if not p or (hasattr(host,'busy') and host.busy()):return
        if QMessageBox.question(self,'Обновить эталон аккаунта '+a+'?','Сохранённый проект станет новым шаблоном. Предыдущий вариант останется в истории. Продолжить?')!=QMessageBox.Yes:return
        try:
            from studio_profiles import install_template
            install_template(a,p)
        except Exception as exc:QMessageBox.warning(self,'Не удалось импортировать',str(exc));return
        self.refresh();self.status.setText(self.titles[a].text()+': эталон сохранён.')
    def import_folder(self,a):
        p=QFileDialog.getExistingDirectory(self,'Выбери папку сохранённого проекта CapCut',str(self.folder))
        self.install(a,p)
    def import_zip(self,a):
        p,_=QFileDialog.getOpenFileName(self,'ZIP-шаблон CapCut','','Архив (*.zip)')
        self.install(a,p)
    def restore(self,a):
        from studio_profiles import versions
        history=versions(a)
        if not history:QMessageBox.information(self,'История','Пока нет предыдущих эталонов.');return
        from PySide6.QtWidgets import QInputDialog
        names=[p.stem for p in history]
        selected,ok=QInputDialog.getItem(self,'Версия эталона','Выбери сохранённую версию:',names,0,False)
        if ok:self.install(a,history[names.index(selected)])
    def reject(self):
        if self.worker and self.worker.isRunning():return
        super().reject()
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore();return
        super().closeEvent(event)
