"""Check public GitHub releases and safely verify an Inno Setup update installer.

No GitHub token is ever stored in the app. The installer itself runs after the
main application closes; versioned settings/models are held in LocalAppData.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from version import VERSION, REPOSITORY

API='https://api.github.com/repos/'+REPOSITORY+'/releases/latest'
INSTALLER_NAME='CapCutAutoEditor_Setup.exe'
CHECKSUM_NAME=INSTALLER_NAME+'.sha256'

class UpdateError(RuntimeError):pass


def _download(url:str,limit:int=1_000_000_000)->bytes:
    if not url.startswith('https://'):
        raise UpdateError('Разрешена загрузка только по HTTPS')
    request=Request(url,headers={'User-Agent':'CapCutAutoEditor/'+VERSION,
                                 'Accept':'application/vnd.github+json'})
    with urlopen(request,timeout=40) as response:
        n=0
        chunks=[]
        while data:=response.read(1024*1024):
            n+=len(data)
            if n>limit:raise UpdateError('Файл обновления слишком большой')
            chunks.append(data)
    return b''.join(chunks)


def _version(s:str):
    m=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)' ,s)
    if not m:raise UpdateError('Некорректный номер версии: '+s)
    return tuple(map(int,m.groups()))


def check_release():
    try:doc=json.loads(_download(API,2_000_000).decode('utf-8'))
    except Exception as exc:raise UpdateError('Не получилось проверить GitHub Releases: '+str(exc)) from exc
    tag=doc.get('tag_name','')
    if _version(tag)<=_version(VERSION):return None
    assets={a['name']:a for a in doc.get('assets',[]) if 'name' in a}
    if INSTALLER_NAME not in assets or CHECKSUM_NAME not in assets:
        raise UpdateError('Новая версия найдена, но установщик или контрольная сумма отсутствует')
    for name in (INSTALLER_NAME,CHECKSUM_NAME):
        if not assets[name].get('browser_download_url','').startswith(
            'https://github.com/'+REPOSITORY+'/releases/download/'):
            raise UpdateError('Неверный адрес скачивания обновления')
    return {'tag':tag,'notes':doc.get('body','')[:2000],
            'installer':assets[INSTALLER_NAME]['browser_download_url'],
            'checksum':assets[CHECKSUM_NAME]['browser_download_url']}


def download_installer(release:dict)->Path:
    expected_text=_download(release['checksum'],2048).decode('ascii').strip()
    match=re.search(r'\b([a-fA-F0-9]{64})\b',expected_text)
    if not match:raise UpdateError('Некорректный SHA256 в файле релиза')
    expected=match.group(1).lower()
    target=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CapCutAutoEditor'/'updates'
    target.mkdir(parents=True,exist_ok=True)
    path=target/(release['tag']+'-'+INSTALLER_NAME)
    from urllib.request import urlopen
    request=Request(release['installer'], headers={'User-Agent':'CapCutAutoEditor/'+VERSION})
    temp=path.with_suffix('.download')
    sha=hashlib.sha256()
    total=0
    try:
        with urlopen(request,timeout=60) as src, temp.open('wb') as dest:
            while chunk:=src.read(1024*1024):
                total+=len(chunk)
                if total>1_500_000_000:
                    raise UpdateError('Установщик слишком большой')
                dest.write(chunk)
                sha.update(chunk)
        if sha.hexdigest()!=expected:
            raise UpdateError('Контрольная сумма обновления не совпала. Установка отменена.')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def launch_installer(path:Path):
    if os.name!='nt':raise UpdateError('Автоустановка доступна только на Windows')
    if not path.is_file():raise UpdateError('Установщик не найден')
    # Runs per-user (not administrator) and recreates the Start Menu shortcut.
    subprocess.Popen([str(path),'/SILENT','/SUPPRESSMSGBOXES','/NORESTART',
                      '/CLOSEAPPLICATIONS','/RESTARTAPPLICATIONS'],cwd=str(path.parent))
