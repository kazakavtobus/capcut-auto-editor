"""Experimental Pinterest video acquisition through a background browser.

Pinterest prohibits unauthorized automated access in its Terms. This module does
not evade login gates, CAPTCHAs, bot challenges, geoblocks or access controls.
Media is not assumed to have a reuse licence. Always review rights before upload.
"""
from __future__ import annotations

import hashlib
import os
import sys
import random
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from auto_pipeline import CONFIG_DIR, StockError, media_info, MICRO
from video_history import VideoHistory, fingerprint

BROWSER_PROFILE = CONFIG_DIR / 'pinterest_browser_profile'


def _playwright():
    # The packaged EXE bundles Chromium beside the executable. Playwright must
    # be pointed at that bundled browser; otherwise it searches a user cache.
    if getattr(sys, 'frozen', False):
        bundled = Path(sys.executable).resolve().parent / 'ms-playwright'
        if bundled.is_dir():
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled)
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError as exc:
        raise StockError('Не установлен Playwright. Закрой программу и запусти install.bat.') from exc


def _context(playwright, visible=False):
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    try:
        return playwright.chromium.launch_persistent_context(
            str(BROWSER_PROFILE), headless=not visible, viewport={'width': 1330, 'height': 870},
            accept_downloads=False, locale='ru-RU', timeout=30000,
        )
    except Exception as exc:
        raise StockError('Не получилось запустить фоновый поиск Pinterest. Попробуй переустановить Chromium через install.bat.\n'+str(exc)[:300]) from exc


def login_once():
    """Open an isolated Pinterest browser profile. User logs in and closes window."""
    with _playwright()() as p:
        context = _context(p, visible=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto('https://www.pinterest.com/login/', wait_until='domcontentloaded', timeout=35000)
            # Browser is intentionally visible and under direct user control.
            while context.pages and any(not x.is_closed() for x in context.pages):
                time.sleep(1)
        except Exception as exc:
            if 'Target page, context or browser has been closed' not in str(exc):
                raise
        finally:
            try: context.close()
            except Exception: pass


def _blocked(page) -> bool:
    try:
        txt = page.locator('body').inner_text(timeout=4000).lower()[:4500]
        return any(x in txt for x in ('we detected a bot','we’ve detected a bot', 'подозрительн', 'unusual activity',
                                     'verify you are human', 'security check'))
    except Exception:
        return False


def _needs_login(page) -> bool:
    try:
        return '/login' in page.url or (page.get_by_role('textbox', name=re.compile('email|электрон', re.I)).count() > 0
                                         and page.get_by_role('textbox', name=re.compile('password|парол', re.I)).count() > 0)
    except Exception:
        return '/login' in page.url


def _video_urls(response):
    try:
        url = response.url
        host=(urlparse(url).hostname or '').lower()
        base = url.split('?',1)[0].lower()
        if host.endswith('.pinimg.com') and ('.m3u8' in base or '.mp4' in base):
            return url
    except Exception:
        pass
    return None


def _search_pin_links(page, query, progress):
    address='https://www.pinterest.com/search/pins/?q='+quote(query+' aesthetic video')
    try:
        page.goto(address, wait_until='domcontentloaded', timeout=40000)
        page.wait_for_timeout(1600)
    except Exception as exc:
        raise StockError('Pinterest не загрузил страницу поиска: '+str(exc)[:250]) from exc
    if _blocked(page):
        raise StockError('Pinterest обнаружил автоматический доступ и ограничил поиск. Не пытайся обходить проверку: останови программу и используй разрешённые источники.')
    if _needs_login(page):
        raise StockError('Pinterest требует входа. В настройках нажми «Войти в Pinterest», войди и закрой браузер.')
    found=[]; seen=set()
    for _ in range(4):
        try:
            anchors=page.locator('a[href*="/pin/"]').evaluate_all('''nodes => nodes.map(a => ({
                 href: a.href,
                 video: !!(a.querySelector('video') || a.closest('[data-test-id="pin"]')?.querySelector('video'))
            }))''')
        except Exception:
            anchors=[]
        for item in anchors:
            u=item.get('href','').split('?',1)[0]
            if re.search(r'pinterest\.[^/]+/pin/\d+/?$',u) and u not in seen:
                seen.add(u); found.append({'url':u,'has_video_preview':bool(item.get('video'))})
        if len(found)>=35:break
        page.mouse.wheel(0,1300)
        page.wait_for_timeout(1100)
    found.sort(key=lambda x: (not x['has_video_preview'], x['url']))
    progress(f'Pinterest: по запросу «{query}» найдено {len(found)} пинов.')
    return found[:30]


def _try_ytdlp(pin_url: str, folder: Path):
    from yt_dlp import YoutubeDL
    folder.mkdir(parents=True,exist_ok=True)
    opts={'outtmpl': str(folder/'pinterest.%(ext)s'), 'format':'bv*[height<=1080]/b[height<=1080]/best',
          'quiet':True,'no_warnings':True,'noplaylist':True,
          'socket_timeout':20,'retries':1,'fragment_retries':1,'extractor_retries':1,
          'max_filesize':115*1024*1024}
    try:
        with YoutubeDL(opts) as ydl: ydl.download([pin_url])
    except Exception:
        pass
    return next((f for f in folder.glob('pinterest.*') if f.is_file() and f.stat().st_size > 100_000),None)


def _try_video_stream(page, pin_url: str, folder: Path):
    """Fallback to directly served public Pinimg media; no DRM/challenge bypass."""
    from yt_dlp import YoutubeDL
    media=[]
    def on_response(resp):
        u=_video_urls(resp)
        if u and u not in media:media.append(u)
    page.on('response',on_response)
    try:
        page.goto(pin_url, wait_until='domcontentloaded', timeout=25000)
        page.wait_for_timeout(1800)
        if _blocked(page): return None
        try:
            dom=page.locator('video').evaluate_all('''nodes => nodes.map(v=> v.currentSrc || v.src).filter(Boolean)''')
            for u in dom:
                if u.startswith('https://') and (urlparse(u).hostname or '').endswith('.pinimg.com') and u not in media:
                    media.append(u)
        except Exception:pass
        for u in media[:3]:
            try:
                with YoutubeDL({'outtmpl':str(folder/'stream.%(ext)s'), 'quiet':True,
                                 'no_warnings':True,'socket_timeout':20,'retries':1,'fragment_retries':1,
                                 'max_filesize':115*1024*1024}) as ydl:
                    ydl.download([u])
                output=next((f for f in folder.glob('stream.*') if f.is_file() and f.stat().st_size>100_000),None)
                if output:return output
            except Exception:continue
    except Exception:
        return None
    finally:
        try:page.remove_listener('response',on_response)
        except Exception:pass
    return None


def download_three(queries: list[str], song_id: str, outdir: Path, progress=None,
                   history: VideoHistory | None = None, theme: str = 'cinematic') -> list[dict]:
    """Search regular Pinterest pages in a headless browser; stop on access gates."""
    status=progress or (lambda _:None)
    outdir.mkdir(parents=True,exist_ok=True)
    rng=random.Random(int(hashlib.sha256(song_id.encode()).hexdigest()[:12],16))
    selected=[];used=set();attempts=0;skipped=0
    if history is None:
        history=VideoHistory(CONFIG_DIR/'video_history.json')
    with _playwright()() as p:
        context=_context(p)
        try:
            search_page=context.pages[0] if context.pages else context.new_page()
            detail_page=context.new_page()
            theme_queries=list(dict.fromkeys(queries))
            rng.shuffle(theme_queries)
            # Crucial: no unrelated city/rain fallback if another theme was selected.
            for query in theme_queries[:12]:
                if len(selected)==3 or attempts>=100:break
                status('Pinterest: ищу видео — '+query)
                pins=_search_pin_links(search_page,query,status)
                video_pins=[pin for pin in pins if pin['has_video_preview']]
                others=[pin for pin in pins if not pin['has_video_preview']]
                rng.shuffle(video_pins);rng.shuffle(others)
                picked_for_this_query=False
                for pin in video_pins+others:
                    if len(selected)==3 or attempts>=100 or picked_for_this_query:break
                    u=pin['url']
                    if u in used:continue
                    used.add(u)
                    candidate={'id':'pinterest-'+u.rstrip('/').rsplit('/',1)[-1],
                               'page':u,'provider':'pinterest','query':query}
                    if history.reason(candidate):
                        skipped+=1
                        continue
                    attempts+=1
                    status(f'Pinterest: проверяю новый пин {attempts}/100 (видео: {len(selected)}/3)')
                    attempt_dir=outdir/f'attempt_{attempts:02d}'
                    attempt_dir.mkdir(exist_ok=True)
                    media=_try_ytdlp(u,attempt_dir)
                    if media is None:media=_try_video_stream(detail_page,u,attempt_dir)
                    if media is None:continue
                    try:
                        info=media_info(media,'video')
                        if info['duration']<5*MICRO or media.stat().st_size>115*1024*1024:
                            continue
                    except Exception:continue
                    sha,visual=fingerprint(media)
                    why=history.reason(candidate,sha,visual)
                    if why:
                        skipped+=1
                        status('Pinterest: пропускаю повтор — '+why)
                        continue
                    target=outdir/f'pinterest_{len(selected)+1:02d}{media.suffix}'
                    shutil.copy2(media,target)
                    history.add_candidate(candidate,sha,visual,theme)
                    picked_for_this_query=True
                    selected.append({'id':candidate['id'], 'page':u, 'creator':'',
                                     'query':query,'provider':'pinterest',
                                     'checked_sha256':sha,'local_test_path':str(target)})
                    status(f'Pinterest: скачано {len(selected)}/3 видео.')
            if len(selected)<3:
                raise StockError(f'Pinterest: найдено {len(selected)} из трёх уникальных видео. '
                                 f'Пропущено повторов: {skipped}. Для выбранной темы '
                                 'недостаточно новых футажей. Старые видео не подставляю. '
                                 'Попробуй позже или выбери другой трек.')
            return selected
        finally:
            try: context.close()
            except Exception: pass
