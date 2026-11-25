"""Local outbound Telegram transport. Never log the token or expose it in errors."""
import hashlib,json,re,sqlite3,uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from song_library import APPDATA
from account_names import account_name

MAX_BYTES=50_000_000
class TelegramError(RuntimeError):pass
class UnknownDelivery(TelegramError):pass

def validate_token(token):
    token=token.strip()
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}',token):
        raise TelegramError('Вставь токен бота из BotFather.')
    return token

def chat_ids(value):
    ids=list(dict.fromkeys(re.split(r'[\s,;]+',value.strip())))
    if not ids or len(ids)>10 or any(not re.fullmatch(r'-?[1-9]\d{0,18}',x) for x in ids):
        raise TelegramError('Укажи от 1 до 10 числовых Chat ID через пробел или запятую.')
    return ids

def tag(value,limit=55):
    return ''.join(c for c in value if c.isalnum() or c=='_')[:limit] or 'Видео'

def caption(settings,account,song,digest):
    if account not in ('1','2'):raise TelegramError('Неизвестный аккаунт.')
    name=account_name(settings,account)
    song=' '.join(str(song).split())[:180] or 'Без названия'
    tags=list(dict.fromkeys(['#'+tag(name),'#account'+account,'#Песня_'+tag(song),'#Ролик_'+digest[:12]]))
    return '🏭 ТикТок Завод\nАккаунт: '+name+'\nПесня: '+song+'\nГотово к публикации\n\n'+' '.join(tags)

def config_path():return APPDATA/'telegram.json'
def load_config():
    try:
        obj=json.loads(config_path().read_text(encoding='utf-8'))
        return {k:obj.get(k,'') if isinstance(obj.get(k,''),str) else '' for k in ('token','chats')}
    except (OSError,ValueError,AttributeError):return {'token':'','chats':''}

def save_config(token,chats):
    token=validate_token(token);ids=chat_ids(chats)
    p=config_path();p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps({'token':token,'chats':', '.join(ids)},ensure_ascii=False),encoding='utf-8')
    tmp.replace(p)

def api(token,method,fields=None,file=None):
    token=validate_token(token)
    fields=fields or {}
    if file is None:
        payload=json.dumps(fields).encode('utf-8');ctype='application/json'
    else:
        boundary='studio-'+uuid.uuid4().hex
        parts=[]
        for key,value in fields.items():
            parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+str(value)+'\r\n').encode('utf-8'))
        # Use a fixed safe filename; the exact MP4 bytes are sent as a document.
        parts.extend([('--'+boundary+'\r\nContent-Disposition: form-data; name="document"; filename="video.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode(),file,b'\r\n',('--'+boundary+'--\r\n').encode()])
        payload=b''.join(parts);ctype='multipart/form-data; boundary='+boundary
    request=Request('https://api.telegram.org/bot'+token+'/'+method,data=payload,
                    headers={'Content-Type':ctype,'User-Agent':'TikTokZavodStudio'},method='POST')
    try:
        with urlopen(request,timeout=120 if file is not None else 20) as response:
            raw=response.read(2_000_001)
    except HTTPError as exc:
        try:doc=json.loads(exc.read(65536))
        except Exception:doc={}
        # Explicit Telegram rejection is safe to retry, but transport/server errors may be ambiguous.
        if 400<=exc.code<500 and isinstance(doc,dict) and doc.get('ok') is False:
            hints={400:'Проверь Chat ID, размер файла и доступ бота.',401:'Токен неверный или отозван.',403:'Бот заблокирован или не имеет доступа к чату.',409:'У бота уже работает webhook или другой получатель обновлений.',429:'Слишком много сообщений. Повтори позже.'}
            raise TelegramError('Telegram: '+str(exc.code)+'. '+hints.get(exc.code,'Запрос отклонён.')) from None
        raise UnknownDelivery('Telegram не подтвердил результат. Проверь чат перед повтором.') from None
    except Exception:
        raise UnknownDelivery('Нет подтверждения от Telegram. Проверь сеть и чат перед повтором.') from None
    try:doc=json.loads(raw)
    except (ValueError,UnicodeError):raise UnknownDelivery('Некорректный ответ Telegram. Проверь чат.') from None
    if not isinstance(doc,dict) or doc.get('ok') is not True:
        raise UnknownDelivery('Telegram не подтвердил результат. Проверь чат.')
    return doc.get('result')

def discover(token):
    me=api(token,'getMe')
    updates=api(token,'getUpdates',{'timeout':0,'limit':100,'allowed_updates':['message']})
    found={}
    for update in updates or []:
        chat=(update.get('message') or {}).get('chat') or {}
        if 'id' in chat:
            name=chat.get('title') or ' '.join(filter(None,[chat.get('first_name'),chat.get('last_name')])) or 'Чат'
            found[str(chat['id'])]=str(name)[:100]
    return {'bot':'@'+me['username'],'chats':found}

def history_db():
    APPDATA.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(APPDATA/'telegram-deliveries.sqlite3',timeout=15)
    db.execute("""CREATE TABLE IF NOT EXISTS deliveries(
        bot TEXT,chat TEXT,account TEXT,digest TEXT,status TEXT,message_id INTEGER,
        PRIMARY KEY(bot,chat,account,digest))""")
    return db

def send_export(token,chats,path,settings,account,song,progress=None):
    """One future export hook; only confirmed MP4s, explicit destinations, exact bytes."""
    token=validate_token(token);ids=chat_ids(chats)
    if account not in ('1','2'):raise TelegramError('Неизвестный аккаунт.')
    p=Path(path)
    if p.suffix.lower()!='.mp4' or not p.is_file():raise TelegramError('Выбери готовый MP4 после экспорта.')
    if not 0<p.stat().st_size<=MAX_BYTES:raise TelegramError('Размер MP4 должен быть от 1 байта до 50 МБ. Файл не сжат и не отправлен.')
    with p.open('rb') as f:video=f.read(MAX_BYTES+1)
    if not 0<len(video)<=MAX_BYTES:raise TelegramError('Файл изменился или превышает 50 МБ.')
    # Standard MP4 ISO BMFF header; reject non-video/unfinished arbitrary files.
    if len(video)<12 or video[4:8]!=b'ftyp':raise TelegramError('Файл не похож на готовый MP4.')
    digest=hashlib.sha256(video).hexdigest()
    text=caption(settings,account,song,digest)
    bot=token.split(':',1)[0];out=[]
    db=history_db()
    try:
        for chat in ids:
            key=(bot,chat,account,digest)
            with db:
                cur=db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,'pending',NULL)",key)
                inserted=cur.rowcount==1
                if not inserted:
                    state=db.execute('SELECT status FROM deliveries WHERE bot=? AND chat=? AND account=? AND digest=?',key).fetchone()[0]
            if not inserted:
                out.append((chat,'Уже отправлено' if state=='sent' else 'Не подтверждено ранее; проверь чат, повтор заблокирован'))
                continue
            if progress:progress('Отправка MP4 в чат '+chat+'…')
            try:
                result=api(token,'sendDocument',{'chat_id':chat,'caption':text},video)
                if not isinstance(result,dict) or not isinstance(result.get('message_id'),int):
                    raise UnknownDelivery('Нет ID сообщения. Проверь чат.')
            except UnknownDelivery as exc:
                out.append((chat,str(exc)));continue
            except TelegramError as exc:
                with db:db.execute('DELETE FROM deliveries WHERE bot=? AND chat=? AND account=? AND digest=?',key)
                out.append((chat,str(exc)));continue
            with db:db.execute("UPDATE deliveries SET status='sent',message_id=? WHERE bot=? AND chat=? AND account=? AND digest=?",(result['message_id'],*key))
            out.append((chat,'Отправлено'))
    finally:db.close()
    return out
