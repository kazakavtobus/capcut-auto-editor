"""Studio dialogs and neutral light/dark theme; no Pinterest dependencies."""
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSize, QUrl
from PySide6.QtGui import QIcon,QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QComboBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QFileDialog,QMessageBox)
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
    def __init__(self,parent,root=None,settings=None):
        super().__init__(parent);self.setWindowTitle('Проекты');self.resize(870,500)
        l=QVBoxLayout(self);l.addWidget(QLabel('История локальных монтажей'))
        from account_names import account_name
        self.rows=MediaLibrary(root or None).projects()
        self.table=QTableWidget(len(self.rows),3);self.table.setHorizontalHeaderLabels(['ПРОЕКТ','АККАУНТ','ПУТЬ'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i,r in enumerate(self.rows):
            for j,t in enumerate((Path(r['path']).name,account_name(settings or {},r['account']),r['path'])):self.table.setItem(i,j,QTableWidgetItem(str(t)))
        l.addWidget(self.table,1);l.addWidget(button('Открыть папку проекта',self.open_project,True))
    def open_project(self):
        i=self.table.currentRow()
        if 0<=i<len(self.rows):QDesktopServices.openUrl(QUrl.fromLocalFile(self.rows[i]['path']))


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
