"""Studio 8.1 desktop components. All workspaces live in one window."""
from pathlib import Path
import re, json
from PySide6.QtCore import Qt,QSize,QRect,QRectF,QByteArray,Signal,QThread
from PySide6.QtGui import QColor,QPainter,QPainterPath,QPen,QPixmap,QIcon,QPalette,QFont,QDesktopServices
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication,QWidget,QFrame,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,
    QListWidget,QListWidgetItem,QListView,QStyledItemDelegate,QStyle,QLineEdit,QComboBox,QFileDialog,
    QMessageBox,QInputDialog,QProgressBar,QMenu,QSizePolicy)
from PySide6.QtCore import QUrl
from studio_media import MediaLibrary,CATEGORIES
from studio_ui import theme_style,ImportWorker
from song_library import SongLibrary,song_hash

ICONS={
 'montage':'<rect x="3" y="5" width="18" height="15" rx="3"/><path d="m3 10 18 0M8 5l3 5m4-5 3 5"/>',
 'media':'<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 6"/>',
 'songs':'<path d="M9 18V5l12-2v13M9 18a3 3 0 1 1-3-3h3m12 1a3 3 0 1 1-3-3h3"/>',
 'captions':'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 10h10M7 14h7"/>',
 'profiles':'<rect x="4" y="3" width="16" height="18" rx="3"/><circle cx="12" cy="9" r="3"/><path d="M7 17c0-4 10-4 10 0"/>',
 'projects':'<rect x="4" y="7" width="16" height="14" rx="2"/><path d="M8 7V3h8v4M8 12h8m-8 4h5"/>',
 'tasks':'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 'settings':'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
 'about':'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
 'plus':'<path d="M12 5v14M5 12h14"/>',
 'search':'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
 'play':'<path d="m9 5 11 7-11 7z"/>',
 'sun':'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M19 5l-2 2M7 17l-2 2"/>',
 'logo':'<path d="M5 16V8l5-4 9 5v7l-5 4z" fill="none"/><path d="m5 8 9 5 5-4m-5 4v7"/>'
}
def icon(name,color='#657185',size=20):
    markup=ICONS.get(name,ICONS['about'])
    raw=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">{markup}</svg>'
    pix=QPixmap(size*2,size*2);pix.fill(Qt.transparent)
    painter=QPainter(pix);QSvgRenderer(QByteArray(raw.encode())).render(painter);painter.end()
    pix.setDevicePixelRatio(2);return QIcon(pix)

def apply_appearance(dark=False):
    app=QApplication.instance()
    p=QPalette()
    bg='#17191e' if dark else '#f5f6f8'
    surface='#22252c' if dark else '#ffffff'
    text='#eef0f4' if dark else '#20242c'
    muted='#a5aab5' if dark else '#68717d'
    for role,value in ((QPalette.Window,bg),(QPalette.WindowText,text),(QPalette.Base,surface),
       (QPalette.AlternateBase,bg),(QPalette.Text,text),(QPalette.Button,surface),(QPalette.ButtonText,text),
       (QPalette.ToolTipBase,surface),(QPalette.ToolTipText,text),(QPalette.Highlight,'#3478f6'),
       (QPalette.HighlightedText,'#ffffff'),(QPalette.PlaceholderText,muted)):
        p.setColor(role,QColor(value))
    p.setColor(QPalette.Disabled,QPalette.Text,QColor(muted));p.setColor(QPalette.Disabled,QPalette.ButtonText,QColor(muted))
    app.setPalette(p)
    assets=(Path(__file__).resolve().parent/'assets').as_posix()
    # Explicit popup and input colors fix Fusion/native black-on-black controls.
    app.setStyleSheet(theme_style(dark)+f"""
      QMainWindow,QWidget#desktop {{background:{bg};}}
      QFrame#sidebar {{background:{surface};border:none;border-right:1px solid {'#343841' if dark else '#e4e7ed'};border-radius:0;}}
      QFrame#topbar {{background:{surface};border-bottom:1px solid {'#343841' if dark else '#e4e7ed'};}}
      QLabel#heading {{font-size:30px;font-weight:700;}}
      QLabel#eyebrow {{font-size:12px;color:{muted};font-weight:600;}}
      QLabel#metric {{font-size:29px;font-weight:700;}}
      QPushButton#nav {{text-align:left;padding:12px 14px;min-height:20px;border-radius:10px;}}
      QPushButton#primary {{min-height:23px;}}
      QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit {{color:{text};background:{surface};min-height:23px;}}
      QComboBox::drop-down {{subcontrol-origin:padding;subcontrol-position:top right;width:26px;border:none;}}
      QComboBox::down-arrow {{image:url("{assets}/chevron-down.svg");width:14px;height:14px;}}
      QDoubleSpinBox::up-arrow {{image:url("{assets}/chevron-up.svg");width:11px;height:11px;}}
      QDoubleSpinBox::down-arrow {{image:url("{assets}/chevron-down.svg");width:11px;height:11px;}}
      QComboBox QAbstractItemView,QMenu,QListView {{color:{text};background:{surface};selection-background-color:#3478f6;selection-color:white;}}
      QComboBox QAbstractItemView::item {{min-height:28px;padding:6px;}}
      QSpinBox::up-button,QSpinBox::down-button,QDoubleSpinBox::up-button,QDoubleSpinBox::down-button {{background:{surface};width:20px;}}
      QCheckBox {{spacing:9px;color:{text};}}
      QCheckBox::indicator {{width:17px;height:17px;border:1px solid #8b96a6;border-radius:5px;background:{surface};}}
      QCheckBox::indicator:checked {{background:#3478f6;border-color:#3478f6;image:url("{assets}/check.svg");}}
      QToolTip {{background:{surface};color:{text};border:1px solid {muted};}}
      QListWidget#assets {{background:transparent;border:none;outline:none;padding:2px;}}
      QListWidget#assets::item {{border:none;}}
      QProgressBar {{min-height:7px;max-height:7px;text-align:center;}}
      QFrame#panel {{background:{surface};border:1px solid {'#343841' if dark else '#e4e7ed'};border-radius:15px;}}
      QFrame#panel[selected="true"] {{border:2px solid #3478f6;}}
      QScrollArea {{background:transparent;border:none;}}
    """)

def label(text='',kind=None):
    x=QLabel(text)
    if kind:x.setObjectName(kind)
    return x
def button(text,fn,primary=False,glyph=None):
    b=QPushButton(text);b.setObjectName('primary' if primary else 'secondary')
    if glyph:b.setIcon(icon(glyph))
    b.setCursor(Qt.PointingHandCursor);b.clicked.connect(fn);return b
def panel():
    w=QFrame();w.setObjectName('panel');return w

class Ring(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.value=None;self.setFixedSize(44,44)
    def set_value(self,value):
        self.value=value;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        r=QRectF(4,4,self.width()-8,self.height()-8)
        p.setPen(QPen(QColor('#a0a9b7'),3));p.drawEllipse(r)
        if self.value is not None:
            pen=QPen(QColor('#3478f6'),3);pen.setCapStyle(Qt.RoundCap);p.setPen(pen)
            p.drawArc(r,90*16,-round(360*16*self.value/100))
        p.setPen(self.palette().color(QPalette.WindowText));f=p.font();f.setPixelSize(10);p.setFont(f)
        p.drawText(self.rect(),Qt.AlignCenter,'…' if self.value is None else str(self.value)+'%')

class AssetDelegate(QStyledItemDelegate):
    def __init__(self,parent=None):
        super().__init__(parent);self.cache={}
    def sizeHint(self,option,index):return QSize(180,224)
    def paint(self,p,option,index):
        r=option.rect.adjusted(5,5,-5,-5);data=index.data(Qt.UserRole) or {}
        p.save();p.setRenderHint(QPainter.Antialiasing)
        dark=option.palette.color(QPalette.Window).lightness()<100
        selected=bool(option.state&QStyle.State_Selected)
        path=QPainterPath();path.addRoundedRect(QRectF(r),13,13)
        p.fillPath(path,QColor('#263c5c' if dark and selected else '#e9f2ff' if selected else '#22252c' if dark else '#ffffff'))
        p.setPen(QPen(QColor('#3478f6' if selected else '#39404b' if dark else '#e2e6ec'),1.5));p.drawPath(path)
        img=QRect(r.x()+8,r.y()+8,r.width()-16,143)
        pp=QPainterPath();pp.addRoundedRect(QRectF(img),8,8)
        p.save();p.setClipPath(pp);p.fillRect(img,QColor('#20252d'))
        key=data.get('preview','')
        if key not in self.cache:
            self.cache[key]=QPixmap(key)
            if len(self.cache)>250:self.cache.pop(next(iter(self.cache)))
        px=self.cache[key]
        if not px.isNull():
            scaled=px.scaled(img.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation)
            p.drawPixmap(img.x()+(img.width()-scaled.width())//2,img.y()+(img.height()-scaled.height())//2,scaled)
        p.restore()
        p.setPen(option.palette.color(QPalette.Text))
        font=QFont(option.font);font.setBold(True);font.setPixelSize(13);p.setFont(font)
        title=f"{Path(data.get('name','')).stem} · {int(data.get('idx',0))+1:02d}"
        p.drawText(QRect(r.x()+10,r.y()+156,r.width()-20,22),Qt.AlignVCenter,p.fontMetrics().elidedText(title,Qt.ElideRight,r.width()-20))
        font.setBold(False);font.setPixelSize(11);p.setFont(font)
        p.setPen(QColor('#a6afbe' if dark else '#657185'))
        p.drawText(QRect(r.x()+10,r.y()+179,r.width()-20,18),Qt.AlignVCenter,f"{data.get('category','')}  ·  5 сек")
        p.drawText(QRect(r.x()+10,r.y()+196,r.width()-20,17),Qt.AlignVCenter,('Активен' if data.get('enabled') else 'Исключён')+f"  ·  {data.get('uses',0)} исп.")
        p.restore()

class MediaPage(QWidget):
    task=Signal(str,object)
    def __init__(self,root=None,parent=None):
        super().__init__(parent);self.lib=MediaLibrary(root or None);self.worker=None;self.rows=[]
        l=QVBoxLayout(self);l.setContentsMargins(30,26,30,26);l.setSpacing(14)
        h=QHBoxLayout();title=label('Медиатека','heading');h.addWidget(title);h.addStretch()
        self.add=button('Импорт видео',self.pick,True,'plus');h.addWidget(self.add)
        self.folder=button('Папка',self.pick_folder);h.addWidget(self.folder);l.addLayout(h)
        self.summary=label('','muted');l.addWidget(self.summary)
        controls=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Поиск по названию');self.search.addAction(icon('search'),QLineEdit.LeadingPosition);controls.addWidget(self.search,2)
        self.filter=QComboBox();self.filter.addItems(['Все категории',*CATEGORIES]);controls.addWidget(self.filter,1)
        self.category=QComboBox();self.category.addItems(list(CATEGORIES));self.category.setToolTip('Категория новых импортируемых материалов')
        controls.addWidget(label('Импорт как:','muted'));controls.addWidget(self.category,1);l.addLayout(controls)
        self.grid=QListWidget();self.grid.setObjectName('assets');self.grid.setViewMode(QListView.IconMode);self.grid.setResizeMode(QListView.Adjust);self.grid.setMovement(QListView.Static)
        self.grid.setWrapping(True);self.grid.setUniformItemSizes(True);self.grid.setGridSize(QSize(180,224));self.grid.setItemDelegate(AssetDelegate(self.grid))
        self.grid.setSelectionMode(QListWidget.SingleSelection);self.grid.itemDoubleClicked.connect(lambda _:self.preview());l.addWidget(self.grid,1)
        self.empty=label('Медиатека пуста. Добавь свои исходники, чтобы создать пятисекундные ЧБ-фрагменты.','muted');self.empty.setWordWrap(True);l.addWidget(self.empty)
        actions=QHBoxLayout()
        for title,fn in [('Просмотр',self.preview),('Переименовать исходник',self.rename),('Вкл. / исключить',self.toggle),('Удалить…',self.delete)]:
            actions.addWidget(button(title,fn))
        actions.addStretch();l.addLayout(actions)
        self.status=label('Готово к импорту','muted');self.status.setWordWrap(True);l.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.hide();l.addWidget(self.progress)
        self.search.textChanged.connect(self.refresh);self.filter.currentTextChanged.connect(self.refresh);self.setAcceptDrops(True);self.refresh()
    def refresh(self,*args):
        allrows=self.lib.clips();q=self.search.text().casefold().strip();category=self.filter.currentText()
        self.rows=[r for r in allrows if (category=='Все категории' or r['category']==category) and q in r['name'].casefold()]
        self.summary.setText(f'{len(allrows)} фрагментов · {sum(r["enabled"] for r in allrows)} активных · {len(set(r["source"] for r in allrows))} исходников')
        self.grid.clear()
        for r in self.rows:
            item=QListWidgetItem();item.setData(Qt.UserRole,r);item.setToolTip(r['name']);self.grid.addItem(item)
        self.empty.setVisible(not self.rows)
        self.empty.setText('Нет подходящих материалов.' if allrows else 'Медиатека пуста. Добавь свои исходники или перетащи их сюда.')
    def selected(self):
        item=self.grid.currentItem();return item.data(Qt.UserRole) if item else None
    def pick(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Добавить видео','','Видео (*.mp4 *.mov *.mkv *.avi *.webm)');self.start(paths)
    def pick_folder(self):
        p=QFileDialog.getExistingDirectory(self,'Папка видео')
        if p:self.start([str(f) for f in Path(p).iterdir() if f.suffix.lower() in ('.mp4','.mov','.mkv','.avi','.webm')])
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):
        self.start([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in ('.mp4','.mov','.mkv','.avi','.webm')]);event.acceptProposedAction()
    def start(self,paths):
        if not paths or (self.worker and self.worker.isRunning()):return
        host=self.window()
        if hasattr(host,'busy') and host.busy():
            self.status.setText('Сначала заверши монтаж.');return
        self.add.setEnabled(False);self.folder.setEnabled(False);self.progress.show();self.progress.setRange(0,0)
        self.worker=ImportWorker(self.lib,paths,self.category.currentText())
        self.worker.status.connect(self.on_status);self.worker.done.connect(self.done);self.worker.start()
        self.task.emit('Импорт медиатеки',None)
    def on_status(self,msg):
        self.status.setText(msg)
        m=re.match(r'Обработано файлов: (\d+)/(\d+)',msg)
        percent=round(int(m[1])*100/int(m[2])) if m else None
        if percent is not None:self.progress.setRange(0,100);self.progress.setValue(percent)
        self.task.emit(msg,percent)
    def done(self,n,errors):
        self.progress.setRange(0,100);self.progress.setValue(100 if not errors else 0)
        self.status.setText(f'Добавлено: {n} фрагментов'+(' · есть ошибки' if errors else ''))
        self.task.emit(self.status.text(),100 if not errors else 0)
        self.add.setEnabled(True);self.folder.setEnabled(True);self.refresh()
        if errors:QMessageBox.warning(self,'Импорт','\n'.join(errors)[:2000])
    def preview(self):
        r=self.selected()
        if r:QDesktopServices.openUrl(QUrl.fromLocalFile(r['path']))
    def busy(self):
        host=self.window()
        return bool(self.worker and self.worker.isRunning()) or bool(hasattr(host,'busy') and host.busy())
    def rename(self):
        r=self.selected()
        if not r or self.busy():return
        name,ok=QInputDialog.getText(self,'Название исходника','Название:',text=Path(r['name']).stem)
        if ok:
            try:self.lib.rename_source(r['source'],name);self.refresh()
            except Exception as exc:QMessageBox.warning(self,'Название',str(exc))
    def toggle(self):
        r=self.selected()
        if r and not self.busy():self.lib.enabled(r['id'],not r['enabled']);self.refresh()
    def delete(self):
        r=self.selected()
        if not r or self.busy():return
        m=QMessageBox(self);m.setWindowTitle('Удалить материал?');m.setText('Материал будет исключён из базы и перемещён в папку trash. Существующие проекты не изменятся.')
        one=m.addButton('Только фрагмент',QMessageBox.DestructiveRole);whole=m.addButton('Весь исходник',QMessageBox.DestructiveRole);m.addButton('Отмена',QMessageBox.RejectRole);m.exec()
        if m.clickedButton() not in (one,whole):return
        try:self.lib.remove_media(r['id'],m.clickedButton()==whole);self.refresh()
        except Exception as exc:QMessageBox.warning(self,'Удаление',str(exc))

class SongsPage(QWidget):
    def __init__(self,host,root=None):
        super().__init__();self.host=host;self.lib=MediaLibrary(root or None);self.library=SongLibrary();self.entries=[]
        l=QVBoxLayout(self);l.setContentsMargins(30,26,30,26);l.setSpacing(14)
        h=QHBoxLayout();h.addWidget(label('Песни','heading'));h.addStretch();h.addWidget(button('Добавить песню',lambda:host.open_manual(),True,'plus'));l.addLayout(h)
        self.summary=label('','muted');l.addWidget(self.summary)
        self.search=QLineEdit();self.search.setPlaceholderText('Поиск песни');self.search.addAction(icon('search'),QLineEdit.LeadingPosition);l.addWidget(self.search)
        self.list=QListWidget();self.list.setSpacing(5);l.addWidget(self.list,1)
        self.empty=label('Добавь песню или создай первый проект — текст появится здесь.','muted');self.empty.setWordWrap(True);l.addWidget(self.empty)
        h=QHBoxLayout()
        for title,fn,primary in [('Выбрать для монтажа',self.use,True),('Редактировать текст',self.edit,False),('Переименовать',self.rename,False),('Удалить запись',self.remove,False)]:
            h.addWidget(button(title,fn,primary))
        l.addLayout(h);self.search.textChanged.connect(self.refresh);self.list.itemDoubleClicked.connect(lambda _:self.edit());self.list.itemSelectionChanged.connect(self.highlight);self.refresh()
    def refresh(self,*args):
        docs=[]
        for p in self.library.directory.glob('*.json'):
            try:docs.append((p,json.loads(p.read_text(encoding='utf-8'))))
            except (OSError,ValueError):continue
        counts={}
        for r in self.lib.projects():counts[r['song']]=counts.get(r['song'],0)+1
        docs.sort(key=lambda t:t[1].get('edited_utc',''),reverse=True)
        q=self.search.text().strip().casefold();self.entries=[(p,d) for p,d in docs if q in d.get('filename','').casefold()]
        self.summary.setText(f'{len(docs)} песен · {sum(bool(d.get("verified")) for _,d in docs)} проверено')
        self.list.clear()
        for i,(p,d) in enumerate(self.entries):
            item=QListWidgetItem();item.setSizeHint(QSize(100,78));item.setData(Qt.UserRole,i)
            row=panel();h=QHBoxLayout(row);h.setContentsMargins(14,9,14,9);h.setSpacing(14)
            glyph=QLabel();glyph.setPixmap(icon('songs','#3478f6',32).pixmap(32,32));h.addWidget(glyph)
            box=QVBoxLayout();box.setSpacing(5);name=label(Path(d.get('filename','Песня')).stem,'cardHeading');box.addWidget(name)
            box.addWidget(label(f'{len(d.get("captions",[]))} фраз · {counts.get(d.get("sha256"),0)} проектов','muted'));h.addLayout(box,1)
            status=label('Проверено' if d.get('verified') else 'Черновик','muted');h.addWidget(status)
            row.setAttribute(Qt.WA_TransparentForMouseEvents,True)
            self.list.addItem(item);self.list.setItemWidget(item,row)
        self.empty.setVisible(not self.entries)
    def highlight(self):
        for i in range(self.list.count()):
            item=self.list.item(i);w=self.list.itemWidget(item)
            if w:
                w.setProperty('selected',item.isSelected())
                w.style().unpolish(w);w.style().polish(w);w.update()
    def selected(self):
        i=self.list.currentRow();return self.entries[i] if 0<=i<len(self.entries) else None
    def audio(self,doc):
        key=doc.get('sha256','')
        if not re.fullmatch(r'[a-f0-9]{64}',key):return None
        saved=list((self.lib.root/'songs').glob(key+'.*'))
        if saved:return saved[0]
        path,_=QFileDialog.getOpenFileName(self,'Выбери исходное аудио','','Аудио (*.mp3 *.wav *.m4a *.flac *.ogg)')
        if not path:return None
        if song_hash(Path(path))!=key:QMessageBox.warning(self,'Песня','Это другой аудиофайл.');return None
        return self.lib.store_song(Path(path))
    def use(self):
        row=self.selected()
        if not row:return
        path=self.audio(row[1])
        if path:self.host.set_audio(str(path));self.host.drop.title.setText(row[1].get('filename',path.name));self.host.change_page(0)
    def edit(self):
        row=self.selected()
        if row:
            path=self.audio(row[1])
            if path:self.host.open_manual(path)
    def rename(self):
        row=self.selected()
        if not row or self.host.busy():return
        p,d=row;name,ok=QInputDialog.getText(self,'Название песни','Название:',text=d.get('filename',''))
        if ok and name.strip():
            d['filename']=name.strip();tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p);self.refresh()
    def remove(self):
        row=self.selected()
        if row and not self.host.busy() and QMessageBox.question(self,'Удалить запись?','Удалить сохранённый текст и таймкоды? Аудио и проекты останутся.')==QMessageBox.Yes:
            row[0].unlink();self.refresh()
