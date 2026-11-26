"""Human-readable, collision-safe export names and manual delivery metadata."""
import os,re,unicodedata
from pathlib import Path
from account_names import account_name

def safe_part(value,limit):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',str(value))
    value=' '.join(value.split()).strip(' .')[:limit].rstrip(' .')
    return value or 'Видео'

def manual_metadata(path,settings):
    """Infer account only from an unambiguous, recognized filename prefix."""
    stem=unicodedata.normalize('NFC',Path(path).stem).strip()
    aliases={}
    for a in ('1','2'):
        values=[account_name(settings,a), 'Аккаунт '+a]
        if a=='1':values.append('Unison Muz')
        for value in values:
            key=unicodedata.normalize('NFC',safe_part(value,40)).casefold()
            aliases.setdefault(key,set()).add(a)
    for name in sorted(aliases,key=len,reverse=True):
        match=re.match(r'^'+re.escape(name)+r'(?:\s*[—–]\s*|\s+-\s+)(.+)$',stem,flags=re.IGNORECASE)
        if match and len(aliases[name])==1:
            song=re.sub(r'\s+[—–]\s+ролик\s+\d{3,}$','',match.group(1),flags=re.IGNORECASE).strip()
            return next(iter(aliases[name])),song or stem
        if match:return None,stem
    return None,stem

def publish_export(source,root,settings,account,song):
    """Move a verified export from its private staging directory to the visible archive.
    Reserve the filename exclusively before replacing our own empty reservation.
    Existing files and other projects are never overwritten.
    """
    source=Path(source);root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    stem=safe_part(account_name(settings,account),40)+' — '+safe_part(song,100)
    for i in range(1,10000):
        name=stem+('' if i==1 else f' — ролик {i:03d}')+'.mp4'
        target=root/name
        try:
            with target.open('xb'):pass
        except FileExistsError:continue
        try:os.replace(source,target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target
    raise FileExistsError('Слишком много роликов с одинаковым названием.')
