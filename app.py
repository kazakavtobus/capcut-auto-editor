"""CapCut Auto Editor V7 — dark neon Qt desktop shell.

Only the UI changes here. The existing Python pipeline remains reusable and
performs its heavy work in a worker thread. No Chrome window is shown for search;
login, if required, is user-initiated from Settings.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
import logging
import traceback
import zipfile
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QPoint, QTimer, QUrl
from PySide6.QtGui import QFont, QColor, QIcon, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QComboBox,
    QCheckBox, QFileDialog, QMessageBox, QStackedWidget, QScrollArea,
    QTextEdit, QProgressBar, QGraphicsDropShadowEffect, QSizePolicy,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDoubleSpinBox,
    QAbstractItemView, QSizeGrip
)
from auto_pipeline import load_settings, save_settings, run_auto
from subtitle_editor import _project_data, apply_changes
from diagnostics import install_crash_logger, report_exception, LOG_FILE
from version import VERSION
from builder import template_zip, USER_TEMPLATE_ZIP
from updater import check_release,download_installer,launch_installer
from semantic_captions import clean_caption
from song_library import SongLibrary, project_song, import_project_corrections
from waveform_editor import WaveformTimeline, waveform_peaks
from alignment import align_existing, AlignmentUnavailable
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
except ImportError:
    QMediaPlayer = QAudioOutput = None

SETTINGS = load_settings()
SETTINGS['provider'] = 'pinterest'
SETTINGS['api_key'] = ''

C = {
    'bg': '#080C17', 'shell': '#0C1120', 'sidebar': '#0D1324',
    'card': '#121A2D', 'card2': '#172137', 'line': '#29354C',
    'text': '#F3F5FF', 'muted': '#8996B2', 'primary': '#8868FF',
    'blue': '#38C9FF', 'success': '#49E3BE', 'error': '#FF6D94'
}

STYLES = """
* {font-family: 'Inter Tight', 'Segoe UI'; color: #F3F5FF; font-size: 13px;}
QWidget#background {background: transparent;}
QFrame#windowShell {background: #0C1120; border: 1px solid #29354C; border-radius: 23px;}
QFrame#header {background: #0D1424; border-top-left-radius: 22px; border-top-right-radius: 22px; border-bottom: 1px solid #26324B;}
QFrame#sidebar {background: #0D1324; border-bottom-left-radius: 22px; border-right: 1px solid #26324B;}
QWidget#page {background: transparent;}
QFrame#card {background: #121A2D; border: 1px solid #29354C; border-radius: 21px;}
QFrame#cardGlow {background: #161D37; border: 1px solid #5549AC; border-radius: 22px;}
QFrame#smallCard {background: #172137; border: 1px solid #273652; border-radius: 15px;}
QFrame#uploadZone {background: #141D35; border: 1px dashed #6559B3; border-radius: 19px;}
QLabel#muted {color: #8996B2;}
QLabel#micro {font-size: 11px; color: #8493B5; letter-spacing: 1px; font-weight: 700;}
QLabel#heading {font-size: 27px; font-weight: 800;}
QLabel#cardHeading {font-size: 17px; font-weight: 700;}
QLabel#badge {color: #A9DCFF; background: #1C3251; border-radius: 11px; padding: 5px 10px; font-size: 11px; font-weight: 700;}
QLabel#successBadge {color: #49E3BE; background: #153D3D; border-radius: 11px; padding: 5px 10px; font-weight: 700;}
QPushButton {border: none; border-radius: 14px; background: #212C45; padding: 11px 16px; font-weight: 650;}
QPushButton:hover {background: #344360;}
QPushButton:disabled {color: #6E788F; background: #1A2233;}
QPushButton#primary {border-radius: 17px; padding: 15px 25px; background: #8361FA; font-size: 15px; font-weight: 800;}
QPushButton#primary:hover {background: #9F80FF;}
QPushButton#primary:disabled {background: #6F36EA; color: #FFFFFF; border: 2px solid #39DDFF; font-weight: 850;}
QPushButton#primary[working="true"] {background: #7038ED; color: #FFFFFF; border: 2px solid #3CE1FF;}
QPushButton#secondary {border: 1px solid #3F5070; background: #192238; border-radius: 15px;}
QPushButton#secondary:hover {border-color: #9C89FF; background: #293354;}
QPushButton#circle {border-radius: 19px; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; background: #202A42; padding: 0; font-size: 18px;}
QPushButton#circle:hover {background: #373A6E;}
QPushButton#close {border-radius: 19px; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; background: #202A42; padding: 0; font-size: 18px;}
QPushButton#close:hover {background: #B83260;}
QPushButton#nav {background: transparent; color: #A3B0CF; text-align: left; border-radius: 13px; padding: 13px 16px;}
QPushButton#nav:hover {background: #1E2840; color: white;}
QPushButton#nav:checked {background: #27254B; color: #E4DFFF; border-left: 3px solid #9274FF;}
QLineEdit, QComboBox, QDoubleSpinBox {background: #0E172B; color: #F2F5FF; border: 1px solid #34415C; border-radius: 12px; padding: 10px 12px; selection-background-color: #8063EF;}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {border: 1px solid #9479FF;}
QComboBox QAbstractItemView {background: #18243A; selection-background-color: #6044BA;}
QCheckBox {spacing: 10px; color: #C4CEE5;}
QCheckBox::indicator {width: 18px; height: 18px; border: 1px solid #536587; border-radius: 6px; background: #101A30;}
QCheckBox::indicator:checked {background: #8868FF; border-color: #8868FF;}
QTextEdit {background: #0B1222; border: 1px solid #2B3954; border-radius: 15px; color: #B9C9E3; padding: 12px; font-family: Consolas; font-size: 12px;}
QProgressBar {border: none; background: #222B43; border-radius: 4px; max-height: 7px; min-height: 7px; text-align: center;}
QProgressBar::chunk {border-radius: 4px; background: #9272FF;}
QScrollArea {border: none; background: transparent;}
QScrollBar:vertical {width: 8px; background: transparent;}
QScrollBar::handle:vertical {background: #394667; border-radius: 4px;}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height: 0;}
QTableWidget {background: #10182B; border: 1px solid #30415D; border-radius: 12px; alternate-background-color: #152035; gridline-color: #2C3B55; selection-background-color: #56469F;}
QHeaderView::section {background: #1C2842; border: none; padding: 10px; font-weight: 700;}
QDialog {background: #0C1120;}
"""


def label(text, kind=None, wrap=False):
    x = QLabel(text)
    if kind: x.setObjectName(kind)
    x.setWordWrap(wrap)
    return x


def vertical(parent=None, space=12, margins=(0, 0, 0, 0)):
    l = QVBoxLayout(parent)
    l.setContentsMargins(*margins)
    l.setSpacing(space)
    return l


def horizontal(parent=None, space=12, margins=(0, 0, 0, 0)):
    l = QHBoxLayout(parent)
    l.setContentsMargins(*margins)
    l.setSpacing(space)
    return l


def card(glow=False):
    x=QFrame()
    x.setObjectName('cardGlow' if glow else 'card')
    return x


def btn(text, style='secondary', handler=None):
    b=QPushButton(text)
    b.setObjectName(style)
    b.setCursor(Qt.PointingHandCursor)
    if handler: b.clicked.connect(handler)
    return b


class TitleBar(QFrame):
    def __init__(self, host, caption='CapCut Auto Editor'):
        super().__init__()
        self.host = host
        self._start = None
        self.setObjectName('header')
        self.setFixedHeight(75)
        l=horizontal(self, 12, (22, 0, 21, 0))
        logo=QLabel()
        logo_path=Path(__file__).resolve().parent / 'assets' / 'app_icon.png'
        if logo_path.is_file():
            from PySide6.QtGui import QPixmap
            logo.setPixmap(QPixmap(str(logo_path)).scaled(38,38,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:
            logo.setText('✦')
            logo.setStyleSheet('color: #AC87FF; font-size: 27px; font-weight: 900;')
        l.addWidget(logo)
        block=QWidget(); cols=vertical(block, 2)
        a=label(caption); a.setStyleSheet('font-size: 14px; font-weight: 800;')
        b=label('NEON STUDIO  /  DESKTOP', 'micro')
        cols.addWidget(a); cols.addWidget(b)
        l.addWidget(block)
        l.addStretch()
        self.status=label('●  Готов к работе')
        self.status.setStyleSheet('font-size: 12px; color: #49E3BE;')
        l.addWidget(self.status)
        l.addSpacing(16)
        for symbol,action,name in [('−',host.showMinimized,'circle'),('□',self.toggle_max,'circle'),('×',host.close,'close')]:
            b=btn(symbol,name,action)
            b.setToolTip({'−':'Свернуть','□':'Развернуть','×':'Закрыть'}[symbol])
            l.addWidget(b)

    def toggle_max(self):
        self.host.showNormal() if self.host.isMaximized() else self.host.showMaximized()

    def mousePressEvent(self, event):
        if event.button()==Qt.LeftButton:
            self._start=event.globalPosition().toPoint()-self.host.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._start is not None and event.buttons()&Qt.LeftButton and not self.host.isMaximized():
            self.host.move(event.globalPosition().toPoint()-self._start)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        self._start=None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:self.toggle_max()
        super().mouseDoubleClickEvent(event)


class DropZone(QFrame):
    chosen = Signal(str)
    def __init__(self):
        super().__init__()
        self.setObjectName('uploadZone')
        self.setMinimumHeight(147)
        self.setAcceptDrops(True)
        l=vertical(self,7,(18,14,18,14))
        l.setAlignment(Qt.AlignCenter)
        ico=label('♫');ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet('font-size: 36px; color: #A88AFF;')
        self.title=label('Перетащи песню сюда')
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet('font-size: 19px; font-weight: 700;')
        self.sub=label('MP3  ·  WAV  ·  M4A  ·  FLAC', 'muted')
        self.sub.setAlignment(Qt.AlignCenter)
        l.addWidget(ico);l.addWidget(self.title);l.addWidget(self.sub)
        choose=btn('Выбрать файл','secondary',self.pick)
        choose.setFixedWidth(158)
        l.addWidget(choose,0,Qt.AlignHCenter)

    def pick(self):
        p,_=QFileDialog.getOpenFileName(self,'Выбрать песню', '',
                    'Аудио (*.mp3 *.wav *.m4a *.flac *.ogg);;Все файлы (*)')
        if p:self.chosen.emit(p)

    def dragEnterEvent(self,event:QDragEnterEvent):
        if event.mimeData().hasUrls() and any(x.isLocalFile() for x in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self,event:QDropEvent):
        for u in event.mimeData().urls():
            p=u.toLocalFile()
            if Path(p).suffix.lower() in ('.mp3','.wav','.m4a','.flac','.ogg'):
                self.chosen.emit(p);event.acceptProposedAction();return


class RenderWorker(QThread):
    update=Signal(str)
    result=Signal(object,object)
    failed=Signal(str)
    def __init__(self,audio,settings):
        super().__init__()
        self.audio=audio
        self.settings=settings.copy()
    def run(self):
        try:
            s=self.settings
            project,info=run_auto(self.audio,s['projects_folder'],'pinterest','',
                    s.get('whisper_model','medium'),progress=self.update.emit,
                    separate_vocals=s.get('separate_vocals',False))
            self.result.emit(project,info)
        except Exception as exc:
            report_exception(exc, 'Ошибка сборки проекта')
            self.failed.emit(f'{exc}\n\nПодробности: {LOG_FILE}')


class LoginWorker(QThread):
    done=Signal(str)
    def run(self):
        try:
            from pinterest_source import login_once
            login_once()
            self.done.emit('Окно входа закрыто. Если вход выполнен, сессия сохранена.')
        except Exception as exc:
            report_exception(exc, 'Ошибка Pinterest')
            self.done.emit('Ошибка авторизации: '+str(exc))


class UpdateWorker(QThread):
    ready=Signal(object)
    failed=Signal(str)
    def __init__(self,mode='check',release=None):
        super().__init__()
        self.mode=mode
        self.release=release
    def run(self):
        try:
            if self.mode=='check':self.ready.emit(check_release())
            else:self.ready.emit(str(download_installer(self.release)))
        except Exception as exc:
            report_exception(exc,'Ошибка обновления')
            self.failed.emit(str(exc))


class AlignmentWorker(QThread):
    ready=Signal(object)
    failed=Signal(str)
    update=Signal(str)
    def __init__(self,audio,rows):
        super().__init__()
        self.audio=audio
        self.rows=rows
    def run(self):
        try:
            self.ready.emit(align_existing(self.audio,self.rows,progress=self.update.emit))
        except Exception as exc:
            report_exception(exc,'Ошибка выравнивания WhisperX')
            self.failed.emit(str(exc))


class SubtitleDialog(QDialog):
    def __init__(self,parent,project=None):
        super().__init__(parent)
        self.setWindowTitle('Редактор субтитров')
        self.resize(970,680)
        icon_path=Path(__file__).resolve().parent / 'assets' / 'app_icon.ico'
        if icon_path.is_file():self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground,True)
        self.rows=[]
        self.project=None
        self.audio_source=None
        self.alignment_worker=None
        self.audio_player=None
        self.audio_output=None
        if QMediaPlayer is not None:
            self.audio_player=QMediaPlayer(self)
            self.audio_output=QAudioOutput(self)
            self.audio_player.setAudioOutput(self.audio_output)
            self.audio_output.setVolume(0.6)
            self.audio_player.positionChanged.connect(self._audio_position)
        outer=vertical(self,0,(9,9,9,9))
        shell=QFrame();shell.setObjectName('windowShell')
        outer.addWidget(shell)
        container=vertical(shell,0,(0,0,0,0))
        container.addWidget(TitleBar(self,'Редактор субтитров'))
        body=QWidget();body.setObjectName('page')
        container.addWidget(body,1)
        l=vertical(body,14,(24,22,24,22))
        header=horizontal(space=12)
        title=label('Редактор субтитров','heading')
        header.addWidget(title);header.addStretch()
        header.addWidget(btn('Выбрать проект','secondary',self.browse))
        header.addWidget(btn('★  Запомнить правки CapCut','secondary',self.import_capcut))
        l.addLayout(header)
        self.pathlabel=label('Выбери проект CapCut с субтитрами','muted',True)
        l.addWidget(self.pathlabel)
        self.table=QTableWidget(0,3)
        self.table.setHorizontalHeaderLabels(['НАЧАЛО, СЕК','КОНЕЦ, СЕК','ФРАЗА'])
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        self.table.setColumnWidth(0,125);self.table.setColumnWidth(1,125)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(43)
        self.table.setToolTip('Дважды нажми на ячейку, чтобы изменить текст или время')
        l.addWidget(self.table,1)
        editor_actions=horizontal(space=9)
        editor_actions.addWidget(btn('＋  Добавить субтитр','primary',self.add_subtitle))
        editor_actions.addWidget(btn('⧉  Дублировать','secondary',self.duplicate_subtitle))
        editor_actions.addWidget(btn('−  Удалить','secondary',self.delete_subtitle))
        editor_actions.addStretch()
        l.addLayout(editor_actions)
        self.preview=label('Выдели строку для предпросмотра','cardHeading',True)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(76)
        self.preview.setStyleSheet('QLabel {background: #0A1325; border: 1px solid #45547C; border-radius: 16px; padding: 12px; color: #FFFFFF; font-size: 20px; font-weight: 700;}')
        l.addWidget(self.preview)
        self.wave=WaveformTimeline(self)
        l.addWidget(self.wave)
        self.wave.seekRequested.connect(self.seek_audio)
        self.wave.subtitleSelected.connect(self.table.selectRow)
        self.wave.subtitleEdited.connect(self._wave_timing_changed)
        playback=horizontal(space=9)
        self.play_btn=btn('▶  Прослушать','secondary',self.toggle_audio)
        self.play_btn.setEnabled(self.audio_player is not None)
        playback.addWidget(self.play_btn)
        self.play_label=label('00:00 / 00:00','muted')
        playback.addWidget(self.play_label)
        playback.addStretch()
        self.align_btn=btn('◷  Уточнить тайминги (WhisperX)','secondary',self.align_subtitles)
        playback.addWidget(self.align_btn)
        l.addLayout(playback)
        self.library_badge=label('Исправления сохраняются в библиотеке песен','muted')
        l.addWidget(self.library_badge)
        self.table.itemSelectionChanged.connect(self.update_preview)
        self.table.itemChanged.connect(self.update_preview)
        controls=horizontal(space=10)
        controls.addWidget(label('Сдвинуть всё на, сек.:','muted'))
        self.shift=QDoubleSpinBox();self.shift.setRange(-5,5);self.shift.setSingleStep(.05)
        self.shift.setDecimals(2);self.shift.setValue(.20)
        controls.addWidget(self.shift)
        controls.addWidget(btn('Сдвинуть', 'secondary', self.shift_all))
        controls.addStretch()
        controls.addWidget(btn('Сохранить в проект','primary',self.save))
        l.addLayout(controls)
        note=label('Запятые в конце фраз удаляются автоматически. Перед сохранением закрой CapCut: изменяется только текстовая дорожка.','muted',True)
        l.addWidget(note)
        if project:self.open_project(Path(project))

    def browse(self):
        p=QFileDialog.getExistingDirectory(self,'Папка проекта CapCut')
        if p:self.open_project(Path(p))

    def open_project(self,project):
        try: rows,_=_project_data(project)
        except Exception as e: QMessageBox.warning(self,'Не удалось открыть проект',str(e));return
        self.rows=rows;self.project=project
        self.pathlabel.setText(str(project))
        self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,v in enumerate((f"{row['start']:.3f}",f"{row['end']:.3f}",row['text'])):
                self.table.setItem(i,j,QTableWidgetItem(v))
        if rows:self.table.selectRow(0)
        try:
            self.audio_source=project_song(project)
            from builder import media_info
            duration=media_info(self.audio_source,'audio')['duration']/1_000_000
            self.wave.set_audio(waveform_peaks(self.audio_source),duration)
            if self.audio_player:
                self.audio_player.stop()
                self.audio_player.setSource(QUrl.fromLocalFile(str(self.audio_source)))
            rec=SongLibrary().load(self.audio_source)
            self.library_badge.setText('✓  Исправленные субтитры уже сохранены' if rec and rec['verified'] else
                                       'Черновик — правки сохранятся после нажатия «Сохранить»')
        except Exception as exc:
            self.audio_source=None
            self.library_badge.setText('Волна недоступна: '+str(exc)[:130])
        self.update_preview()

    def update_preview(self,*_):
        r=self.table.currentRow()
        if r<0 or not self.table.item(r,2):
            self.preview.setText('Выдели строку для предпросмотра')
        else:
            self.preview.setText(clean_caption(self.table.item(r,2).text()) or 'Новый субтитр')
        self.wave.set_captions(self._current_rows())
        self.wave.set_selected(r)

    def _current_rows(self):
        rows=[]
        for i in range(self.table.rowCount()):
            try:
                rows.append({'start':float(self.table.item(i,0).text().replace(',','.')),
                             'end':float(self.table.item(i,1).text().replace(',','.')),
                             'text':self.table.item(i,2).text()})
            except (AttributeError,ValueError):
                continue
        return rows

    def _wave_timing_changed(self,index,start,end):
        if index<0 or index>=self.table.rowCount():return
        self.table.blockSignals(True)
        self.table.item(index,0).setText(f'{start:.3f}')
        self.table.item(index,1).setText(f'{end:.3f}')
        self.table.blockSignals(False)

    def seek_audio(self,seconds):
        if self.audio_player:
            self.audio_player.setPosition(round(seconds*1000))
        self.wave.set_position(seconds)

    def _audio_position(self,position):
        secs=position/1000
        self.wave.set_position(secs)
        dur=self.wave.duration
        self.play_label.setText(f'{int(secs//60):02d}:{secs%60:04.1f} / {int(dur//60):02d}:{dur%60:04.1f}')

    def toggle_audio(self):
        if not self.audio_player or not self.audio_source:return
        if self.audio_player.playbackState()==QMediaPlayer.PlayingState:
            self.audio_player.pause()
            self.play_btn.setText('▶  Прослушать')
        else:
            self.audio_player.play()
            self.play_btn.setText('Ⅱ  Пауза')

    def import_capcut(self):
        if self.project is None:
            return self.browse()
        if QMessageBox.question(self,'Импортировать текст из CapCut?',
             'Закрой CapCut перед импортом. Все слова и таймкоды из текущего проекта '
             'будут сохранены как проверенная версия песни. Продолжить?')!=QMessageBox.Yes:return
        try:
            count,_=import_project_corrections(self.project)
        except Exception as exc:
            QMessageBox.warning(self,'Ошибка импорта',str(exc));return
        self.open_project(self.project)
        QMessageBox.information(self,'Библиотека песен',
            f'Сохранено {count} фраз. Для следующего ролика с этой песней они загрузятся автоматически.')

    def align_subtitles(self):
        if not self.audio_source:
            QMessageBox.warning(self,'Нет музыки','В проекте отсутствует исходная песня.');return
        if self.alignment_worker and self.alignment_worker.isRunning():return
        rows=self._current_rows()
        if not rows:return
        if QMessageBox.question(self,'Уточнить тайминги?',
              'WhisperX предложит новые временные границы для существующего текста. '
              'Слова не изменятся. Результат можно проверить перед сохранением.')!=QMessageBox.Yes:return
        self.align_btn.setEnabled(False)
        self.align_btn.setText('◌  Выравниваю…')
        self.alignment_worker=AlignmentWorker(self.audio_source,rows)
        self.alignment_worker.update.connect(self.library_badge.setText)
        self.alignment_worker.ready.connect(self._alignment_ready)
        self.alignment_worker.failed.connect(self._alignment_failed)
        self.alignment_worker.finished.connect(self._alignment_finished)
        self.alignment_worker.start()

    def _alignment_ready(self, rows):
        self.table.blockSignals(True)
        for i,(a,b,_) in enumerate(rows):
            if i<self.table.rowCount():
                self.table.item(i,0).setText(f'{a/1_000_000:.3f}')
                self.table.item(i,1).setText(f'{b/1_000_000:.3f}')
        self.table.blockSignals(False)
        self.update_preview()
        self.library_badge.setText('Временные границы обновлены. Проверь и нажми «Сохранить в проект».')

    def _alignment_failed(self,message):
        QMessageBox.warning(self,'Выравнивание недоступно',message)

    def _alignment_finished(self):
        self.align_btn.setEnabled(True)
        self.align_btn.setText('◷  Уточнить тайминги (WhisperX)')

    def add_subtitle(self):
        last_end=0.0
        for i in range(self.table.rowCount()):
            try:last_end=max(last_end,float(self.table.item(i,1).text().replace(',','.')))
            except (ValueError,AttributeError):pass
        self._append_row({'id':str(uuid.uuid4()).upper(), 'start':last_end+0.05,
                          'end':last_end+1.25, 'text':'Новый субтитр'})

    def duplicate_subtitle(self):
        row=self.table.currentRow()
        if row<0:return self.add_subtitle()
        txt=self.table.item(row,2).text() if self.table.item(row,2) else 'Новый субтитр'
        self.add_subtitle()
        self.table.item(self.table.rowCount()-1,2).setText(txt)

    def delete_subtitle(self):
        row=self.table.currentRow()
        if row<0:return
        self.table.removeRow(row)
        self.rows.pop(row)
        if self.table.rowCount():self.table.selectRow(min(row,self.table.rowCount()-1))
        self.update_preview()

    def _append_row(self,row):
        i=self.table.rowCount()
        self.rows.append(row)
        self.table.insertRow(i)
        for j,v in enumerate((f"{row['start']:.3f}",f"{row['end']:.3f}",row['text'])):
            self.table.setItem(i,j,QTableWidgetItem(v))
        self.table.selectRow(i)
        self.table.scrollToBottom()
        self.table.editItem(self.table.item(i,2))

    def shift_all(self):
        delta=self.shift.value()
        if not self.rows:return
        for i in range(self.table.rowCount()):
            for col in (0,1):
                item=self.table.item(i,col)
                try: val=float(item.text().replace(',','.'))+delta
                except Exception:continue
                item.setText(f'{val:.3f}')

    def closeEvent(self,event):
        if self.alignment_worker and self.alignment_worker.isRunning():
            QMessageBox.information(self,'Выравнивание','Дождись окончания синхронизации, прежде чем закрывать редактор.')
            event.ignore()
            return
        if self.audio_player:self.audio_player.stop()
        event.accept()

    def save(self):
        if self.project is None:return self.browse()
        values=[]
        try:
            for i,row in enumerate(self.rows):
                start=float(self.table.item(i,0).text().replace(',','.'))
                end=float(self.table.item(i,1).text().replace(',','.'))
                words=clean_caption(self.table.item(i,2).text())
                self.table.item(i,2).setText(words)
                values.append({**row,'start':start,'end':end,'text':words})
        except (ValueError,AttributeError):
            QMessageBox.warning(self,'Ошибка','Проверь текст и время всех строк.');return
        if QMessageBox.question(self,'Сохранить изменения?',
              'CapCut закрыт? Изменения в открытом проекте могут быть перезаписаны.') != QMessageBox.Yes:return
        try: count=apply_changes(self.project,values)
        except Exception as e: QMessageBox.critical(self,'Ошибка сохранения',str(e));return
        QMessageBox.information(self,'Сохранено',f'Текстовые блоки сохранены в {count} файлах проекта.')
        # Reload stable IDs generated by the writer, so newly added captions
        # can be edited and saved again without duplicating their materials.
        self.open_project(self.project)


class SongLibraryDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent)
        self.setWindowTitle('Библиотека песен')
        self.resize(760,510)
        self.library=SongLibrary()
        layout=vertical(self,14,(22,22,22,22))
        layout.addWidget(label('Библиотека исправленных песен','heading'))
        layout.addWidget(label('Слова и таймкоды сохраняются локально и доступны после обновлений. '
                               'Проверенные правки не заменяются автоматикой.','muted',True))
        self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['ПЕСНЯ','ФРАЗ','СТАТУС','ОБНОВЛЕНО'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table,1)
        row=horizontal(space=10)
        row.addWidget(btn('↻ Обновить','secondary',self.refresh))
        row.addWidget(btn('↗ Открыть папку библиотеки','secondary',self.open_folder))
        row.addStretch()
        row.addWidget(btn('Удалить запись','secondary',self.remove))
        layout.addLayout(row)
        self.entries=[]
        self.refresh()

    def refresh(self):
        self.entries=[]
        if self.library.directory.exists():
            for file in self.library.directory.glob('*.json'):
                try:
                    import json
                    doc=json.loads(file.read_text(encoding='utf-8'))
                    self.entries.append((file,doc))
                except (OSError,ValueError):continue
        self.entries.sort(key=lambda x:x[1].get('edited_utc',''),reverse=True)
        self.table.setRowCount(len(self.entries))
        for i,(_,d) in enumerate(self.entries):
            for col,text in enumerate((d.get('filename','—'),str(len(d.get('captions',[]))),
                                      '✓ Проверено' if d.get('verified') else 'Авто-черновик',
                                      d.get('edited_utc','')[:16].replace('T',' '))):
                self.table.setItem(i,col,QTableWidgetItem(text))

    def open_folder(self):
        self.library.directory.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.directory)))

    def remove(self):
        i=self.table.currentRow()
        if i<0 or i>=len(self.entries):return
        file,doc=self.entries[i]
        if QMessageBox.question(self,'Удалить исправления?',
              'Удалить сохранённые субтитры для «'+doc.get('filename','')+'»? '
              'Новый монтаж потребует распознавания заново.')!=QMessageBox.Yes:return
        file.unlink()
        self.refresh()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CapCut Auto Editor ' + VERSION)
        self.resize(1100,780)
        self.setMinimumSize(890,660)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground,True)
        self.worker=None
        self.login_worker=None
        self.update_worker=None
        self.last_project=None
        self.audio=''
        outer=QWidget();outer.setObjectName('background')
        self.setCentralWidget(outer)
        shell_pad=vertical(outer,0,(10,10,10,10))
        self.shell=QFrame();self.shell.setObjectName('windowShell')
        shell_pad.addWidget(self.shell)
        shell_layout=vertical(self.shell,0,(0,0,0,0))
        self.header=TitleBar(self)
        shell_layout.addWidget(self.header)
        body=QWidget();shell_layout.addWidget(body,1)
        bodyrow=horizontal(body,0)
        self.sidebar=QFrame();self.sidebar.setObjectName('sidebar')
        self.sidebar.setFixedWidth(218)
        bodyrow.addWidget(self.sidebar)
        self.pages=QStackedWidget();bodyrow.addWidget(self.pages,1)
        self._make_nav()
        self._make_main_page()
        self._make_settings_page()
        self._make_about_page()
        self.change_page(0)
        QTimer.singleShot(450,self.initial_check)
        self._updating=False

    def _make_nav(self):
        l=vertical(self.sidebar,9,(14,27,14,22))
        l.addWidget(label('РАБОЧЕЕ ПРОСТРАНСТВО','micro'))
        self.nav=[]
        for title,index in [('◉   Монтаж',0),('⚙   Настройки',1),('◎   О программе',2)]:
            b=btn(title,'nav',lambda _=False,i=index:self.change_page(i))
            b.setCheckable(True)
            l.addWidget(b);self.nav.append(b)
        l.addSpacing(13)
        l.addWidget(label('ИНСТРУМЕНТЫ','micro'))
        l.addWidget(btn('▤   Редактор субтитров','nav',self.open_captions))
        l.addWidget(btn('♫   Библиотека песен','nav',self.open_library))
        l.addStretch()
        box=card();bl=vertical(box,8,(15,15,15,15))
        bl.addWidget(label('✦   AUTO MODE'))
        desc=label('Одна песня — и проект собран автоматически.','muted',True)
        bl.addWidget(desc)
        l.addWidget(box)
        l.addWidget(label('VERSION '+VERSION+'  /  NEON','micro'))

    def scroll_page(self):
        page=QScrollArea();page.setObjectName('page');page.setWidgetResizable(True)
        content=QWidget();content.setObjectName('page');page.setWidget(content)
        self.pages.addWidget(page)
        return content

    def _make_main_page(self):
        content=self.scroll_page()
        l=vertical(content,18,(29,28,29,27))
        hdr=horizontal(space=10)
        titles=QWidget(); t=vertical(titles,6)
        t.addWidget(label('Новый монтаж','heading'))
        t.addWidget(label('Загрузи трек — всё остальное соберём автоматически.','muted'))
        hdr.addWidget(titles);hdr.addStretch()
        hdr.addWidget(label('PIN • AUTO','badge'))
        l.addLayout(hdr)
        upload=card(True);upl=vertical(upload,12,(21,18,21,21))
        upl.addWidget(label('01    ИСХОДНЫЙ ТРЕК','micro'))
        self.drop=DropZone();self.drop.chosen.connect(self.set_audio)
        upl.addWidget(self.drop)
        self.file_name=label('Песня ещё не выбрана','muted')
        upl.addWidget(self.file_name)
        l.addWidget(upload)
        row=horizontal(space=12)
        for num,ttl,desc,ico in [
           ('02','ПОИСК','3 атмосферных видео','⌕'),
           ('03','СУБТИТРЫ','Смысловые фразы','≡'),
           ('04','МОНТАЖ','Бит · эффекты · CapCut','✧')
        ]:
            c=card();cl=vertical(c,7,(16,16,16,16))
            top=horizontal(space=6)
            a=label(num,'micro');top.addWidget(a);top.addStretch()
            glyph=label(ico);glyph.setStyleSheet('font-size: 19px; color: #9B83FF')
            top.addWidget(glyph);cl.addLayout(top)
            cl.addWidget(label(ttl));cl.addWidget(label(desc,'muted',True))
            row.addWidget(c,1)
        l.addLayout(row)
        control=horizontal(space=12)
        self.build_btn=btn('✦   Создать проект CapCut','primary',self.start)
        self.build_btn.setMinimumHeight(55)
        glow=QGraphicsDropShadowEffect(self.build_btn)
        glow.setBlurRadius(25)
        glow.setOffset(0,3)
        glow.setColor(QColor(124,92,255,110))
        self.build_btn.setGraphicsEffect(glow)
        control.addWidget(self.build_btn,1)
        self.project_btn=btn('↗  Папка проекта','secondary',self.open_project_folder)
        self.project_btn.setEnabled(False)
        control.addWidget(self.project_btn)
        l.addLayout(control)
        status=card();sl=vertical(status,11,(17,15,17,16))
        statusrow=horizontal()
        statusrow.addWidget(label('СТАТУС ОБРАБОТКИ','micro'))
        statusrow.addStretch()
        self.stage=label('Ожидает запуска','successBadge')
        statusrow.addWidget(self.stage)
        sl.addLayout(statusrow)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0)
        sl.addWidget(self.progress)
        self.status=label('Добавь аудиофайл и нажми «Создать проект».','muted',True)
        sl.addWidget(self.status)
        self.log=QTextEdit();self.log.setReadOnly(True)
        self.log.setMinimumHeight(115)
        self.log.setMaximumHeight(210)
        self.log.setPlaceholderText('Здесь будут отображаться этапы работы...')
        sl.addWidget(self.log)
        l.addWidget(status)
        l.addStretch()

    def _make_settings_page(self):
        content=self.scroll_page();l=vertical(content,19,(29,28,29,25))
        l.addWidget(label('Настройки','heading'))
        l.addWidget(label('Настрой один раз, затем загружай только песню.','muted'))
        c=card();form=vertical(c,18,(23,24,23,24))
        form.addWidget(label('ПРОЕКТЫ CAPCUT','micro'))
        form.addWidget(label('Папка с локальными проектами CapCut','cardHeading'))
        pathrow=horizontal(space=8)
        self.folder=QLineEdit(SETTINGS.get('projects_folder',''))
        pathrow.addWidget(self.folder,1)
        pathrow.addWidget(btn('Обзор','secondary',self.pick_folder))
        form.addLayout(pathrow)
        form.addWidget(label('КАЧЕСТВО СУБТИТРОВ','micro'))
        self.model=QComboBox();self.model.addItems(['medium','large-v3'])
        self.model.setCurrentText(SETTINGS.get('whisper_model','medium'))
        form.addWidget(self.model)
        self.demucs=QCheckBox('Дополнительно отделять вокал Demucs (если установлен)')
        self.demucs.setChecked(SETTINGS.get('separate_vocals',False))
        form.addWidget(self.demucs)
        form.addWidget(label('Модель large-v3 точнее на некоторых песнях, но работает заметно дольше.','muted',True))
        l.addWidget(c)
        browser=card();br=vertical(browser,13,(23,20,23,20))
        br.addWidget(label('PINTEREST  ·  ФОНОВЫЙ ПОИСК','micro'))
        br.addWidget(label('Одна тематика на ролик · Повторы только через 7 дней','muted',True))
        br.addWidget(label('Браузер скрыт во время автоматического монтажа.','cardHeading',True))
        br.addWidget(label('Только если Pinterest запросит авторизацию, нажми «Войти» — откроется обычное окно для входа. При капче или блокировке программа остановится.','muted',True))
        br.addWidget(btn('Открыть Pinterest для входа','secondary',self.pinterest_login),0,Qt.AlignLeft)
        l.addWidget(browser)
        local_template=card();lt=vertical(local_template,12,(23,20,23,20))
        lt.addWidget(label('ЛОКАЛЬНЫЙ ШАБЛОН МОНТАЖА','micro'))
        lt.addWidget(label('Твой шаблон CapCut хранится только на этом компьютере — не загружается в GitHub.','muted',True))
        lt.addWidget(btn('Импортировать template_original.zip','secondary',self.import_template),0,Qt.AlignLeft)
        l.addWidget(local_template)
        l.addWidget(btn('Сохранить настройки','primary',self.store_settings),0,Qt.AlignRight)
        l.addStretch()

    def _make_about_page(self):
        content=self.scroll_page();l=vertical(content,16,(29,28,29,25))
        l.addWidget(label('О приложении','heading'))
        c=card();body=vertical(c,15,(25,24,25,24))
        body.addWidget(label('✦   CAPCUT AUTO EDITOR','cardHeading'))
        body.addWidget(label('Автоматическая сборка редактируемых проектов CapCut: музыкальный анализ, поиск трёх видео, субтитры, монтаж и эффекты.','muted',True))
        body.addWidget(label('Pinterest работает в экспериментальном режиме. Используй для публикации только материалы, на которые у тебя есть права.','muted',True))
        body.addWidget(label('Распознавание вокала и разбиение на фразы может ошибаться — редактор субтитров доступен в боковом меню.','muted',True))
        body.addWidget(label('Версия '+VERSION,'muted'))
        body.addWidget(btn('Открыть журнал ошибок','secondary',self.open_logs),0,Qt.AlignLeft)
        self.updates_btn=btn('↻  Проверить обновления','primary',self.check_updates)
        body.addWidget(self.updates_btn,0,Qt.AlignLeft)
        body.addWidget(label('Обновления загружаются из публичных GitHub Releases. При установке программа закроется, проекты и модели сохранятся.','muted',True))
        l.addWidget(c);l.addStretch()

    def check_updates(self):
        if self.update_worker is not None and self.update_worker.isRunning():return
        self.updates_btn.setEnabled(False)
        self.updates_btn.setText('Проверяю GitHub…')
        self.update_worker=UpdateWorker('check')
        self.update_worker.ready.connect(self._release_checked)
        self.update_worker.failed.connect(self._update_failed)
        self.update_worker.start()

    def _update_failed(self,why):
        self.updates_btn.setEnabled(True)
        self.updates_btn.setText('↻  Проверить обновления')
        QMessageBox.warning(self,'Проблема обновления',why)

    def _release_checked(self,release):
        self.updates_btn.setEnabled(True)
        self.updates_btn.setText('↻  Проверить обновления')
        if release is None:
            QMessageBox.information(self,'Обновления','У тебя последняя версия '+VERSION)
            return
        if QMessageBox.question(self,'Доступна '+release['tag'],
                'Найдено обновление '+release['tag']+'. Скачать и установить?\n\n'+release['notes'][:350]) != QMessageBox.Yes:
            return
        if (self.worker and self.worker.isRunning()) or (self.login_worker and self.login_worker.isRunning()):
            QMessageBox.warning(self,'Занято','Дождись окончания монтажа или поиска Pinterest.')
            return
        self._updating=True
        self.updates_btn.setEnabled(False)
        self.updates_btn.setText('Загружаю установщик…')
        self.update_worker=UpdateWorker('download',release)
        self.update_worker.ready.connect(self._installer_ready)
        self.update_worker.failed.connect(self._update_failed)
        self.update_worker.start()

    def _installer_ready(self,path):
        self.updates_btn.setEnabled(True)
        self.updates_btn.setText('↻  Проверить обновления')
        try:
            launch_installer(Path(path))
        except Exception as exc:
            self._update_failed(str(exc))
            return
        # The update worker must exit before Qt objects are torn down.
        QTimer.singleShot(500,QApplication.instance().quit)

    def change_page(self,index):
        self.pages.setCurrentIndex(index)
        for i,b in enumerate(self.nav):b.setChecked(i==index)

    def set_audio(self,p):
        self.audio=p
        self.drop.title.setText(Path(p).stem[:65])
        self.drop.sub.setText('Файл выбран  ·  '+Path(p).suffix.upper().strip('.'))
        self.file_name.setText(str(p))
        self.note('Загружен музыкальный файл. Готов к монтажу.')

    def note(self,msg):
        self.status.setText(msg)
        self.log.append('• '+msg)
        bar=self.log.verticalScrollBar();bar.setValue(bar.maximum())

    def initial_check(self):
        try:template_zip()
        except FileNotFoundError:
            self.note('Нужно один раз импортировать шаблон из папки предыдущей версии.')
            self.change_page(1)
        if not Path(SETTINGS.get('projects_folder','')).is_dir():
            self.note('Укажи путь к проектам CapCut в настройках (один раз).')
            self.change_page(1)

    def import_template(self):
        filename,_=QFileDialog.getOpenFileName(self,'Выбери template_original.zip из V7.3','',
                                               'Архив проекта (*.zip)')
        if not filename:return
        try:
            with zipfile.ZipFile(filename) as z:
                if not any(x.endswith('/draft_content.json') for x in z.namelist()):
                    raise ValueError('Это не ZIP-шаблон CapCut с draft_content.json.')
            USER_TEMPLATE_ZIP.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(filename,USER_TEMPLATE_ZIP)
        except Exception as exc:
            QMessageBox.warning(self,'Не удалось импортировать',str(exc));return
        QMessageBox.information(self,'Шаблон сохранён',
            'Импортировано локально. При последующих обновлениях шаблон останется на компьютере.')

    def open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE.parent)))

    def pick_folder(self):
        p=QFileDialog.getExistingDirectory(self,'Папка проектов CapCut',self.folder.text())
        if p:self.folder.setText(p)

    def store_settings(self):
        p=self.folder.text().strip()
        if not Path(p).is_dir():
            QMessageBox.warning(self,'Папка не найдена','Выбери существующую папку проектов CapCut.');return False
        SETTINGS.update({'provider':'pinterest','api_key':'','projects_folder':p,
                         'whisper_model':self.model.currentText(),
                         'separate_vocals':self.demucs.isChecked()})
        save_settings(SETTINGS)
        self.note('Настройки сохранены.')
        self.change_page(0)
        return True

    def pinterest_login(self):
        if self.login_worker is not None and self.login_worker.isRunning():return
        self.login_worker=LoginWorker(self)
        self.login_worker.done.connect(lambda msg: QMessageBox.information(self,'Pinterest',msg))
        self.login_worker.start()
        QMessageBox.information(self,'Pinterest','Сейчас откроется окно для входа. Войди в Pinterest и закрой его — дальнейший поиск будет фоновым.')

    def start(self):
        if self.worker is not None and self.worker.isRunning():return
        if not self.audio or not Path(self.audio).is_file():
            QMessageBox.warning(self,'Нет музыки','Сначала выбери аудиофайл.');return
        if not Path(SETTINGS.get('projects_folder','')).is_dir():
            QMessageBox.warning(self,'Нет папки проектов','В настройках укажи папку проектов CapCut.')
            self.change_page(1);return
        self.build_btn.setText('◌   Создаю проект…')
        self.build_btn.setProperty('working', True)
        self.build_btn.style().unpolish(self.build_btn)
        self.build_btn.style().polish(self.build_btn)
        self.build_btn.setEnabled(False)
        self.stage.setText('●  В процессе')
        self.header.status.setText('●  Монтирую')
        self.progress.setRange(0,0)
        self.note('Запускаю автоматическую сборку...')
        self.worker=RenderWorker(self.audio,SETTINGS)
        self.worker.update.connect(self.note)
        self.worker.result.connect(self.finish)
        self.worker.failed.connect(self.failed)
        self.worker.start()

    def finish(self,path,info):
        self.last_project=Path(path)
        self.build_btn.setEnabled(True)
        self.build_btn.setProperty('working', False)
        self.build_btn.setText('✓   Проект готов — создать ещё')
        self.build_btn.style().unpolish(self.build_btn)
        self.build_btn.style().polish(self.build_btn)
        self.project_btn.setEnabled(True)
        self.progress.setRange(0,100);self.progress.setValue(100)
        self.stage.setText('✓  Готово')
        self.header.status.setText('●  Готово')
        self.note(f"Проект собран: {info.get('clips',0)} видеофрагментов, {info.get('captions',0)} субтитров.")
        QMessageBox.information(self,'Проект готов',
           'Редактируемый проект создан. Если CapCut уже открыт — перезапусти его, чтобы появился новый проект.\n\n'+str(path))

    def failed(self,msg):
        self.build_btn.setEnabled(True)
        self.build_btn.setProperty('working', False)
        self.build_btn.setText('✦   Создать проект CapCut')
        self.build_btn.style().unpolish(self.build_btn)
        self.build_btn.style().polish(self.build_btn)
        self.progress.setRange(0,100);self.progress.setValue(0)
        self.stage.setText('!  Ошибка')
        self.header.status.setText('●  Ожидает')
        self.note('ОШИБКА: '+msg)
        QMessageBox.critical(self,'Не удалось создать проект',msg)

    def open_project_folder(self):
        if self.last_project and self.last_project.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_project)))

    def open_captions(self):
        dia=SubtitleDialog(self,self.last_project)
        dia.exec()

    def open_library(self):
        dia=SongLibraryDialog(self)
        dia.exec()


    def closeEvent(self,event):
        if ((self.worker is not None and self.worker.isRunning()) or
            (self.login_worker is not None and self.login_worker.isRunning()) or
            (self.update_worker is not None and self.update_worker.isRunning())):
            QMessageBox.information(self,'Выполняется задача',
                'Сейчас идёт обработка. Дождись её завершения, чтобы не повредить проект.')
            event.ignore()
            return
        event.accept()


def main():
    # Bundled FFmpeg and Chromium in the installed Windows EXE distribution.
    if getattr(sys,'frozen',False):
        base=Path(sys.executable).resolve().parent
        os.environ['PATH']=str(base)+os.pathsep+os.environ.get('PATH','')
        browser=base/'ms-playwright'
        if browser.is_dir():os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(browser)
    # Durable crash log, including Qt's hidden Windows launch without console.
    install_crash_logger()
    # Give this Python-based app its own Windows taskbar identity and icon.
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('CapCutAutoEditor.Neon.V7')
        except Exception:
            pass
    app=QApplication(sys.argv)
    icon_path = Path(__file__).resolve().parent / 'assets' / 'app_icon.ico'
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle('Fusion')
    app.setFont(QFont('Inter Tight',10))
    app.setStyleSheet(STYLES)
    window=MainWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
