"""Persistent exception, Python-thread and native-fault logs on Windows."""
from __future__ import annotations
import faulthandler
import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CapCutAutoEditor' / 'logs'
LOG_FILE = LOG_DIR / 'app.log'
_fault_stream = None
_installed = False


def install_crash_logger():
    global _installed, _fault_stream
    if _installed:return
    LOG_DIR.mkdir(parents=True,exist_ok=True)
    root=logging.getLogger('capcut_auto_editor')
    root.setLevel(logging.INFO)
    handler=RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(threadName)s] %(message)s'))
    root.addHandler(handler)
    root.info('Application start, Python=%s, executable=%s', sys.version.split()[0], sys.executable)
    def excepthook(cls, exc, tb):
        root.critical('Unhandled GUI exception:\n%s',''.join(traceback.format_exception(cls,exc,tb)))
    sys.excepthook=excepthook
    if hasattr(threading,'excepthook'):
        def thread_hook(args):
            root.critical('Unhandled Python worker exception:\n%s',
                          ''.join(traceback.format_exception(args.exc_type,args.exc_value,args.exc_traceback)))
        threading.excepthook=thread_hook
    # A native crash (e.g. Qt/CTranslate2) may bypass Python exception hooks.
    try:
        _fault_stream=open(LOG_DIR/'native_faults.log','a',encoding='utf-8',buffering=1)
        faulthandler.enable(file=_fault_stream, all_threads=True)
    except (OSError,RuntimeError):
        root.exception('Native crash logger unavailable')
    _installed=True


def report_exception(exc:BaseException,context:str):
    if not _installed:install_crash_logger()
    logging.getLogger('capcut_auto_editor').error('%s: %s',context,exc,exc_info=(type(exc),exc,exc.__traceback__))
