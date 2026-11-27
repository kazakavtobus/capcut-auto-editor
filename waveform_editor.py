"""Interactive audio waveform / subtitle-timing ruler for the Qt editor."""
from __future__ import annotations

import array
import math
import subprocess
import io, tempfile, sys, shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap
from PySide6.QtWidgets import QWidget,QApplication,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollBar,QSlider


def waveform_peaks(audio: Path, bins: int = 1200) -> list[float]:
    """Decode once with ffmpeg; use amplitude envelope, not a fake waveform."""
    bundled=Path(sys.executable).resolve().parent/'ffmpeg.exe'
    exe=str(bundled) if getattr(sys,'frozen',False) and bundled.is_file() else (shutil.which('ffmpeg') or 'ffmpeg')
    result = subprocess.run([
        exe, '-v', 'error', '-nostdin', '-i', str(audio), '-vn', '-ac', '1',
        '-ar', '4000', '-f', 's16le', '-t', '180', '-'
    ], check=True, capture_output=True, timeout=60)
    pcm = array.array('h')
    pcm.frombytes(result.stdout[:len(result.stdout)//2*2])
    if not pcm:
        return [0.02]*bins
    step = max(1, math.ceil(len(pcm)/bins))
    peaks = []
    for start in range(0, len(pcm), step):
        segment = pcm[start:start+step]
        peaks.append(max(abs(v) for v in segment)/32768.0)
    return peaks


def retime(start,end,mode,delta,lower,upper,snap=(),tolerance=0):
    """Keep length when moving; keep the other edge fixed when trimming."""
    if mode=='move':
        length=end-start;candidate=max(lower,min(start+delta,upper-length))
        for target in sorted(snap,key=lambda x:min(abs(x-candidate),abs(x-candidate-length))):
            edges=[target,target-length]
            valid=[x for x in edges if lower<=x<=upper-length and abs(x-candidate)<=tolerance]
            if valid:candidate=min(valid,key=lambda x:abs(x-candidate));break
        return round(candidate,3),round(candidate+length,3)
    value=(start if mode=='start' else end)+delta
    lo,hi=(lower,end-.1) if mode=='start' else (start+.1,upper)
    value=max(lo,min(value,hi))
    for target in sorted(snap,key=lambda x:abs(x-value)):
        if lo<=target<=hi and abs(target-value)<=tolerance:value=target;break
    return (round(value,3),end) if mode=='start' else (start,round(value,3))

class WaveformTimeline(QWidget):
    seekRequested=Signal(float)
    subtitleSelected=Signal(int)
    subtitleEdited=Signal(int,float,float)
    viewChanged=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumHeight(192);self.setMouseTracking(True)
        self.peaks=[];self.rows=[];self.duration=1.;self.position=0.;self.selected=-1
        self._drag=None;self.zoom=1.;self.view_start=0.
    @property
    def span(self):return self.duration/self.zoom
    def set_audio(self,peaks,duration):
        self.peaks=peaks;self.duration=max(.1,float(duration));self.view_start=0.;self.viewChanged.emit();self.update()
    def set_captions(self,rows):
        self.rows=[dict(r) for r in rows];self.update()
    def set_position(self,seconds):
        self.position=max(0.,min(float(seconds),self.duration));self.update()
    def set_selected(self,index):self.selected=index;self.update()
    def set_zoom(self,zoom):
        center=self.view_start+self.span/2;self.zoom=max(1.,min(12.,float(zoom)))
        self.set_view(center-self.span/2)
    def set_view(self,start):
        self.view_start=max(0.,min(float(start),max(0.,self.duration-self.span)));self.viewChanged.emit();self.update()
    def _x(self,seconds):return 14+(self.width()-28)*(seconds-self.view_start)/self.span
    def _sec(self,x):return max(0.,min(self.duration,self.view_start+(x-14)/max(1,self.width()-28)*self.span))
    def _row_index(self,i):return self.rows[i].get('table_index',i)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        dark=bool(QApplication.instance().property('studioDark'))
        p.fillRect(self.rect(),QColor('#20232b' if dark else '#f0f3f8'))
        w=max(1,self.width()-28)
        p.setPen(QColor('#9ca8bb' if dark else '#657185'))
        raw=self.span/max(2,w//85);step=next((s for s in (.1,.2,.5,1,2,5,10,15,30,60,120) if s>=raw),120)
        tick=math.ceil(self.view_start/step)*step
        while tick<=self.view_start+self.span+.00001:
            x=round(self._x(tick));p.drawText(x+3,17,f'{int(tick//60):02d}:{tick%60:04.1f}')
            p.setPen(QPen(QColor('#343b48' if dark else '#d6dde7'),1));p.drawLine(x,23,x,186);p.setPen(QColor('#9ca8bb' if dark else '#657185'));tick+=step
        p.fillRect(14,29,w,82,QColor('#2b3445' if dark else '#dde7f5'))
        if self.peaks:
            for n in range(w):
                t=self._sec(n+14);i=min(len(self.peaks)-1,int(t/self.duration*len(self.peaks)))
                h=min(74,3+self.peaks[i]*96)
                p.setPen(QPen(QColor('#3478f6' if t<self.position else '#8da5c7'),1))
                p.drawLine(n+14,int(70-h/2),n+14,int(70+h/2))
        p.fillRect(14,119,w,61,QColor('#191d25' if dark else '#e3e8f1'))
        for i,row in enumerate(self.rows):
            left=max(14,round(self._x(float(row['start']))));right=min(self.width()-14,round(self._x(float(row['end']))))
            if right<=left:continue
            selected=self._row_index(i)==self.selected
            active=float(row['start'])<=self.position<float(row['end'])
            p.setPen(QPen(QColor('#a8c8ff' if selected else '#7084a2'),1));p.setBrush(QColor('#2369df' if selected else '#405575' if dark else '#b8cfee'))
            p.drawRoundedRect(QRectF(left,123,right-left,51),5,5)
            if selected and right-left>=15:
                p.fillRect(left+2,132,4,32,QColor('#ffffff'));p.fillRect(right-6,132,4,32,QColor('#ffffff'))
            p.setPen(QColor('#ffffff' if dark or selected else '#20242c'))
            text=str(row.get('text','')).replace('\n',' ')
            p.drawText(left+9,145,p.fontMetrics().elidedText(text,Qt.ElideRight,max(0,right-left-18)))
            if right-left>75:p.drawText(left+9,163,f"{float(row['end'])-float(row['start']):.2f} с")
            if active:p.fillRect(left+3,170,max(0,right-left-6),2,QColor('#a8d2ff'))
        if self.view_start<=self.position<=self.view_start+self.span:
            px=round(self._x(self.position));p.setPen(QPen(QColor('#ffffff' if dark else '#2369df'),2));p.drawLine(px,21,px,186);p.fillRect(px-4,20,9,7,QColor('#3478f6'))
        p.end()
    def _find_caption(self,x):
        for i,r in enumerate(self.rows):
            if self._x(float(r['start']))<=x<=self._x(float(r['end'])):return i
        return -1
    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton:return
        x=event.position().x();y=event.position().y()
        if y>=119:
            i=self._find_caption(x)
            if i>=0:
                r=self.rows[i];a,b=float(r['start']),float(r['end']);idx=self._row_index(i)
                left,right=self._x(a),self._x(b);handle=min(11,max(3,(right-left)/4))
                mode='start' if x-left<=handle else 'end' if right-x<=handle else 'move'
                lower=float(self.rows[i-1]['end']) if i>0 else 0.
                upper=float(self.rows[i+1]['start']) if i+1<len(self.rows) else self.duration
                self._drag=(idx,mode,self._sec(x),a,b,lower,upper)
                self.selected=idx;self.subtitleSelected.emit(idx);self.update();return
        self.seekRequested.emit(self._sec(x))
    def mouseMoveEvent(self,event):
        x=event.position().x()
        if self._drag is None:
            i=self._find_caption(x) if event.position().y()>=119 else -1
            if i>=0:
                r=self.rows[i];d=min(abs(x-self._x(float(r['start']))),abs(x-self._x(float(r['end']))))
                self.setCursor(Qt.SizeHorCursor if d<=10 else Qt.OpenHandCursor)
            else:self.setCursor(Qt.PointingHandCursor)
            return
        idx,mode,origin,a,b,lower,upper=self._drag
        if upper-lower<b-a and mode=='move':return
        start,end=retime(a,b,mode,self._sec(x)-origin,lower,upper,(lower,upper,self.position),self.span*7/max(1,self.width()-28))
        if end<=start:return
        for i,row in enumerate(self.rows):
            if row.get('table_index',i)==idx:row.update(start=start,end=end);break
        self.subtitleEdited.emit(idx,start,end);self.update()
    def mouseReleaseEvent(self,event):
        self._drag=None;self.setCursor(Qt.PointingHandCursor)
    def wheelEvent(self,event):
        if event.modifiers()&Qt.ControlModifier:
            self.set_zoom(self.zoom*(1.25 if event.angleDelta().y()>0 else .8));event.accept()
        else:super().wheelEvent(event)

def timeline_panel(wave):
    box=QWidget();l=QVBoxLayout(box);l.setContentsMargins(0,0,0,0);l.setSpacing(6)
    h=QHBoxLayout();h.addWidget(QLabel('ТАЙМЛАЙН'));h.addStretch()
    minus=QPushButton('−');plus=QPushButton('+');zoom=QSlider(Qt.Horizontal);zoom.setRange(10,120);zoom.setValue(10);zoom.setFixedWidth(120)
    minus.clicked.connect(lambda:zoom.setValue(max(10,zoom.value()-10)));plus.clicked.connect(lambda:zoom.setValue(min(120,zoom.value()+10)))
    h.addWidget(minus);h.addWidget(zoom);h.addWidget(plus);l.addLayout(h);l.addWidget(wave)
    scroll=QScrollBar(Qt.Horizontal);l.addWidget(scroll)
    def sync():
        scroll.blockSignals(True);zoom.blockSignals(True)
        scroll.setRange(0,round(max(0,wave.duration-wave.span)*1000));scroll.setPageStep(round(wave.span*1000));scroll.setValue(round(wave.view_start*1000));zoom.setValue(round(wave.zoom*10))
        scroll.blockSignals(False);zoom.blockSignals(False)
    wave.viewChanged.connect(sync);zoom.valueChanged.connect(lambda v:wave.set_zoom(v/10));scroll.valueChanged.connect(lambda v:wave.set_view(v/1000));sync()
    hint=QLabel('За середину — переместить · за края — изменить длительность · Ctrl + колесо — масштаб');hint.setWordWrap(True);hint.setObjectName('muted');l.addWidget(hint);return box

class PhrasePreview(QLabel):
    """Neutral portrait canvas; uses the exact same rasterizer as export."""
    def __init__(self):
        super().__init__();self.setFixedSize(190,338);self.setAlignment(Qt.AlignCenter);self.setWordWrap(True)
        self.setStyleSheet('QLabel {background:#111319;color:white;border-radius:12px;}')
        self._tmp=tempfile.TemporaryDirectory();self._fonts={};self._last=None
    def set_phrase(self,text,account='1'):
        key=(text,account)
        if key==self._last:return
        self._last=key
        try:
            from remotion_export import CAPTION_FONTS,find_font,stage_caption_font,raster_caption
            from studio_pipeline import reference_style
            from PIL import Image
            if account not in self._fonts:
                name,_=CAPTION_FONTS[account];font=find_font(name,'АБВабвЁёABCabc012')
                root=Path(self._tmp.name);self._fonts[account]=(stage_caption_font(font,name,root)[0],reference_style(account))
            font,style=self._fonts[account]
            canvas=Image.new('RGBA',(1080,1920),'#17191e')
            if text.strip():
                image=raster_caption({'fontSize':float(style['font_size'])*4.6,'text':text,'color':style['color']},font,None)
                transform=style['transform'];x=round((1080-image.width)/2+float(transform.get('x',0))*540);y=round((1920-image.height)/2-float(transform.get('y',0))*960)
                canvas.alpha_composite(image,(x,y))
            canvas=canvas.resize((190,338),Image.Resampling.LANCZOS);buf=io.BytesIO();canvas.save(buf,format='PNG');pix=QPixmap();pix.loadFromData(buf.getvalue());self.setPixmap(pix)
        except Exception:
            self.clear();self.setText('Импортируй точный шрифт аккаунта в настройках.')
