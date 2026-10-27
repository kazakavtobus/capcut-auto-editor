"""Interactive audio waveform / subtitle-timing ruler for the Qt editor."""
from __future__ import annotations

import array
import math
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget


def waveform_peaks(audio: Path, bins: int = 1200) -> list[float]:
    """Decode once with ffmpeg; use amplitude envelope, not a fake waveform."""
    result = subprocess.run([
        'ffmpeg', '-v', 'error', '-nostdin', '-i', str(audio), '-vn', '-ac', '1',
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


class WaveformTimeline(QWidget):
    """Click seek, click a caption to select, drag its LEFT/RIGHT edge to retime."""
    seekRequested = Signal(float)
    subtitleSelected = Signal(int)
    subtitleEdited = Signal(int, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(145)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.peaks=[]
        self.rows=[]
        self.duration=1.0
        self.position=0.0
        self.selected=-1
        self._drag=None

    def set_audio(self, peaks: list[float], duration: float):
        self.peaks = peaks
        self.duration = max(0.1, float(duration))
        self.update()

    def set_captions(self, rows):
        self.rows=list(rows)
        self.update()

    def set_position(self, seconds: float):
        self.position=max(0.,min(float(seconds),self.duration))
        self.update()

    def set_selected(self, index: int):
        self.selected=index
        self.update()

    def _x(self, seconds: float) -> float:
        return 15+(self.width()-30)*(seconds/self.duration)

    def _sec(self, x: float) -> float:
        return max(0.,min(self.duration,(x-15)/max(1,self.width()-30)*self.duration))

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(),QColor('#11182A'))
        mid=67
        w=max(1,self.width()-30)
        if self.peaks:
            for n in range(w):
                i=min(len(self.peaks)-1,int(n/w*len(self.peaks)))
                h=min(48,3+self.peaks[i]*65)
                p.setPen(QPen(QColor('#947DFF') if self._sec(n+15)<self.position else QColor('#495B83'),1))
                p.drawLine(n+15,int(mid-h/2),n+15,int(mid+h/2))
        p.fillRect(0,110,self.width(),35,QColor('#0D1425'))
        for i,row in enumerate(self.rows):
            start,end = float(row['start']),float(row['end'])
            left=max(15,round(self._x(start)))
            right=min(self.width()-15,round(self._x(end)))
            if right<=left:continue
            p.fillRect(left,112,right-left,27,QColor('#7857E9' if i==self.selected else '#343F67'))
            if i==self.selected:
                p.fillRect(left,112,3,27,QColor('#46D8FF'))
                p.fillRect(right-3,112,3,27,QColor('#46D8FF'))
            p.setPen(QColor('#F4F2FF'))
            text=str(row.get('text','')).replace('\n',' ')
            p.drawText(left+5,131,p.fontMetrics().elidedText(text,Qt.ElideRight,max(0,right-left-10)))
        p.setPen(QPen(QColor('#D7D4FF'),2))
        px=round(self._x(self.position))
        p.drawLine(px,10,px,144)
        p.end()

    def _find_caption(self,x):
        for i,r in enumerate(self.rows):
            if self._x(float(r['start']))-5<=x<=self._x(float(r['end']))+5:
                return i
        return -1

    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton:return
        x=event.position().x()
        if event.position().y()>104:
            i=self._find_caption(x)
            if i>=0:
                self.selected=i
                self.subtitleSelected.emit(i)
                r=self.rows[i]
                left,right=self._x(float(r['start'])),self._x(float(r['end']))
                if abs(x-left)<=11:self._drag=(i,'start')
                elif abs(x-right)<=11:self._drag=(i,'end')
                else:self._drag=None
                self.update()
                return
        self.seekRequested.emit(self._sec(x))

    def mouseMoveEvent(self,event):
        if self._drag is None:return
        i,side=self._drag
        row=self.rows[i]
        value=round(self._sec(event.position().x()),3)
        start,end=float(row['start']),float(row['end'])
        if side=='start':start=min(value,end-0.1)
        else:end=max(value,start+0.1)
        start=max(0.,start)
        end=min(self.duration,end)
        # Don't allow overlapping neighboring captions by dragging.
        if i>0:start=max(start,float(self.rows[i-1]['end']))
        if i+1<len(self.rows):end=min(end,float(self.rows[i+1]['start']))
        if end<=start:return
        row.update({'start':start,'end':end})
        self.subtitleEdited.emit(i,start,end)
        self.update()

    def mouseReleaseEvent(self,event):
        self._drag=None
