"""Optional local WebGL composition preview; editor remains usable without it."""
from pathlib import Path
import json
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton

class CompositionPreview(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.browser=None;self.ready=False;self.words='Слова песни'
        l=QVBoxLayout(self);l.setContentsMargins(0,0,0,0)
        self.toggle=QPushButton('Предпросмотр композиции · 9:16')
        self.toggle.setObjectName('secondary');self.toggle.clicked.connect(self.open);l.addWidget(self.toggle)
        self.notice=QLabel('Условная композиция. Точное оформление проверяй в CapCut.')
        self.notice.setObjectName('muted');self.notice.setWordWrap(True);self.notice.hide();l.addWidget(self.notice)
        self.layout_box=l
    def open(self):
        if self.browser:
            visible=not self.browser.isVisible()
            self.browser.setVisible(visible);self.notice.setVisible(visible)
            return
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineSettings
            page=Path(__file__).resolve().parent/'assets'/'composition.html'
            if not page.is_file() or not page.with_name('composition.bundle.js').is_file():raise RuntimeError('Локальный модуль предпросмотра не установлен.')
            view=QWebEngineView(self)
            view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,False)
            view.setMinimumHeight(260);view.setMaximumHeight(360)
            self.browser=view;self.layout_box.addWidget(view)
            view.loadFinished.connect(self.loaded)
            self.notice.show();view.load(QUrl.fromLocalFile(str(page)))
        except Exception as exc:
            self.notice.setText('Предпросмотр WebGL недоступен. Обычный редактор работает.');self.notice.show()
    def loaded(self,ok):
        self.ready=bool(ok)
        self.update_words(self.words)
    def update_words(self,words):
        self.words=str(words or 'Слова песни')
        if self.browser and self.ready:
            self.browser.page().runJavaScript('window.setCaption && window.setCaption('+json.dumps(self.words,ensure_ascii=True)+')')
