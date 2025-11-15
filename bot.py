from dotenv import load_dotenv
import os
import random
import time
import requests
import praw
import re
import sys
import time
import json
import os
import base64
import random
import hashlib
import requests
import subprocess
from pathlib import Path
from urllib.parse import unquote
from PIL import Image
import io
from bs4 import BeautifulSoup
import asyncio
import threading
from twscrape import API, gather
from types import SimpleNamespace
import shutil
import m3u8
import unicodedata
import logging
import sqlite3
# Pnytter kaldırıldı - sadece TWSCRAPE kullanılacak
# Lazy import için Google AI modüllerini kaldır - ihtiyaç duyulduğunda import edilecek

# FastAPI for web service - lazy import
# from fastapi import FastAPI, Request - lazy import
# from fastapi.responses import PlainTextResponse - lazy import
# import uvicorn - lazy import
# import psycopg2 - lazy import
# from psycopg2.extras import RealDictCursor - lazy import

load_dotenv()

# Resolve script directory and accounts DB absolute path early
SCRIPT_DIR = Path(__file__).resolve().parent
_env_db = os.environ.get("ACCOUNTS_DB_PATH", "accounts.db")
if os.path.isabs(_env_db):
    ACCOUNTS_DB_PATH = _env_db
else:
    ACCOUNTS_DB_PATH = str((SCRIPT_DIR / _env_db).resolve())

# Ensure accounts.db exists (for Railway/containers without shell)
def _ensure_accounts_db():
    try:
        db_path = Path(ACCOUNTS_DB_PATH)
        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            # Quick sanity check for readability
            if not os.access(db_path, os.R_OK):
                print(f"[UYARI] accounts.db okunamıyor (izinler): {db_path}")
            return
        b64 = os.environ.get("ACCOUNTS_DB_B64")
        if not b64:
            # Nothing to do; twscrape will log "No active accounts" later if required
            print("[INFO] ACCOUNTS_DB_B64 bulunamadı; accounts.db oluşturulmadı")
            return
        try:
            data = base64.b64decode(b64)
        except Exception:
            # Handle potential newlines/spaces
            data = base64.b64decode(b64.encode("ascii"))
        db_path.write_bytes(data)
        try:
            # Best-effort chown in Linux containers; ignore on Windows
            import pwd, grp  # type: ignore
            import os as _os
            uid = _os.getuid() if hasattr(_os, "getuid") else None
            gid = _os.getgid() if hasattr(_os, "getgid") else None
            if uid is not None and gid is not None:
                _os.chown(str(db_path), uid, gid)
        except Exception:
            pass
        print(f"[+] accounts.db oluşturuldu: {db_path}")
    except Exception as e:
        print(f"[UYARI] accounts.db oluşturulamadı: {e}")

_ensure_accounts_db()

# User-Agent rotation pool
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0'
]

# Session pool için global değişkenler
SESSION_POOL = {}
SESSION_LAST_USED = {}
MAX_SESSION_AGE = 1800  # 30 dakika

# Proxy ayarları
PROXY_LIST = [
    # Ücretsiz HTTP proxy'ler - çalışanları ekleyin
    # {'http': 'http://proxy1:port', 'https': 'http://proxy1:port'},
    # {'http': 'http://proxy2:port', 'https': 'http://proxy2:port'},
]

# Tor proxy (eğer kuruluysa)
TOR_PROXY = {
    'http': 'socks5://127.0.0.1:9050',
    'https': 'socks5://127.0.0.1:9050'
}

CURRENT_PROXY_INDEX = 0
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"
USE_TOR = os.getenv("USE_TOR", "false").lower() == "true"

# twscrape API instance
twscrape_api = None
from base64 import b64decode

# RedditWarp imports
import redditwarp.SYNC
from redditwarp.SYNC import Client as RedditWarpClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Local-only mode: skip FastAPI/uvicorn when true
LOCAL_ONLY = os.getenv("LOCAL_ONLY", "false").strip().lower() == "true"
USE_EXTERNAL_QUEUE = os.getenv("USE_EXTERNAL_QUEUE", "false").strip().lower() == "true"
QUEUE_URL = (os.getenv("QUEUE_URL", "") or "").strip()
MANIFEST_URL = (os.getenv("MANIFEST_URL", "") or "").strip()
MANIFEST_PATH = (os.getenv("MANIFEST_PATH", "manifest.json") or "manifest.json").strip()
MANIFEST_REFRESH_SECONDS = int(os.getenv("MANIFEST_REFRESH_SECONDS", "300") or 300)
MANIFEST_MAX_POSTS_PER_CYCLE = int(os.getenv("MANIFEST_MAX_POSTS_PER_CYCLE", "1") or 1)
MANIFEST_TEST_FIRST_ITEM = os.getenv("MANIFEST_TEST_FIRST_ITEM", "false").strip().lower() == "true"
DOWNLOAD_CONNECT_TIMEOUT = float(os.getenv("DOWNLOAD_CONNECT_TIMEOUT", "5") or 5)
DOWNLOAD_READ_TIMEOUT = float(os.getenv("DOWNLOAD_READ_TIMEOUT", "60") or 60)
DOWNLOAD_CHUNK_SLEEP_MS = int(os.getenv("DOWNLOAD_CHUNK_SLEEP_MS", "0") or 0)

# --- Localization helpers (Unicode + casing) ---
def _nfc(s: str) -> str:
    """Return NFC-normalized text to keep Turkish diacritics stable."""
    try:
        return unicodedata.normalize('NFC', s) if isinstance(s, str) else s
    except Exception:
        return s

def _parse_iso8601(ts: str):
    try:
        # Accept both "Z" and offsetless
        from datetime import datetime, timezone
        t = ts.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        return datetime.fromisoformat(t).astimezone(timezone.utc)
    except Exception:
        return None

# --- Reddit text sanitizer ---
def _sanitize_for_reddit(s: str) -> str:
    """Sanitize text for Reddit to avoid byte-marker artifacts and stray emojis.
    - NFC normalize
    - Remove patterns like '<0xF0><0x9F>...'
    - Remove control chars except basic whitespace and newlines
    - Heuristic removal of most emoji codepoints
    """
    try:
        if not isinstance(s, str):
            return s
        txt = _nfc(s)
        # Remove hex byte marker sequences
        txt = re.sub(r"(?:<0x[0-9A-Fa-f]{2}>)+", "", txt)
        # Remove zero-width spaces and control chars except tab/newline
        txt = "".join(ch for ch in txt if (ch == "\n" or ch == "\t" or (ch >= " " and ch not in ("\u200b",))))
        # Remove common emoji ranges (simple heuristic)
        txt = "".join(ch for ch in txt if not (0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF))
        # Collapse spaces
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt
    except Exception:
        return s

# duplicate removed

def _is_all_caps_like(s: str) -> bool:
    """Heuristic: treat as ALL CAPS if >=80% of letters are uppercase and there is at least one letter."""
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return False
    upp = sum(1 for ch in letters if ch.isupper())
    return (upp / max(1, len(letters))) >= 0.8

def _deshout_en_sentence_case(s: str) -> str:
    """Convert shouty English text to sentence case to improve translation quality.
    Keeps non-letter characters as is. Simple sentence boundary heuristic."""
    try:
        s_low = s.lower()
        out = []
        make_upper = True
        for ch in s_low:
            out.append(ch.upper() if make_upper and ch.isalpha() else ch)
            if ch in '.!?\n':
                make_upper = True
            elif ch.isalpha():
                make_upper = False
        return ''.join(out)
    except Exception:
        return s

# --- Countdown detection helper ---
def _extract_countdown_days(text: str):
    """Detect patterns like '44 Days Until ...' in text and return the day count as int.
    Returns None if not found. Case-insensitive, tolerant of extra spaces and punctuation.
    """
    try:
        if not text:
            return None
        # Normalize whitespace
        t = ' '.join(str(text).split())
        # Common patterns: '44 Days Until', '10 day until', '3 DAYS UNTIL'
        m = re.search(r"\b(\d{1,3})\s*(day|days)\s+until\b", t, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        return None
    except Exception:
        return None

# Windows encoding sorununu güvenli şekilde çöz (buffer olmayabilir)
if sys.platform.startswith('win'):
    import codecs
    try:
        stdout_base = getattr(sys.stdout, 'buffer', sys.stdout)
        stderr_base = getattr(sys.stderr, 'buffer', sys.stderr)
        sys.stdout = codecs.getwriter('utf-8')(stdout_base, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(stderr_base, 'strict')
    except Exception as _enc_e:
        print(f"[UYARI] Windows encoding ayarı atlandı: {_enc_e}")

load_dotenv()

SUBREDDIT = "bf6_tr"

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT = "python:bf6-gaming-news-bot:v1.1.0 (by /u/BFHaber_Bot)"
RAPIDAPI_TRANSLATE_KEY = os.getenv("RAPIDAPI_TRANSLATE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# Posted IDs storage backend selector
USE_DB_FOR_POSTED_IDS = bool(DATABASE_URL)
# If true, bot MUST have DB; otherwise exit instead of using file fallback
FAIL_IF_DB_UNAVAILABLE = os.getenv("FAIL_IF_DB_UNAVAILABLE", "true").lower() == "true"

# Retention and dedupe configuration
# How many posted tweet IDs to retain in storage (DB/file)
POSTED_IDS_RETENTION = int(os.getenv("POSTED_IDS_RETENTION", "200"))
# If enabled, skip any tweet with id <= last seen numeric id at startup/runtime
HIGH_WATERMARK_ENABLED = os.getenv("HIGH_WATERMARK_ENABLED", "true").lower() == "true"

# Translate cache (avoid repeated Gemini calls for identical input)
TRANSLATE_CACHE_MAX = int(os.getenv("TRANSLATE_CACHE_MAX", "500"))
try:
    from collections import OrderedDict
except Exception:
    OrderedDict = dict  # very rare fallback; order eviction won't be perfect
TRANSLATE_CACHE = OrderedDict()
TRANSLATE_CACHE_LOCK = threading.Lock()

# Belirli tweet ID'lerini asla Reddit'e göndermeyin (kullanıcı isteği)
# Bu ID'ler işlenmiş olarak da işaretlenir, böylece tekrar denenmez
EXCLUDED_TWEET_IDS = {
    "1958574822692462777",
    "19585522850022935535",
    "1958552050322616811",
    "1958551490953367669",
    "1958551346367324285",
    "1958548172915044642",
    "1958529168376770882",
    "1958287931153760384",
    "1958287931153760384",
    "1958025330372825431",
}

# Nitter konfigürasyonu kaldırıldı - sadece TWSCRAPE kullanılacak
TWITTER_SCREENNAME = os.getenv("TWITTER_SCREENNAME", "TheBFWire").strip()
# Twitter User ID (tercih edilen yöntem - daha güvenilir)
TWITTER_USER_ID = os.getenv("TWITTER_USER_ID", "1939708158051500032").strip()
MIN_REQUEST_INTERVAL = 30  # Minimum seconds between any requests
LAST_REQUEST_TIME = 0  # Son istek zamanı
TWSCRAPE_DETAIL_TIMEOUT = 8  # seconds to wait for tweet_details before skipping
REDDIT_MAX_VIDEO_SECONDS = int(os.getenv("REDDIT_MAX_VIDEO_SECONDS", "900"))
ENABLE_SECONDARY_RETWEETS = os.getenv("ENABLE_SECONDARY_RETWEETS", "false").strip().lower() == "true"
 
# Optional: process specific tweet id(s) via environment
PROCESS_TWEET_ID = (os.getenv("PROCESS_TWEET_ID", "") or "").strip()
PROCESS_TWEET_IDS = (os.getenv("PROCESS_TWEET_IDS", "") or "").strip()
PROCESSED_ENV_IDS = set()

# Scheduled weekly player-finder post config (stateless, configurable via env)
def _parse_days_env(val: str) -> set[int]:
    out: set[int] = set()
    try:
        for p in (val or "").split(","):
            p = p.strip()
            if not p:
                continue
            try:
                d = int(p)
                if 1 <= d <= 31:
                    out.add(d)
            except Exception:
                continue
    except Exception:
        pass
    return out or set()

# New: allow scheduling by weekday (0=Mon .. 6=Sun). Default 4 (Friday).
SCHEDULED_PIN_WEEKDAY = int(os.getenv("SCHEDULED_PIN_WEEKDAY", "4"))
# Backward-compat: if SCHEDULED_PIN_DAYS provided, it will be used only if WEEKDAY is invalid (<0 or >6).
SCHEDULED_PIN_DAYS = _parse_days_env(os.getenv("SCHEDULED_PIN_DAYS", ""))
SCHEDULED_PIN_HOUR = int(os.getenv("SCHEDULED_PIN_HOUR", "9"))
SCHEDULED_PIN_TITLE_PREFIX = os.getenv("SCHEDULED_PIN_TITLE_PREFIX", "Haftalık Oyuncu Arama Ana Başlığı - (")
SCHEDULED_PIN_ENABLED = (os.getenv("SCHEDULED_PIN_ENABLED", "true").strip().lower() == "true")

# PRAW konfigürasyonunu Reddit API kurallarına uygun şekilde optimize et
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    username=REDDIT_USERNAME,
    password=REDDIT_PASSWORD,
    user_agent=REDDIT_USER_AGENT,
    ratelimit_seconds=60,  # Reddit API: Max 60 requests per minute
    timeout=30,  # Daha kısa timeout
    check_for_updates=False,
    check_for_async=False
)

# RedditWarp client setup
try:
    # RedditWarp client oluştur - positional credentials ile username/password authentication
    redditwarp_client = RedditWarpClient(
        REDDIT_CLIENT_ID,
        REDDIT_CLIENT_SECRET,
        REDDIT_USERNAME,
        REDDIT_PASSWORD
    )
    
    # User agent ayarla
    redditwarp_client.http.headers['User-Agent'] = REDDIT_USER_AGENT
    
    print("[+] RedditWarp client başarıyla kuruldu")
    
except Exception as rw_setup_error:
    print(f"[UYARI] RedditWarp setup hatası: {rw_setup_error}")
    redditwarp_client = None

def get_random_user_agent():
    """Rastgele User-Agent döndür"""
    return random.choice(USER_AGENTS)

def get_proxy():
    """Aktif proxy ayarlarını döndür"""
    global CURRENT_PROXY_INDEX
    
    if USE_TOR:
        print("[+] Tor proxy kullanılıyor")
        return TOR_PROXY
    elif USE_PROXY and PROXY_LIST:
        proxy = PROXY_LIST[CURRENT_PROXY_INDEX % len(PROXY_LIST)]
        CURRENT_PROXY_INDEX += 1
        print(f"[+] HTTP proxy kullanılıyor: {proxy}")
        return proxy
    else:
        return None

def test_proxy(proxy):
    """Proxy'nin çalışıp çalışmadığını test et"""
    try:
        response = requests.get('http://httpbin.org/ip', proxies=proxy, timeout=10)
        if response.status_code == 200:
            ip_info = response.json()
            print(f"[+] Proxy çalışıyor - IP: {ip_info.get('origin', 'Unknown')}")
            return True
    except Exception as e:
        print(f"[UYARI] Proxy test başarısız: {e}")
    return False

def get_or_create_session(instance_url):
    """ Instance için session al veya yeni oluştur (memory optimized)"""
    global SESSION_POOL, SESSION_LAST_USED
    
    current_time = time.time()
    
    # Eski session'ları temizle - memory management
    expired_keys = []
    for key, last_used in SESSION_LAST_USED.items():
        if current_time - last_used > MAX_SESSION_AGE:
            expired_keys.append(key)
    
    for key in expired_keys:
        if key in SESSION_POOL:
            try:
                SESSION_POOL[key].close()
            except Exception:
                pass
            del SESSION_POOL[key]
        del SESSION_LAST_USED[key]
    
    # Temizlik
    del expired_keys
    
    # Mevcut session'ı kullan veya yeni oluştur
    if instance_url not in SESSION_POOL:
        session = requests.Session()
        session.headers.update({
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Proxy ayarlarını ekle
        proxy = get_proxy()
        if proxy:
            if test_proxy(proxy):
                session.proxies.update(proxy)
            # Logging azaltıldı - sadece hata durumunda log
        
        SESSION_POOL[instance_url] = session
    
    SESSION_LAST_USED[instance_url] = current_time
    return SESSION_POOL[instance_url]

def clean_text(text):
    """Metni temizle ve kısalt"""
    text = re.sub(r'http[s]?://\S+', '', text)
    text = re.sub(r't\.co/\S+', '', text)
    text = re.sub(r'#\w+', '', text)
    text = text.replace('|', '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_tweet_text(text):
    if not text:
        return ""
    # RT @<screenname>: ifadesini kaldır (env'den alınan TWITTER_SCREENNAME)
    try:
        if TWITTER_SCREENNAME:
            pattern = rf'^RT @{re.escape(TWITTER_SCREENNAME)}:\s*'
            text = re.sub(pattern, '', text)
    except Exception:
        pass
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r't\.co/\S+', '', text)
    text = re.sub(r'#\w+', '', text)
    # "via @nickname" ve genel @mention'ları kaldır
    # via @user (parantez içinde/sonunda olabilir)
    text = re.sub(r'(?i)\bvia\s+@[-_a-zA-Z0-9]+', '', text)
    # tüm @mention'ları kaldır (örn: @user, @User_Name)
    text = re.sub(r'@[A-Za-z0-9_]+', '', text)
    # Boş kalan parantez/dash kalıntılarını toparla
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\[\s*\]', '', text)
    text = re.sub(r'\s*[-–—]\s*$', '', text)
    text = text.replace('|', '')
    # Satır sonlarını koru, sadece aynı satırdaki fazla boşlukları temizle
    # \n karakterlerini geçici olarak koruma altına al
    text = text.replace('\n', '|||NEWLINE|||')
    text = re.sub(r'\s+', ' ', text)  # Fazla boşlukları tek boşluğa çevir
    text = text.replace('|||NEWLINE|||', '\n')  # Satır sonlarını geri getir
    # Satır başı/sonundaki gereksiz boşlukları temizle ama satır sonlarını koru
    lines = text.split('\n')
    lines = [line.strip() for line in lines]
    text = '\n'.join(lines)
    return text.strip()

def extract_username_from_tweet_url(url: str) -> str:
    """Tweet URL'sinden kullanıcı adını çıkar.
    Beklenen biçimler:
    - https://x.com/<username>/status/<id>
    - https://twitter.com/<username>/status/<id>
    Uyumlu değilse varsayılan olarak TWITTER_SCREENNAME döner.
    """
    try:
        if not url:
            return TWITTER_SCREENNAME
        m = re.search(r"https?://(?:x|twitter)\.com/([^/]+)/status/", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return TWITTER_SCREENNAME

async def init_twscrape_api():
    """twscrape API'yi başlat"""
    global twscrape_api
    if twscrape_api is None:
        # Debug: show resolved DB path and basic access
        print(f"[DEBUG] twscrape accounts DB path: {ACCOUNTS_DB_PATH}")
        if not os.path.exists(ACCOUNTS_DB_PATH):
            print("[UYARI] accounts.db bulunamadı, twscrape erişimi başarısız olabilir")
        elif not os.access(ACCOUNTS_DB_PATH, os.R_OK):
            print("[UYARI] accounts.db dosyası okunamıyor (izin)")
        # Optional: enable verbose native twscrape logs
        try:
            if os.getenv("TWSCRAPE_DEBUG", "false").strip().lower() == "true":
                # Set up root logger minimally if not configured
                if not logging.getLogger().handlers:
                    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
                # Verbose for twscrape and httpx
                logging.getLogger("twscrape").setLevel(logging.DEBUG)
                logging.getLogger("twscrape.api").setLevel(logging.DEBUG)
                logging.getLogger("httpx").setLevel(logging.WARNING)
                print("[INFO] TWSCRAPE_DEBUG etkin: twscrape native logları DEBUG seviyesinde")
        except Exception:
            pass
        twscrape_api = API(ACCOUNTS_DB_PATH)
        print("[+] twscrape API başlatıldı")
        # Diagnostics: inspect DB content and pool availability
        try:
            conn = sqlite3.connect(ACCOUNTS_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='accounts'")
            has_tbl = (cur.fetchone() or [0])[0] > 0
            if has_tbl:
                cur.execute("SELECT username, active FROM accounts")
                rows = cur.fetchall() or []
                actives = [r[0] for r in rows if (r[1] in (1, True, '1'))]
                print(f"[DIAG] accounts toplam={len(rows)} aktif={len(actives)} -> {actives}")
            else:
                print("[DIAG] accounts tablosu bulunamadı (DB boş olabilir)")
            conn.close()
        except Exception as de:
            print(f"[DIAG] accounts DB inceleme hatası: {de}")
        try:
            nat = await twscrape_api.pool.next_available_at("timeline")
            if not nat:
                print("[DIAG] twscrape pool: aktif hesap yok (next_available_at=None)")
            else:
                print(f"[DIAG] twscrape pool: sonraki uygun hesap {nat}")
        except Exception as de:
            print(f"[DIAG] pool inceleme hatası: {de}")
    return twscrape_api

async def _get_best_media_urls(tweet_id: int | str) -> tuple[str | None, str | None]:
    """twscrape ile tweet detaylarından en iyi MP4 ve HLS URL'lerini bul.
    Dönüş: (best_mp4_url, best_hls_url)
    """
    try:
        api = await init_twscrape_api()
        try:
            detail = await asyncio.wait_for(api.tweet_details(int(tweet_id)), timeout=TWSCRAPE_DETAIL_TIMEOUT)
        except Exception as te:
            print(f"[UYARI] tweet_details timeout/hata: {te}")
            detail = None
        if not detail or not getattr(detail, "media", None):
            print("[UYARI] Tweet detayında medya bulunamadı")
            return None, None

        videos = getattr(detail.media, "videos", []) or []
        if not videos:
            print("[UYARI] Video medyası yok")
            return None, None

        mp4_candidates: list[tuple[int, str]] = []
        hls_candidates: list[tuple[int, str]] = []
        for v in videos:
            variants = getattr(v, "variants", []) or []
            if os.getenv("ACCOUNTS_PRINT_VARIANTS", "false").lower() == "true":
                print(f"[DEBUG] Variants: {[getattr(x,'url',None) for x in variants]}")
            for var in variants:
                url = getattr(var, "url", None)
                br = getattr(var, "bitrate", 0) or 0
                if not url:
                    continue
                ul = url.lower()
                if ul.endswith(".m3u8"):
                    hls_candidates.append((br, url))
                elif ".mp4" in ul or ul.endswith(".mp4"):
                    mp4_candidates.append((br, url))

        best_mp4 = max(mp4_candidates, key=lambda x: x[0])[1] if mp4_candidates else None
        best_hls = max(hls_candidates, key=lambda x: x[0])[1] if hls_candidates else None
        if best_mp4:
            print(f"[+] MP4 aday bulundu: {best_mp4}")
        else:
            print("[INFO] MP4 varyantı bulunamadı")
        if best_hls:
            print(f"[+] HLS aday bulundu: {best_hls}")
        return best_mp4, best_hls
    except Exception as e:
        print(f"[HATA] twscrape media çözümleme hatası: {e}")
        return None, None

def _download_hls_py(hls_url: str, filename: str) -> str | None:
    """FFmpeg yoksa saf-Python HLS indirme (Render uyumlu)."""
    try:
        playlist = m3u8.load(hls_url)
        if not playlist or not playlist.segments:
            print("[UYARI] HLS playlist boş veya geçersiz")
            return None
        base = hls_url.rsplit('/', 1)[0]
        with open(filename, 'wb') as out:
            for seg in playlist.segments:
                surl = seg.uri
                if not surl.startswith('http'):
                    surl = f"{base}/{surl}"
                try:
                    with requests.get(surl, timeout=30, stream=True) as r:
                        if r.status_code == 200:
                            for chunk in r.iter_content(1024 * 64):
                                if chunk:
                                    out.write(chunk)
                        else:
                            print(f"[UYARI] Segment indirilemedi: {surl} -> {r.status_code}")
                            return None
                except Exception as se:
                    print(f"[UYARI] Segment hatası: {se}")
                    return None
        return filename
    except Exception as e:
        print(f"[HATA] HLS py indirme hatası: {e}")
        return None

def download_best_video_for_tweet(tweet_id: str | int, out_filename: str) -> str | None:
    """Tweet için en kaliteli videoyu indir (HLS tercihli, sonra MP4, opsiyonel yt-dlp)."""
    try:
        # 1) En iyi URL'leri al (async)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            best_mp4, best_hls = loop.run_until_complete(_get_best_media_urls(tweet_id))
        finally:
            loop.close()

        # 2) Önce HLS dene
        if best_hls:
            ffmpeg_path = shutil.which('ffmpeg')
            if ffmpeg_path:
                print("[+] HLS ffmpeg ile indiriliyor...")
                cmd = [ffmpeg_path, '-y', '-i', best_hls, '-c', 'copy', out_filename]
                try:
                    subprocess.run(cmd, check=True, timeout=300)
                    if os.path.exists(out_filename) and os.path.getsize(out_filename) > 0:
                        return out_filename
                except subprocess.CalledProcessError as cpe:
                    print(f"[UYARI] ffmpeg HLS indirimi başarısız: {cpe}")
                except subprocess.TimeoutExpired:
                    print("[UYARI] ffmpeg HLS indirmesi zaman aşımı")
            # Saf Python HLS
            if os.getenv('USE_PY_HLS', 'true').lower() == 'true':
                print("[+] HLS saf-Python ile indiriliyor...")
                hls_path = _download_hls_py(best_hls, out_filename)
                if hls_path:
                    return hls_path

        # 3) MP4 varyantı ile indir
        if best_mp4:
            print("[+] MP4 varyantı indiriliyor...")
            path = download_media(best_mp4, out_filename)
            if path:
                return path

        # 4) Son çare: yt-dlp (opsiyonel)
        if os.getenv('USE_YTDLP', 'false').lower() == 'true':
            try:
                print("[+] yt-dlp fallback deneniyor...")
                url = f"https://x.com/i/web/status/{tweet_id}"
                cmd = [
                    'yt-dlp', '-f', 'bv*+ba/b[ext=mp4]/bv/best', '-o', out_filename, url
                ]
                subprocess.run(cmd, check=True, timeout=600)
                if os.path.exists(out_filename) and os.path.getsize(out_filename) > 0:
                    return out_filename
            except Exception as yte:
                print(f"[UYARI] yt-dlp fallback başarısız: {yte}")

        print("[UYARI] En kaliteli video indirilemedi")
        return None
    except Exception as e:
        print(f"[HATA] En kaliteli video indirirken: {e}")
        return None

def _is_retweet_of_target(raw_text: str, target_screenname: str) -> bool:
    """Metnin belirli hedef hesabın retweet'i olup olmadığını kontrol eder.
    - Büyük/küçük harf duyarsız
    - '@hedef' sonrası ':' opsiyonel
    - Birden fazla alias destekler (virgülle ayrılmış)
    """
    if not raw_text:
        return False
    # Alias listesi: env üzerinden de verilebilir (örn: "bf6_tr,bf6tr,battlefield6tr")
    aliases_env = os.getenv("SECONDARY_RETWEET_TARGET", target_screenname) or target_screenname
    aliases = [a.strip().lstrip('@').lower() for a in aliases_env.split(',') if a.strip()]
    txt = raw_text.strip()
    if not txt.lower().startswith('rt '):
        # RT ifadesi varsa ama farklı biçimde olabilir; yine de hızlı kontrol
        if 'rt @' not in txt.lower():
            return False
    # Esnek desen: RT [boşluklar] @alias(:| )
    for alias in aliases:
        pattern = rf"^\s*RT\s+@{re.escape(alias)}\b\s*:?(\s|$)"
        if re.search(pattern, txt, flags=re.IGNORECASE):
            return True
    return False

async def _get_bf6_retweets_twscrape(target: str, count: int = 3):
    """bf6_tr (veya SECONDARY_RETWEET_TARGET) kullanıcısının zaman akışından
    retweet olan öğeleri bulur ve retweet edilen ORİJİNAL tweet'leri döndürür.
    """
    try:
        api = await init_twscrape_api()
        # Hedef kullanıcıyı ID ile bulmaya çalış, yoksa login ile dene
        target_id_env = (os.getenv("SECONDARY_RETWEET_TARGET_ID", "") or "").strip()
        user = None
        if target_id_env and target_id_env.isdigit():
            try:
                user = await api.user_by_id(int(target_id_env))
            except Exception as _euid:
                print(f"[UYARI] target user by id alınamadı: {target_id_env} -> {_euid}")
        if not user:
            user = await api.user_by_login(target)
        if not user:
            print(f"[HATA] Hedef kullanıcı bulunamadı: {target} / {target_id_env}")
            return []

        results = []
        detail_lookups = 0
        max_detail_lookups = max(1, count)

        async for tweet in api.user_tweets(user.id, limit=count * 6):
            # Retweet değilse atla
            rt = getattr(tweet, 'retweetedTweet', None)
            if not rt:
                continue

            # Medya topla (orijinal tweet)
            media_urls = []
            t_media = getattr(rt, 'media', None)
            if not t_media or (
                len(getattr(t_media, 'photos', []) or []) == 0 and
                len(getattr(t_media, 'videos', []) or []) == 0 and
                len(getattr(t_media, 'animated', []) or []) == 0
            ):
                if detail_lookups < max_detail_lookups:
                    try:
                        detail = await api.tweet_details(rt.id, wait=TWSCRAPE_DETAIL_TIMEOUT)
                        detail_lookups += 1
                        if detail and getattr(detail, 'media', None):
                            t_media = detail.media
                    except Exception as de:
                        print(f"[UYARI] Orijinal tweet detay çekilemedi: {de}")

            if t_media:
                for photo in getattr(t_media, 'photos', []) or []:
                    url = getattr(photo, 'url', None)
                    if url:
                        media_urls.append(url)
                for video in getattr(t_media, 'videos', []) or []:
                    variants = getattr(video, 'variants', []) or []
                    if variants:
                        best = max(variants, key=lambda x: getattr(x, 'bitrate', 0))
                        vurl = getattr(best, 'url', None)
                        if vurl:
                            media_urls.append(vurl)

            tweet_data = {
                'id': str(getattr(rt, 'id', getattr(rt, 'id_str', ''))),
                'text': getattr(rt, 'rawContent', ''),
                'created_at': getattr(rt, 'date', None),
                'media_urls': media_urls,
                'url': getattr(rt, 'url', None)
            }

            results.append(tweet_data)
            if len(results) >= count:
                break

        # Eskiden yeniye sırala
        def _tw_key(td):
            ts = td.get('created_at') if isinstance(td, dict) else None
            tsv = 0
            try:
                if hasattr(ts, 'timestamp'):
                    tsv = int(ts.timestamp())
            except Exception:
                tsv = 0
            try:
                return (tsv, int(str(td.get('id', '0'))))
            except Exception:
                return (tsv, 0)

        results.sort(key=_tw_key)
        return results
    except Exception as e:
        print(f"[UYARI] @bf6_tr retweet'leri alınamadı (async): {e}")
        return []

def get_latest_bf6_retweets(count: int = 3):
    """twscrape ile TWITTER_SCREENNAME zaman akışından sadece @bf6_tr retweet'lerini getirir.
    Başarısız olursa sessizce boş liste döner. Mevcut pipeline ile aynı veri şeklini üretir.
    """
    target = os.getenv("SECONDARY_RETWEET_TARGET", "bf6_tr")
    try:
        # Rate limiting (aynı mekanizma)
        global LAST_REQUEST_TIME
        current_time = time.time()
        time_since_last_request = current_time - LAST_REQUEST_TIME
        if time_since_last_request < MIN_REQUEST_INTERVAL:
            wait_time = MIN_REQUEST_INTERVAL - time_since_last_request
            print(f"[+] (RT) Rate limiting: {int(wait_time)} saniye bekleniyor...")
            time.sleep(wait_time)
        LAST_REQUEST_TIME = time.time()

        # Async twscrape çağrısı
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tweets = loop.run_until_complete(_get_bf6_retweets_twscrape(target, count))
        finally:
            loop.close()
        return tweets or []
    except Exception as e:
        print(f"[UYARI] @bf6_tr retweet'leri alınamadı: {e}")
        return []

# Pnytter fallback fonksiyonu kaldırıldı - sadece TWSCRAPE kullanılacak

# RSS fallback fonksiyonu kaldırıldı - sadece TWSCRAPE kullanılacak

def get_media_urls_from_tweet_data(tweet_data):
    """ TWSCRAPE'den alınan tweet verisinden medya URL'lerini çıkar"""
    if not tweet_data or "media_urls" not in tweet_data:
        return []
    
    try:
        media_urls = tweet_data.get("media_urls", [])
        return media_urls
        
    except Exception:
        return []

# Nitter HTML fonksiyonları kaldırıldı - sadece TWSCRAPE kullanılacak

# Nitter instance yönetim fonksiyonları kaldırıldı - sadece TWSCRAPE kullanılacak

def _is_retweet_or_quote_by_id(tweet_id: str) -> bool:
    """Detail sorgusu ile RT/Quote olup olmadığını doğrula (senkron sarmalayıcı)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                api = await init_twscrape_api()
                try:
                    d = await asyncio.wait_for(api.tweet_details(int(tweet_id)), timeout=TWSCRAPE_DETAIL_TIMEOUT)
                except Exception:
                    return False
                if not d:
                    return False
                if getattr(d, 'inReplyToTweetId', None):
                    return True
                if getattr(d, 'retweetedTweet', None):
                    return True
                if getattr(d, 'quotedTweet', None) or getattr(d, 'isQuoted', False) or getattr(d, 'isQuote', False):
                    return True
                return False
            return bool(loop.run_until_complete(_run()))
        finally:
            loop.close()
    except Exception:
        return False

def process_specific_tweet(tweet_id: str) -> dict:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                api = await init_twscrape_api()
                try:
                    detail = await asyncio.wait_for(api.tweet_details(int(tweet_id)), timeout=TWSCRAPE_DETAIL_TIMEOUT)
                except Exception:
                    detail = None
                if not detail:
                    return {"processed": False, "reason": "detail_not_found"}
                if getattr(detail, 'inReplyToTweetId', None):
                    return {"processed": False, "reason": "is_reply"}
                if getattr(detail, 'retweetedTweet', None):
                    return {"processed": False, "reason": "is_retweet"}
                if getattr(detail, 'quotedTweet', None) or getattr(detail, 'isQuoted', False) or getattr(detail, 'isQuote', False):
                    return {"processed": False, "reason": "is_quote"}

                media_urls = []
                md = getattr(detail, 'media', None)
                if md:
                    photos = getattr(md, 'photos', []) or []
                    for p in photos:
                        u = getattr(p, 'url', None)
                        if u:
                            media_urls.append(u)
                    videos = getattr(md, 'videos', []) or []
                    for v in videos:
                        vars = getattr(v, 'variants', []) or []
                        if vars:
                            best = max(vars, key=lambda x: getattr(x, 'bitrate', 0))
                            u = getattr(best, 'url', None)
                            if u:
                                media_urls.append(u)
                    animated = getattr(md, 'animated', []) or []
                    for a in animated:
                        u = getattr(a, 'videoUrl', None)
                        if u:
                            media_urls.append(u)

                tweet_data = {
                    'id': str(getattr(detail, 'id', getattr(detail, 'id_str', ''))),
                    'text': getattr(detail, 'rawContent', ''),
                    'created_at': getattr(detail, 'date', None),
                    'media_urls': media_urls,
                    'url': getattr(detail, 'url', None),
                }

                text = tweet_data.get("text", "")
                cleaned_text = clean_tweet_text(text)
                try:
                    cd_days = _extract_countdown_days(text) or _extract_countdown_days(cleaned_text)
                except Exception:
                    cd_days = None
                if cd_days is not None and cd_days > 10:
                    return {"processed": False, "reason": "countdown_gt_10"}

                media_urls2 = get_media_urls_from_tweet_data(tweet_data)
                media_files = []
                image_urls = []
                video_urls = []
                for mu in media_urls2:
                    ul = str(mu).lower()
                    is_image = (
                        any(ext in ul for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']) or
                        'format=jpg' in ul or 'format=jpeg' in ul or 'format=png' in ul or 'format=webp' in ul or
                        'pbs.twimg.com/media' in ul
                    )
                    is_video = ('.mp4' in ul or 'format=mp4' in ul or 'video.twimg.com' in ul)
                    if is_image:
                        image_urls.append(mu)
                    elif is_video:
                        video_urls.append(mu)

                translated = translate_text(cleaned_text, has_video=bool(video_urls))
                if not translated:
                    return {"processed": False, "reason": "translation_failed"}

                if len(image_urls) > 1:
                    downloaded_images = download_multiple_images(image_urls, tweet_id)
                    media_files.extend(downloaded_images)
                elif len(image_urls) == 1:
                    media_url = image_urls[0]
                    ext = os.path.splitext(media_url)[1].split("?")[0] or ".jpg"
                    filename = f"temp_image_{tweet_id}_0{ext}"
                    path = download_media(media_url, filename)
                    if path:
                        media_files.append(path)

                if video_urls:
                    filename = f"temp_video_{tweet_id}_0.mp4"
                    path = download_best_video_for_tweet(tweet_id, filename)
                    if path:
                        dur = get_video_duration_seconds(path)
                        if dur is not None and dur > REDDIT_MAX_VIDEO_SECONDS:
                            try:
                                if os.path.exists(path):
                                    os.remove(path)
                            except Exception:
                                pass
                            for fpath in media_files:
                                try:
                                    if os.path.exists(fpath):
                                        os.remove(fpath)
                                except Exception:
                                    pass
                            return {"processed": False, "reason": "video_too_long"}
                        converted = f"converted_{filename}"
                        converted_path = convert_video_to_reddit_format(path, converted)
                        if converted_path:
                            media_files.append(converted_path)
                        if os.path.exists(path):
                            os.remove(path)

                original_text = tweet_data.get("text", "")
                has_media_in_original = any(ind in original_text for ind in ['pic.twitter.com', 'video.twitter.com', 'pbs.twimg.com'])
                if has_media_in_original and len(media_files) == 0:
                    for fpath in media_files:
                        try:
                            if os.path.exists(fpath):
                                os.remove(fpath)
                        except Exception:
                            pass
                    return {"processed": False, "reason": "media_expected_but_missing"}

                candidates = [
                    (translated or "").strip(),
                    (cleaned_text or "").strip(),
                    (text or "").strip(),
                ]
                chosen_text = next((c for c in candidates if c), "")
                if not chosen_text:
                    chosen_text = f"@{TWITTER_SCREENNAME} paylaşımı - {tweet_id}"
                title_to_use, remainder_to_post = smart_split_title(chosen_text, 300)
                ok = submit_post(title_to_use, media_files, text, remainder_text=remainder_to_post)
                if ok:
                    return {"processed": True, "tweet_id": str(tweet_id), "title": title_to_use}
                return {"processed": False, "reason": "submit_failed"}

            result = loop.run_until_complete(_run())
            return result
        finally:
            loop.close()
    except Exception as e:
        return {"processed": False, "reason": f"exception:{e}"}

# Manifest consumption support (USE_EXTERNAL_QUEUE=true)
def process_external_due_items(posted_tweet_ids=None):
    if not USE_EXTERNAL_QUEUE:
        return

    manifest = None
    if MANIFEST_URL:
        try:
            r = requests.get(MANIFEST_URL, timeout=15)
            if r.status_code == 200:
                manifest = r.json()
            else:
                print(f"[UYARI] Manifest URL hata kodu: {r.status_code} | MANIFEST_URL='{MANIFEST_URL}'")
                return
        except Exception as e:
            print(f"[UYARI] Manifest indirme hatası: {e} | MANIFEST_URL='{MANIFEST_URL}'")
            return
    else:
        try:
            with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception as e:
            print(f"[UYARI] Manifest dosyası okunamadı: {e} | MANIFEST_PATH='{MANIFEST_PATH}'")
            return

    if not isinstance(manifest, dict) or 'items' not in manifest:
        print("[UYARI] Manifest biçimi geçersiz (dict 'items' beklenirdi)")
        return

    now = time.time()
    items = manifest.get('items') or []
    if not isinstance(items, list):
        print("[UYARI] Manifest 'items' listesi geçersiz")
        return

    # Load posted IDs to avoid duplicates
    posted_ids = set(posted_tweet_ids) if posted_tweet_ids is not None else set(load_posted_tweet_ids())

    def _parse_iso8601_to_epoch(s: str) -> float | None:
        try:
            if not s:
                return None
            t = s.strip().replace('Z', '+00:00')
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(t).astimezone(timezone.utc)
            return dt.timestamp()
        except Exception:
            return None

    # Select due items
    due: list[dict] = []
    upcoming: list[tuple[float, dict]] = []
    if MANIFEST_TEST_FIRST_ITEM:
        # Testing mode: process the first item with media that hasn't been posted yet
        try:
            for it in items:
                iid = str(it.get('id', '')).strip()
                if not iid or iid in posted_ids:
                    continue
                media = it.get('media') or []
                if isinstance(media, list) and len(media) > 0:
                    due.append(it)
                    break
        except Exception:
            pass
    else:
        for it in items:
            try:
                iid = str(it.get('id', '')).strip()
                if not iid:
                    continue
                if iid in posted_ids:
                    continue
                sched = _parse_iso8601_to_epoch(str(it.get('scheduled_at', '')).strip())
                if sched is None:
                    continue
                if sched <= now:
                    due.append(it)
                else:
                    upcoming.append((sched, it))
            except Exception:
                continue

    # Log summary so it's clear why nothing posted
    try:
        total = len(items)
        due_count = len(due)
        next_info = None
        if upcoming:
            upcoming.sort(key=lambda x: x[0])
            from datetime import datetime, timezone
            next_ts = upcoming[0][0]
            next_info = datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        print(f"[INFO] Manifest: total_items={total}, due_now={due_count}, next_due_at={next_info}")
    except Exception:
        pass

    seen_ids = set()
    seen_titles = set()
    posted_in_cycle = 0
    for it in due:
        if posted_in_cycle >= MANIFEST_MAX_POSTS_PER_CYCLE:
            break
        iid = str(it.get('id', '')).strip()
        title = (it.get('title') or '').strip()
        body = (it.get('body') or '').strip()
        media = it.get('media') or []
        if not isinstance(media, list) or len(media) == 0:
            continue
        if iid in seen_ids:
            continue
        if title and title in seen_titles:
            continue
        # Prioritize video: if any video exists, submit only the first video; otherwise submit images
        videos = [m for m in media if (m.get('type', '').lower() == 'video' and m.get('url'))]
        images = [m for m in media if (m.get('type', '').lower() == 'image' and m.get('url'))]
        chosen_media = []
        if videos:
            chosen_media = [videos[0]]
            print(f"[MANIFEST] Video önceliklendirildi (1 video seçildi)")
        elif images:
            chosen_media = images
            print(f"[MANIFEST] Resim galerisi seçildi ({len(images)} resim)")
        else:
            print("[MANIFEST] Geçerli medya bulunamadı (ne video ne resim)")
            continue

        media_files: list[str] = []
        try:
            # Download media
            for idx, m in enumerate(chosen_media):
                try:
                    mtype = (m.get('type') or '').lower()
                    url = m.get('url')
                    if not url:
                        continue
                    ext = os.path.splitext(url)[1].split('?')[0] or ('.mp4' if mtype == 'video' else '.jpg')
                    fname = f"manifest_{iid}_{idx}{ext}"
                    p = download_media(url, fname)
                    if p:
                        media_files.append(p)
                except Exception:
                    continue

            if media_files:
                print(f"[MANIFEST] İndirilen medya dosyaları: {', '.join(os.path.basename(x) for x in media_files)}")
            else:
                print("[MANIFEST] Medya indirilemedi, item atlandı")
                continue

            # Submit
            if not title:
                title = f"Manifest Item {iid}"
            ok = submit_post(title, media_files, original_tweet_text=body, remainder_text="")
            if ok:
                print(f"[+] Manifest öğesi gönderildi: {iid}")
                try:
                    save_posted_tweet_id(iid)
                except Exception:
                    pass
                seen_ids.add(iid)
                if title:
                    seen_titles.add(title)
                posted_in_cycle += 1
            else:
                print(f"[UYARI] Manifest öğesi gönderilemedi: {iid}")
        except Exception as e:
            print(f"[UYARI] Manifest öğesi işlenirken hata ({iid}): {e}")
        finally:
            # Clean up downloaded files
            for fp in media_files:
                try:
                    if os.path.exists(fp):
                        os.remove(fp)
                except Exception:
                    pass

# --- Scheduled weekly "Oyuncu Arama" post helper (stateless) ---
def _create_and_pin_weekly_post_if_due() -> None:
    """Scheduled weekly megathread creator.
    Primary schedule: every Friday (weekday=4) at/after configured hour.
    Fallback schedule: specified days-of-month in `SCHEDULED_PIN_DAYS` if WEEKDAY invalid.
    Uses PRAW and requires moderator permissions on the subreddit.
    """
    try:
        # Global toggle
        if not SCHEDULED_PIN_ENABLED:
            return
        lt = time.localtime()
        day = lt.tm_mday
        wday = lt.tm_wday  # 0=Mon .. 6=Sun
        hour = lt.tm_hour

        run_today = False
        # Prefer weekday schedule if valid
        if 0 <= SCHEDULED_PIN_WEEKDAY <= 6:
            run_today = (wday == SCHEDULED_PIN_WEEKDAY) and (hour >= SCHEDULED_PIN_HOUR)
        else:
            # Fallback to day-of-month list if provided
            if SCHEDULED_PIN_DAYS:
                run_today = (day in SCHEDULED_PIN_DAYS) and (hour >= SCHEDULED_PIN_HOUR)

        if not run_today:
            return
        today_key = time.strftime("%Y-%m-%d", lt)

        # Build title and body
        tarih = time.strftime("%d.%m.%Y", lt)
        title = f"{SCHEDULED_PIN_TITLE_PREFIX}{tarih})"
        body = (
            "**Hoş geldiniz!**\n\n"
            "Bu başlık, takım/oyuncu bulmanızı kolaylaştırmak amacıyla oluşturulmuştur. Eğer birlikte oyun oynayabileceğiniz yeni kişiler arıyorsanız doğru yerdesiniz! Aşağıda belirtildiği şekilde yorum yaparak takım arkadaşı arayabilirsiniz. Böylece benzer oyunlara ve tercihlere sahip oyuncular kolayca bir araya gelebilir.\n\n"
            "**Lütfen yorumlarınızda şunları belirtmeyi unutmayın:**\n\n"
            "* Oyun platformunuz (PC, PlayStation, Xbox vb.)\n"
            "* Oyun içi kullanıcı adınız\n"
            "* Mikrofonlu/suz bilgisi\n"
            "* Genellikle oynadığınız veya oynayacağınız görev birimi (assault, medic, recon vb.)\n\n"
            "Bu bilgiler sayesinde, benzer oyun ve oyun tarzlarına sahip kişilerle daha kolay iletişim kurabilirsiniz.\n\n"
            "**Yorumların sıralanması:**\n\n"
            "Yorumlar sistem tarafından otomatik olarak en yeni yorumdan en eski yoruma doğru sıralanmaktadır. Böylece en güncel oyunculara ve taleplere kolayca ulaşabilirsiniz.\n\n"
            "Her seviyeden oyuncuya açıktır, saygılı ve destekleyici bir ortam yaratmayı amaçlıyoruz. Keyifli oyunlar!"
        )

        # Stateless dedupe: scan recent posts for today's weekly thread
        sr = reddit.subreddit(SUBREDDIT)
        try:
            for s in sr.new(limit=30):
                try:
                    author_name = getattr(s.author, 'name', '') or ''
                except Exception:
                    author_name = ''
                s_title = getattr(s, 'title', '') or ''
                try:
                    created_utc = int(getattr(s, 'created_utc', 0) or 0)
                except Exception:
                    created_utc = 0
                s_local = time.localtime(created_utc) if created_utc else None
                s_key = time.strftime("%Y-%m-%d", s_local) if s_local else ''
                if (
                    author_name.lower() == (REDDIT_USERNAME or '').lower()
                    and s_title.startswith(SCHEDULED_PIN_TITLE_PREFIX)
                    and s_key == today_key
                ):
                    print(f"[INFO] Bugünün haftalık başlığı zaten mevcut: https://reddit.com{s.permalink}")
                    return
        except Exception as scan_e:
            print(f"[UYARI] Mevcut haftalık gönderiler taranamadı: {scan_e}")

        print("[+] Haftalık oyuncu arama gönderisi oluşturuluyor ve sabitleniyor...")
        submission = sr.submit(title=title, selftext=body, send_replies=False, resubmit=False)
        if submission:
            try:
                # Pin to top (slot 1) and set suggested sort to 'new'
                submission.mod.sticky(state=True, bottom=False)
                try:
                    submission.mod.suggested_sort("new")
                except Exception as se:
                    print(f"[UYARI] suggested_sort ayarlanamadı: {se}")
                print(f"[+] Haftalık gönderi oluşturuldu ve sabitlendi: https://reddit.com{submission.permalink}")

                # Unsticky older megathreads so only the newest stays pinned
                try:
                    for slot in (1, 2):
                        try:
                            stickied = sr.sticky(number=slot)
                        except Exception:
                            stickied = None
                        if not stickied:
                            continue
                        try:
                            st_author = getattr(stickied.author, 'name', '') or ''
                        except Exception:
                            st_author = ''
                        st_title = getattr(stickied, 'title', '') or ''
                        if (
                            stickied.id != submission.id and
                            st_author.lower() == (REDDIT_USERNAME or '').lower() and
                            st_title.startswith(SCHEDULED_PIN_TITLE_PREFIX)
                        ):
                            try:
                                stickied.mod.sticky(state=False)
                                print(f"[+] Eski haftalık başlık unsticky yapıldı: https://reddit.com{stickied.permalink}")
                            except Exception as ue:
                                print(f"[UYARI] Unsticky başarısız: {ue}")
                except Exception as sweep_e:
                    print(f"[UYARI] Sticky temizleme sırasında hata: {sweep_e}")
                # Extra sweep: scan recent posts and unsticky any lingering older stickied megathreads
                try:
                    for s in sr.new(limit=100):
                        try:
                            if getattr(s, 'id', None) == submission.id:
                                continue
                            if not getattr(s, 'stickied', False):
                                continue
                            author_name = getattr(s.author, 'name', '') or ''
                            s_title = getattr(s, 'title', '') or ''
                            if (
                                author_name.lower() == (REDDIT_USERNAME or '').lower() and
                                s_title.startswith(SCHEDULED_PIN_TITLE_PREFIX)
                            ):
                                try:
                                    s.mod.sticky(state=False)
                                    print(f"[+] Eski stickied gönderi unsticky yapıldı: https://reddit.com{s.permalink}")
                                except Exception as ue2:
                                    print(f"[UYARI] Unsticky (scan) başarısız: {ue2}")
                        except Exception:
                            # Ignore per-item errors during sweep
                            continue
                except Exception as scan_uns_e:
                    print(f"[UYARI] Ek sticky tarama/temizleme hatası: {scan_uns_e}")
            except Exception as me:
                print(f"[UYARI] Gönderi sabitleme/moderasyon işlemi başarısız: {me}")
        else:
            print("[UYARI] Haftalık gönderi oluşturulamadı (PRAW submit falsy)")
    except Exception as e:
        print(f"[UYARI] Haftalık gönderi oluşturma hatası: {e}")

# Manifest refresh
def refresh_manifest():
    if MANIFEST_URL:
        try:
            response = requests.get(MANIFEST_URL, timeout=10)
            if response.status_code == 200:
                with open(MANIFEST_PATH, 'w') as f:
                    json.dump(response.json(), f)
                print(f"[+] Manifest güncellendi: {MANIFEST_PATH}")
            else:
                print(f"[UYARI] Manifest URL'den alınamadı: {response.status_code}")
        except Exception as e:
            print(f"[UYARI] Manifest URL hatası: {e}")

def get_next_due_epoch() -> float | None:
    manifest = None
    try:
        if MANIFEST_URL:
            r = requests.get(MANIFEST_URL, timeout=10)
            if r.status_code == 200:
                manifest = r.json()
            else:
                return None
        else:
            with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
    except Exception:
        return None
    if not isinstance(manifest, dict):
        return None
    items = manifest.get('items') or []
    if not isinstance(items, list) or not items:
        return None
    # Find earliest future scheduled_at
    now = time.time()
    next_ts = None
    for it in items:
        try:
            s = str(it.get('scheduled_at', '')).strip()
            if not s:
                continue
            t = s.replace('Z', '+00:00')
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(t).astimezone(timezone.utc).timestamp()
            if ts > now and (next_ts is None or ts < next_ts):
                next_ts = ts
        except Exception:
            continue
    return next_ts

# Main loop
def main_loop():
    while True:
        try:
            process_external_due_items()
            _create_and_pin_weekly_post_if_due()
            refresh_manifest()
            # Dynamic sleep: wait until next scheduled_at if available
            now = time.time()
            next_ts = get_next_due_epoch()
            if next_ts and next_ts > now:
                sleep_sec = int(min(1800, max(30, next_ts - now)))
                nxt_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(next_ts))
                print(f"\n[+] Sonraki kontrol: {nxt_str}Z (dinamik {sleep_sec}s)")
                print("⏳ Bekleniyor...")
                time.sleep(sleep_sec)
            else:
                # Fallback periodic poll
                print(f"\n[+] Sonraki kontrol (periyodik): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now + MANIFEST_REFRESH_SECONDS))}Z")
                print("⏳ Bekleniyor...")
                time.sleep(MANIFEST_REFRESH_SECONDS)
        except Exception as e:
            print(f"[UYARI] Main loop hatası: {e}")

# --- Web Service (FastAPI) ---
# Lazy import - FastAPI sadece ihtiyaç duyulduğunda import edilecek

# Global değişkenler
_worker_started = False
_worker_lock = None
app = None

def get_instance_health_status() -> bool:
    """Basit sağlık durumu: arka plan işçisi başladı mı?"""
    try:
        return bool(_worker_started)
    except Exception:
        # Varsayılan: servis ayakta kabul et
        return True

def _init_fastapi():
    """ FastAPI lazy initialization"""
    global app, _worker_lock
    if app is None:
        if LOCAL_ONLY:
            # Lokal modda web servis kurma
            return None
        # Lazy import
        try:
            from fastapi import FastAPI, Request
            from fastapi.responses import PlainTextResponse
            import threading
        except ImportError:
            raise RuntimeError("FastAPI veya threading mevcut değil")
        
        app = FastAPI(title="X-to-Reddit Bot")
        _worker_lock = threading.Lock()
        
        # Route'ları tanımla
        @app.api_route("/", methods=["GET", "HEAD"], response_class=PlainTextResponse)
        def root(request: Request):
            if request.method == "HEAD":
                return PlainTextResponse("", status_code=200)
            return "OK"

        @app.api_route("/healthz", methods=["GET", "HEAD"], response_class=PlainTextResponse)
        def healthz(request: Request):
            try:
                if request.method == "HEAD":
                    return PlainTextResponse("", status_code=200)
                status = get_instance_health_status()
                return "healthy" if status else "ok"
            except Exception:
                return PlainTextResponse("ok", status_code=200)

        @app.api_route("/ping", methods=["GET", "HEAD"])
        async def ping(request: Request):
            # Basit canlılık kontrolü
            if request.method == "HEAD":
                return PlainTextResponse("", status_code=200)
            return {"status": "alive"}

        @app.api_route("/process/{tweet_id}", methods=["GET", "POST"])
        async def process_tweet_endpoint(tweet_id: str):
            try:
                # Senkron yardımcı fonksiyonu çağır
                res = process_specific_tweet(tweet_id)
                return res
            except Exception as e:
                return {"processed": False, "reason": f"exception:{e}"}

        @app.on_event("startup")
        def start_background_worker():
            global _worker_started
            with _worker_lock:
                if _worker_started:
                    return
                # DB preflight: if DB is mandatory, ensure we can connect and create table
                if USE_DB_FOR_POSTED_IDS and FAIL_IF_DB_UNAVAILABLE:
                    try:
                        _ensure_posted_ids_table()
                    except Exception as e:
                        # Fail fast: exit the process so Render restarts with proper env
                        try:
                            sys.exit(1)
                        except SystemExit:
                            raise
                        except Exception:
                            # As a fallback, re-raise to stop background worker
                            raise
                def _run():
                    # main_loop zaten kendi içinde sonsuz döngüye sahip
                    try:
                        main_loop()
                    except Exception:
                        pass  # Logging azaltıldı
                t = threading.Thread(target=_run, name="bot-worker", daemon=True)
                t.start()
                _worker_started = True
    
    return app

# Expose ASGI app for 'uvicorn bot:app' imports (Render)
app = None if LOCAL_ONLY else _init_fastapi()

# Route tanımları _init_fastapi() fonksiyonuna taşındı

# Nitter multi-instance fonksiyonu kaldırıldı - sadece TWSCRAPE kullanılacak

# Gallery-dl fonksiyonu kaldırıldı - sadece TWSCRAPE kullanılacak

def translate_text(text, has_video: bool = False):
    """ Gemini 2.5 Flash ile İngilizce -> Türkçe çeviri (memory optimized)
    Çıkış: Sadece ham çeviri (ek açıklama, tırnak, etiket vs. yok).
    Özel terimleri ÇEVİRME: battlefield, free pass, battle pass.
    has_video: Kaynak tweet'te video varsa True (ör: 'reload' -> 'Şarjör').
    """
    try:
        if not text or not text.strip():
            return None
        
        # Lazy import - sadece ihtiyaç duyulduğunda import et
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            return None
        
        # Normalize input to NFC first
        original_text = _nfc(text)
        # If text is shouty ALL CAPS, create a de-shouted version for translation
        input_for_translation = _deshout_en_sentence_case(original_text) if _is_all_caps_like(original_text) else original_text

        # Cache lookup (normalized key)
        key = input_for_translation.strip()
        with TRANSLATE_CACHE_LOCK:
            cached = TRANSLATE_CACHE.get(key)
            if cached is not None:
                # touch LRU order if available
                try:
                    TRANSLATE_CACHE.move_to_end(key)
                except Exception:
                    pass
                return cached

        # Gemini client - lazy initialization
        client = None
        try:
            client = genai.Client()
        except Exception:
            return None
        # Modeller: primary ve fallback env ile ayarlanabilir
        model_primary = os.getenv("GEMINI_MODEL_PRIMARY", "gemini-2.5-flash-lite").strip()
        model_fallback = os.getenv("GEMINI_MODEL_FALLBACK", "gemini-2.5-flash").strip()

        # Talimat: sadece ham çeviri, belirli terimler çevrilmez.
        # Bağlam satırı: video var/yok bilgisi ile özel kurallar uygulanır.
        prompt = (
            "Translate the text from English (source: en) to Turkish (target: tr). Output ONLY the translation with no extra words, "
            "no quotes, no labels. Do NOT translate these terms and keep their original casing: "
            "Battlefield, Free Pass, Battle Pass, Operation Firestorm, Easter Egg, Plus, Trickshot, Support, Recon, Assault, Engineer.\n"
            "Preserve the original tweet's capitalization EXACTLY for all words where possible; do not change upper/lower casing from the source text, "
            "but apply strict capitalization preservation ONLY to protected terms and proper nouns; Turkish words should use natural Turkish casing.\n"
            "Translate ALL parts of the text into Turkish EXCEPT the protected terms listed above. Do NOT leave any sentence or common word in English.\n"
            "If the input includes any mentions like @nickname or patterns like 'via @nickname', exclude them from the output entirely.\n"
            "If the content appears to be a short gameplay/clip highlight rather than a news/article, compress it into ONE coherent Turkish sentence (no bullet points, no multiple sentences).\n"
            "Remove any first-person opinions or subjective phrases (e.g., 'I think', 'IMO', 'bence', 'bana göre'); keep only neutral, factual content.\n"
            "Before finalizing, re-read your Turkish output and ensure it is coherent and faithful: do NOT invent numbers, durations (e.g., '3-5 gün'), hedging words (e.g., 'sanki', 'gibi', 'muhtemelen') unless they EXIST in the English. Remove any such additions. Do NOT add or change meaning.\n"
            "Do not translate 'Campaign' in a video game context as 'Kampanya'; prefer 'Hikaye' (or 'Hikaye modu' if fits better). Translate 'Campaign Early Access' as 'Hikaye Erken Erişimi'.\n"
            f"Context: HAS_VIDEO={'true' if has_video else 'false'} — If HAS_VIDEO is true AND the English contains the word 'reload', translate 'reload' specifically as 'Şarjör' (capitalize S). Otherwise, translate naturally (do NOT use 'Şarjör').\n"
            "Before finalizing, ensure the Turkish output is coherent and natural; do NOT produce two unrelated sentences or add stray quoted fragments. If any part seems odd, fix it for clarity while staying faithful to the source.\n\n"
            "Important: When translating phrases like 'your [THING] rating', do NOT add Turkish possessive suffixes to game/brand names. Prefer the structure '[NAME] için ... derecelendirmeniz' instead of '[NAME]'nızın ...'.\n"
            "Example: 'What is your FINAL Rating of the Battlefield 6 Beta? (1-10)' -> 'Battlefield 6 Beta için FINAL derecelendirmeniz nedir? (1-10)'.\n\n"
            "Idioms: Translate 'can't wait' / 'cannot wait' / 'can NOT wait' as positive excitement -> 'sabırsızlanıyorum' (NOT 'sabırsızlanamam'). If the English uses emphasis (e.g., NOT in caps), you may emphasize the Turkish verb (e.g., SABIRSIZLANIYORUM) but do not change the meaning to negative.\n"
            "Meme pattern '... be like': Translate patterns such as 'waiting BF6 be like...' as 'BF6’yı beklemek böyle bir şey...' or '[X] böyle bir şey...' Do NOT produce literal 'bekliyorum sanki' or similar unnatural phrasing.\n"
            "Consistency: Never introduce or switch to a different game/series/version that is not in the source. If the source mentions 'Battlefield 2042', do not output 'Battlefield 6', and vice versa. Keep titles and versions consistent with the input.\n"
            "Natural wording: Translate generic English gaming terms to proper Turkish instead of mixing languages (e.g., translate 'cosmetics' as 'kozmetikler' when not a protected proper noun; avoid forms like 'Cosmetics'ler'). Keep protected terms listed above in English as instructed.\n"
            "Use correct Turkish diacritics (ç, ğ, ı, İ, ö, ş, ü) and keep Unicode in NFC form. Preserve basic punctuation and line breaks.\n\n"
            "Text:\n" + input_for_translation.strip()
        )

        def _translate_with(model_name: str):
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                ),
            )
            out_local = _nfc((resp.text or "").strip())
            if out_local and out_local != text.strip():
                # Cache write-through + basit LRU tahliyesi
                try:
                    with TRANSLATE_CACHE_LOCK:
                        TRANSLATE_CACHE[key] = out_local
                        try:
                            TRANSLATE_CACHE.move_to_end(key)
                        except Exception:
                            pass
                        try:
                            while len(TRANSLATE_CACHE) > TRANSLATE_CACHE_MAX:
                                TRANSLATE_CACHE.popitem(last=False)
                        except Exception:
                            pass
                except Exception:
                    pass
                return out_local
            return None

        # Önce primary modeli dene
        out = None
        try:
            out = _translate_with(model_primary)
        except Exception as e:
            print(f"[UYARI] Gemini model hata ({model_primary}): {e}")

        # Başarısızsa fallback modeli dene
        if not out and model_fallback and model_fallback != model_primary:
            try:
                out = _translate_with(model_fallback)
            except Exception as e:
                print(f"[UYARI] Gemini model hata ({model_fallback}): {e}")

        if out:
            # If original was ALL CAPS, avoid re-uppercasing Turkish output blindly; keep natural casing
            return out
        print("[UYARI] Çeviri boş döndü veya orijinal ile aynı")
        return None
    except Exception as e:
        print(f"[UYARI] Gemini çeviri hatası: {e}")
        return None

# (Şaka/"joke" notu ile ilgili tüm kodlar kaldırıldı)

# AI-powered flair selection system
FLAIR_OPTIONS = {
    "Haberler": "a3c0f742-22de-11f0-9e24-7a8b08eb260a",
    "Klip": "b6d04ac2-22de-11f0-9536-c6a33f70974b",
    "Tartışma": "c22e9cfc-22de-11f0-950d-4ee5c0d1016f",
    "Soru": "ccbc6fb4-22de-11f0-b443-da5b1d3016fa",
    "İnceleme": "e52aa2a0-22de-11f0-abed-aa5bfc354624",
    "Kampanya": "26a6deda-68ab-11f0-8584-6a05febc585d",
    "Arkaplan": "33ea1cfa-69c4-11f0-8376-9a5b50ce03e6",
    "Sızıntı": "351fe58c-6be0-11f0-bcb4-9e6d710db689"
}

# Reverse lookup for flair name by hardcoded ID (to recover name if IDs drift)
_FLAIR_NAME_BY_ID = {vid: k for k, vid in FLAIR_OPTIONS.items()}

# Cache subreddit flair templates to avoid rate limit
_FLAIR_TEMPLATE_CACHE: dict[str, list[dict]] = {}

def _fetch_link_flair_templates(subreddit_name: str) -> list[dict]:
    """Fetch available link flair templates for a subreddit using PRAW.
    Returns a list of dicts with keys like 'id' and 'text'. Caches results per process.
    """
    try:
        if subreddit_name in _FLAIR_TEMPLATE_CACHE and _FLAIR_TEMPLATE_CACHE[subreddit_name]:
            return _FLAIR_TEMPLATE_CACHE[subreddit_name]
        sr = reddit.subreddit(subreddit_name)
        # PRAW: SubredditFlair link templates
        # Some versions expose via sr.flair.link_templates
        templates = []
        try:
            templates = list(getattr(sr.flair, 'link_templates', []) or [])
        except Exception:
            pass
        # Fallback: sr.flair.templates may include both; filter link flairs if present
        if not templates:
            try:
                templates = list(getattr(sr.flair, 'templates', []) or [])
            except Exception:
                templates = []
        # Normalize
        norm = []
        for t in templates:
            # PRAW returns objects or dicts depending on version
            tid = getattr(t, 'id', None) if not isinstance(t, dict) else t.get('id')
            text = getattr(t, 'text', None) if not isinstance(t, dict) else t.get('text')
            if tid and text is not None:
                norm.append({'id': str(tid), 'text': str(text)})
        _FLAIR_TEMPLATE_CACHE[subreddit_name] = norm
        print(f"[INFO] r/{subreddit_name} mevcut link flair'leri: {[n['text']+':'+n['id'] for n in norm]}")
        return norm
    except Exception as e:
        print(f"[UYARI] Flair template'ları alınamadı (r/{subreddit_name}): {e}")
        return []

def _resolve_flair_id_for_subreddit(subreddit_name: str, flair_id: str | None, flair_name_guess: str | None) -> str | None:
    """Ensure flair_id exists on subreddit; if not, try to find by flair text.
    Returns a valid flair_id or None if not resolvable.
    """
    try:
        templates = _fetch_link_flair_templates(subreddit_name)
        if not templates:
            return None
        ids = {t['id'] for t in templates}
        if flair_id and str(flair_id) in ids:
            return str(flair_id)
        # Try by name guess (case-insensitive)
        if flair_name_guess:
            fl = flair_name_guess.strip().lower()
            # Prefer exact text match
            for t in templates:
                if t['text'].strip().lower() == fl:
                    return t['id']
            # Then substring match
            for t in templates:
                tt = t['text'].strip().lower()
                if fl in tt or tt in fl:
                    return t['id']
        # If we had an ID not present, try inferring name from our reverse map
        if flair_id and flair_id in _FLAIR_NAME_BY_ID:
            inferred = _FLAIR_NAME_BY_ID[flair_id].strip().lower()
            for t in templates:
                if t['text'].strip().lower() == inferred:
                    return t['id']
        return None
    except Exception as e:
        print(f"[UYARI] Flair ID çözümlenemedi: {e}")
        return None

def select_flair_with_ai(title, original_tweet_text="", has_video: bool = False):
    """AI ile otomatik flair seçimi"""
    print("[+] AI ile flair seçimi başlatılıyor...")
    print(f"[DEBUG] Başlık: {title}")
    print(f"[DEBUG] Orijinal tweet: {original_tweet_text[:100]}..." if original_tweet_text else "[DEBUG] Orijinal tweet yok")
    print(f"[DEBUG] Video var mı: {'Evet' if has_video else 'Hayır'}")
    
    # Önce basit kural tabanlı flair seçimi deneyelim
    title_lower = title.lower()
    tweet_lower = original_tweet_text.lower() if original_tweet_text else ""
    combined_text = f"{title_lower} {tweet_lower}"
    
    print(f"[DEBUG] Analiz edilen metin: {combined_text[:200]}...")
    
    # Kural tabanlı flair seçimi
    if any(word in combined_text for word in ["klip", "gameplay"]):
        selected_flair = "Klip"
    elif any(word in combined_text for word in ["leak", "sızıntı", "rumor", "söylenti"]):
        selected_flair = "Sızıntı"
    elif any(word in combined_text for word in ["campaign", "kampanya", "single player"]):
        selected_flair = "Kampanya"
    elif any(word in combined_text for word in ["review", "inceleme", "değerlendirme"]):
        selected_flair = "İnceleme"
    elif any(word in combined_text for word in ["question", "soru", "help", "yardım"]):
        selected_flair = "Soru"
    elif any(word in combined_text for word in ["discussion", "tartışma", "opinion", "görüş"]):
        selected_flair = "Tartışma"
    elif any(word in combined_text for word in ["arkaplan", "background"]):
        selected_flair = "Arkaplan"
    else:
        selected_flair = "Haberler"  # Varsayılan
    
    selected_flair_id = FLAIR_OPTIONS[selected_flair]
    print(f"[+] Kural tabanlı flair seçimi: {selected_flair} (ID: {selected_flair_id})")
    
    # OpenAI API'yi dene (opsiyonel)
    try:
        # API key kontrolü
        ai_api_key = os.getenv("OPENAI_API_KEY")
        if not ai_api_key:
            print("[!] OPENAI_API_KEY bulunamadı, Gemini ile deneniyor")
            # Gemini istemcisi ve model
            gclient = genai.Client()
            g_model_primary = os.getenv("GEMINI_MODEL_PRIMARY", "gemini-2.5-flash-lite").strip()
            g_model_fallback = os.getenv("GEMINI_MODEL_FALLBACK", "gemini-2.5-flash").strip()

            g_prompt = (
                "Aşağıdaki içeriği analiz et ve en uygun Reddit flair'ini seç. Sadece aşağıdaki seçeneklerden BİRİNİ aynen döndür (başka hiçbir şey yazma):\n"
                "Haberler | Klip | Tartışma | Soru | İnceleme | Kampanya | Arkaplan | Sızıntı\n\n"
                "Kural: Eğer video VAR ve metin haber/duyuru gibi değilse 'Klip' seçeneğine öncelik ver. Haber duyurusu ise 'Haberler' uygundur.\n\n"
                f"Başlık: {title}\n"
                f"Video: {'Evet' if has_video else 'Hayır'}\n"
                + (f"Orijinal Tweet: {original_tweet_text}\n" if original_tweet_text else "") +
                "Yalnızca seçimi döndür."
            )

            def _ask_gemini(model_name: str) -> str:
                resp = gclient.models.generate_content(
                    model=model_name,
                    contents=g_prompt,
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(thinking_budget=0)
                    ),
                )
                return (getattr(resp, 'text', '') or '').strip()

            ai_suggestion = ""
            try:
                try:
                    ai_suggestion = _ask_gemini(g_model_primary)
                except Exception as ge1:
                    try:
                        ai_suggestion = _ask_gemini(g_model_fallback)
                    except Exception as ge2:
                        ai_suggestion = ""
                        print(f"[UYARI] Gemini flair (primary) hata: {ge1}")
                        print(f"[UYARI] Gemini flair (fallback) hata: {ge2}")
            except Exception as e:
                print(f"[UYARI] Gemini hata: {e}")
                return selected_flair_id

            if ai_suggestion:
                ai_clean = ai_suggestion.replace(".", "").replace(":", "").strip()
                # Tam eşleşme veya içerme ile eşleştir
                for flair_name, flair_id in FLAIR_OPTIONS.items():
                    if ai_clean.lower() == flair_name.lower() or flair_name.lower() in ai_clean.lower() or ai_clean.lower() in flair_name.lower():
                        print(f"[+] Gemini seçilen flair: {flair_name} (ID: {flair_id})")
                        return flair_id
                print(f"[!] Gemini önerisi eşleşmedi ({ai_clean}), kural tabanlı seçim kullanılıyor: {selected_flair}")
                return selected_flair_id
            else:
                print("[!] Gemini sonuç üretmedi, kural tabanlı seçim kullanılıyor")
                return selected_flair_id
            
        if ai_api_key:
            # OpenAI API için prompt hazırla
            content_to_analyze = f"Başlık: {title}\nVideo: {'Evet' if has_video else 'Hayır'}"
            if original_tweet_text:
                content_to_analyze += f"\nOrijinal Tweet: {original_tweet_text}"
            
            prompt = f"""Aşağıdaki Battlefield 6 ile ilgili içeriği analiz et ve en uygun flair'i seç.

Kurallar:
- Eğer video VAR ve metin haber/duyuru gibi değilse 'Klip' seçeneğine öncelik ver.
- Haber/duyuru ise 'Haberler' uygundur.

İçerik:
{content_to_analyze}

Sadece şu seçeneklerden birini döndür: Haberler, Klip, Tartışma, Soru, İnceleme, Kampanya, Arkaplan, Sızıntı
Sadece flair adını yaz (örnek: Haberler). Başka bir şey yazma."""
            
            # OpenAI API çağrısı
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": "gpt-4o-mini",  # Daha ekonomik model
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 50,
                "temperature": 0.1
            }
            headers = {
                "Authorization": f"Bearer {ai_api_key}",
                "Content-Type": "application/json"
            }
            
            print("[+] OpenAI API çağrısı yapılıyor...")
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            
            print(f"[DEBUG] API Response Status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"[!] OpenAI API hatası (Status: {response.status_code}): {response.text}")
                print(f"[+] Kural tabanlı seçim kullanılıyor: {selected_flair}")
                return selected_flair_id
            
            result = response.json()
            print(f"[DEBUG] OpenAI Response: {result}")
            
            # AI yanıtını al
            if "choices" in result and len(result["choices"]) > 0:
                ai_suggestion = result["choices"][0]["message"]["content"].strip()
                print(f"[+] AI flair önerisi: {ai_suggestion}")
                
                # Flair adını temizle ve kontrol et
                ai_suggestion_clean = ai_suggestion.replace(".", "").replace(":", "").strip()
                
                # Flair seçeneklerinde ara
                for flair_name, flair_id in FLAIR_OPTIONS.items():
                    if flair_name.lower() in ai_suggestion_clean.lower() or ai_suggestion_clean.lower() in flair_name.lower():
                        print(f"[+] AI seçilen flair: {flair_name} (ID: {flair_id})")
                        return flair_id
                
                # Tam eşleşme bulunamazsa, kural tabanlı seçimi kullan
                print(f"[!] AI önerisi eşleşmedi ({ai_suggestion_clean}), kural tabanlı seçim kullanılıyor: {selected_flair}")
                return selected_flair_id
            else:
                print("[!] AI yanıtı alınamadı, kural tabanlı seçim kullanılıyor")
                return selected_flair_id
                
    except requests.exceptions.Timeout:
        print("[!] AI API timeout, kural tabanlı seçim kullanılıyor")
        return selected_flair_id
    except requests.exceptions.RequestException as req_e:
        print(f"[!] AI API çağrısı başarısız: {req_e}")
        print(f"[+] Kural tabanlı seçim kullanılıyor: {selected_flair}")
        return selected_flair_id
    except Exception as e:
        print(f"[!] Flair seçimi hatası: {e}")
        print(f"[+] Kural tabanlı seçim kullanılıyor: {selected_flair}")
        import traceback
        traceback.print_exc()
        return selected_flair_id

def download_media(media_url, filename):
    try:
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "*/*",
            "Connection": "keep-alive",
        }
        # Session with retries for server errors
        session = requests.Session()
        retry_policy = Retry(
            total=5,
            connect=3,
            read=3,
            backoff_factor=1.0,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_policy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Primary: streamed download
        for attempt in range(1, 4):
            try:
                with session.get(
                    media_url,
                    headers=headers,
                    stream=True,
                    timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
                ) as r:
                    if r.status_code != 200:
                        print(f"[HATA] Medya indirilemedi (HTTP {r.status_code}): {media_url}")
                        raise requests.exceptions.RequestException(f"HTTP {r.status_code}")
                    with open(filename, "wb") as f:
                        for chunk in r.iter_content(1024 * 64):
                            if chunk:
                                f.write(chunk)
                                if DOWNLOAD_CHUNK_SLEEP_MS > 0:
                                    try:
                                        time.sleep(DOWNLOAD_CHUNK_SLEEP_MS / 1000.0)
                                    except Exception:
                                        pass
                    return filename
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ReadTimeout,
                    requests.exceptions.ProtocolError) as rexc:
                print(f"[UYARI] Medya indirme denemesi {attempt}/3 hata: {rexc}")
            except Exception as e:
                print(f"[UYARI] Medya indirme beklenmeyen hata {attempt}/3: {e}")
            # Backoff between attempts
            try:
                time.sleep(1.0 * attempt)
            except Exception:
                pass

        # Fallback: non-streamed download (for small files or stubborn hosts)
        try:
            r = session.get(media_url, headers=headers, timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT))
            if r.status_code == 200:
                with open(filename, "wb") as f:
                    f.write(r.content)
                return filename
            else:
                print(f"[HATA] Medya indirilemedi (fallback HTTP {r.status_code}): {media_url}")
        except Exception as fe:
            print(f"[HATA] Medya indirilemedi (fallback): {fe}")

        print(f"[HATA] Medya indirme başarısız: {media_url}")
        return None
    except Exception as e:
        print(f"[HATA] Medya indirirken (genel): {e}")
        return None

def get_image_hash(image_path):
    """Resim dosyasının hash'ini hesapla (duplicate detection için)"""
    try:
        hasher = hashlib.md5()
        with open(image_path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"[HATA] Hash hesaplanırken: {e}")
        return None

def download_multiple_images(media_urls, tweet_id):
    """Birden fazla resmi indir ve duplicate'leri filtrele"""
    downloaded_images = []
    image_hashes = set()
    
    print(f"[+] {len(media_urls)} medya URL'si işleniyor...")
    
    for i, media_url in enumerate(media_urls):
        try:
            # Geliştirilmiş resim tespiti
            url_lower = media_url.lower()
            is_image = (
                any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']) or
                'format=jpg' in url_lower or 'format=jpeg' in url_lower or 
                'format=png' in url_lower or 'format=webp' in url_lower or
                'pbs.twimg.com/media' in url_lower
            )
            if not is_image:
                print(f"[!] Resim olmayan medya atlanıyor: {media_url}")
                continue
                
            ext = os.path.splitext(media_url)[1].split("?")[0]
            if not ext:
                ext = ".jpg"  # Default extension
            
            filename = f"temp_image_{tweet_id}_{i}{ext}"
            print(f"[+] Resim indiriliyor ({i+1}/{len(media_urls)}): {media_url[:50]}...")
            
            path = download_media(media_url, filename)
            if path and os.path.exists(path):
                # Hash kontrolü ile duplicate detection
                image_hash = get_image_hash(path)
                if image_hash and image_hash not in image_hashes:
                    image_hashes.add(image_hash)
                    downloaded_images.append(path)
                    print(f"[+] Benzersiz resim eklendi: {path}")
                else:
                    print(f"[!] Duplicate resim atlandı: {path}")
                    # Duplicate dosyayı sil
                    if os.path.exists(path):
                        os.remove(path)
            else:
                print(f"[!] Resim indirilemedi: {media_url}")
                
        except Exception as e:
            print(f"[HATA] Resim işleme hatası ({media_url}): {e}")
    
    print(f"[+] Toplam {len(downloaded_images)} benzersiz resim indirildi")
    return downloaded_images

def convert_video_to_reddit_format(input_path, output_path):
    """Reddit için optimize edilmiş video dönüştürme"""
    try:
        print(f"[+] Reddit uyumlu video dönüştürme başlatılıyor: {input_path} -> {output_path}")
        
        # Video bilgilerini kontrol et
        probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", input_path]
        try:
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            video_info = json.loads(probe_result.stdout)
            
            duration = float(video_info['format']['duration'])
            if duration > 900:  # 15 dakika Reddit limiti
                print(f"[HATA] Video çok uzun ({duration:.1f}s). Reddit limiti: 900s")
                return None
                
            print(f"[+] Orijinal video süresi: {duration:.1f}s")
            
        except Exception as probe_e:
            print(f"[UYARI] Video bilgisi alınamadı: {probe_e}")
            # Süre bilinmiyorsa makul bir süre kullan
            duration = 120.0
        
        # OPTIMIZE EDİLMİŞ FFmpeg komutu - 4K video ve bellek sorunları için
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-c:v", "libx264",
            "-profile:v", "baseline",  # En uyumlu profil
            "-level", "3.1",  # Daha düşük level (daha az bellek)
            "-preset", "veryfast",  # Daha hızlı işlem için
            "-crf", "28",  # Daha yüksek CRF (küçük dosya)
            "-maxrate", "2M",  # Düşük bitrate
            "-bufsize", "4M",  # Küçük buffer
            "-g", "30",
            "-keyint_min", "30",
            "-sc_threshold", "0",
            "-c:a", "aac",
            "-b:a", "96k",  # Düşük audio bitrate
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease:flags=fast_bilinear,pad=ceil(iw/2)*2:ceil(ih/2)*2,fps=24",  # 720p max, 24fps
            "-r", "24",  # Düşük framerate
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts",
            "-map_metadata", "-1",
            "-threads", "1",  # Daha az thread (daha düşük bellek kullanımı)
            "-y",
            output_path
        ]
        
        print(f"[+] Reddit uyumlu FFmpeg komutu çalıştırılıyor...")
        print(f"[DEBUG] Komut: {' '.join(cmd[:10])}...")  # İlk 10 parametreyi göster
        # Süreye göre uyarlanabilir timeout (min 5dk, max 15dk)
        conv_timeout = int(max(300, min(900, duration * 8)))
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=conv_timeout)
        
        if result.returncode != 0:
            print(f"[HATA] FFmpeg başarısız (code: {result.returncode})")
            print(f"[HATA] FFmpeg stderr: {result.stderr[:500]}")  # İlk 500 karakter
            return None
        
        # Dönüştürülmüş dosyayı kontrol et
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:  # En az 1KB
            file_size = os.path.getsize(output_path)
            print(f"[+] Video başarıyla dönüştürüldü: {output_path} ({file_size} bytes)")
            
            # Dönüştürülmüş video bilgilerini kontrol et
            try:
                probe_result2 = subprocess.run(probe_cmd[:-1] + [output_path], capture_output=True, text=True, check=True)
                video_info2 = json.loads(probe_result2.stdout)
                
                video_streams = [s for s in video_info2.get('streams', []) if s.get('codec_type') == 'video']
                if video_streams:
                    codec = video_streams[0].get('codec_name', 'unknown')
                    width = video_streams[0].get('width', 0)
                    height = video_streams[0].get('height', 0)
                    print(f"[+] Dönüştürülmüş video: {codec}, {width}x{height}")
                    
            except Exception as probe_e2:
                print(f"[UYARI] Dönüştürülmüş video bilgisi alınamadı: {probe_e2}")
            
            return output_path
        else:
            print("[HATA] Dönüştürülmüş video dosyası geçersiz")
            return None
            
    except subprocess.TimeoutExpired:
        print("[HATA] FFmpeg timeout - bir fallback ile yeniden denenecek")
        try:
            # Daha agresif: ultrafast preset, biraz daha düşük bitrate, aynı 720p/24fps
            fallback_cmd = [
                "ffmpeg",
                "-i", input_path,
                "-c:v", "libx264",
                "-profile:v", "baseline",
                "-level", "3.1",
                "-preset", "ultrafast",
                "-crf", "30",
                "-maxrate", "1.5M",
                "-bufsize", "3M",
                "-g", "30",
                "-keyint_min", "30",
                "-sc_threshold", "0",
                "-c:a", "aac",
                "-b:a", "96k",
                "-ar", "44100",
                "-ac", "2",
                "-movflags", "+faststart",
                "-pix_fmt", "yuv420p",
                "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease:flags=fast_bilinear,pad=ceil(iw/2)*2:ceil(ih/2)*2,fps=24",
                "-r", "24",
                "-avoid_negative_ts", "make_zero",
                "-fflags", "+genpts",
                "-map_metadata", "-1",
                "-threads", "2",
                "-y",
                output_path
            ]
            print("[+] Fallback FFmpeg komutu çalıştırılıyor (ultrafast)...")
            fb_timeout = 900  # 15 dakika son şans
            fb_res = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=fb_timeout)
            if fb_res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                print("[+] Fallback dönüştürme başarılı")
                return output_path
            else:
                print(f"[HATA] Fallback FFmpeg başarısız (code: {fb_res.returncode})")
                print(f"[HATA] Fallback stderr: {fb_res.stderr[:500]}")
                return None
        except subprocess.TimeoutExpired:
            print("[HATA] Fallback FFmpeg de timeout verdi")
            return None
    except Exception as e:
        print(f"[HATA] Video dönüştürme hatası: {e}")
        return None

def get_video_duration_seconds(path: str) -> float | None:
    """ffprobe ile video süresini saniye cinsinden döndür. Hata halinde None döner."""
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(res.stdout or "{}")
        dur = float(info.get("format", {}).get("duration", "nan"))
        if dur != dur:  # NaN kontrolü
            return None
        return dur
    except Exception as e:
        print(f"[UYARI] Video süresi alınamadı: {e}")
        return None

# --- Scheduled weekly "Oyuncu Arama" post helper (stateless) ---
def _create_and_pin_weekly_post_if_due() -> None:
    """Scheduled weekly megathread creator.
    Primary schedule: every Friday (weekday=4) at/after configured hour.
    Fallback schedule: specified days-of-month in `SCHEDULED_PIN_DAYS` if WEEKDAY invalid.
    Uses PRAW and requires moderator permissions on the subreddit.
    """
    try:
        # Global toggle
        if not SCHEDULED_PIN_ENABLED:
            return
        lt = time.localtime()
        day = lt.tm_mday
        wday = lt.tm_wday  # 0=Mon .. 6=Sun
        hour = lt.tm_hour

        run_today = False
        # Prefer weekday schedule if valid
        if 0 <= SCHEDULED_PIN_WEEKDAY <= 6:
            run_today = (wday == SCHEDULED_PIN_WEEKDAY) and (hour >= SCHEDULED_PIN_HOUR)
        else:
            # Fallback to day-of-month list if provided
            if SCHEDULED_PIN_DAYS:
                run_today = (day in SCHEDULED_PIN_DAYS) and (hour >= SCHEDULED_PIN_HOUR)

        if not run_today:
            return
        today_key = time.strftime("%Y-%m-%d", lt)

        # Build title and body
        tarih = time.strftime("%d.%m.%Y", lt)
        title = f"{SCHEDULED_PIN_TITLE_PREFIX}{tarih})"
        body = (
            "**Hoş geldiniz!**\n\n"
            "Bu başlık, takım/oyuncu bulmanızı kolaylaştırmak amacıyla oluşturulmuştur. Eğer birlikte oyun oynayabileceğiniz yeni kişiler arıyorsanız doğru yerdesiniz! Aşağıda belirtildiği şekilde yorum yaparak takım arkadaşı arayabilirsiniz. Böylece benzer oyunlara ve tercihlere sahip oyuncular kolayca bir araya gelebilir.\n\n"
            "**Lütfen yorumlarınızda şunları belirtmeyi unutmayın:**\n\n"
            "* Oyun platformunuz (PC, PlayStation, Xbox vb.)\n"
            "* Oyun içi kullanıcı adınız\n"
            "* Mikrofonlu/suz bilgisi\n"
            "* Genellikle oynadığınız veya oynayacağınız görev birimi (assault, medic, recon vb.)\n\n"
            "Bu bilgiler sayesinde, benzer oyun ve oyun tarzlarına sahip kişilerle daha kolay iletişim kurabilirsiniz.\n\n"
            "**Yorumların sıralanması:**\n\n"
            "Yorumlar sistem tarafından otomatik olarak en yeni yorumdan en eski yoruma doğru sıralanmaktadır. Böylece en güncel oyunculara ve taleplere kolayca ulaşabilirsiniz.\n\n"
            "Her seviyeden oyuncuya açıktır, saygılı ve destekleyici bir ortam yaratmayı amaçlıyoruz. Keyifli oyunlar!"
        )

        # Stateless dedupe: scan recent posts for today's weekly thread
        sr = reddit.subreddit(SUBREDDIT)
        try:
            for s in sr.new(limit=30):
                try:
                    author_name = getattr(s.author, 'name', '') or ''
                except Exception:
                    author_name = ''
                s_title = getattr(s, 'title', '') or ''
                try:
                    created_utc = int(getattr(s, 'created_utc', 0) or 0)
                except Exception:
                    created_utc = 0
                s_local = time.localtime(created_utc) if created_utc else None
                s_key = time.strftime("%Y-%m-%d", s_local) if s_local else ''
                if (
                    author_name.lower() == (REDDIT_USERNAME or '').lower()
                    and s_title.startswith(SCHEDULED_PIN_TITLE_PREFIX)
                    and s_key == today_key
                ):
                    print(f"[INFO] Bugünün haftalık başlığı zaten mevcut: https://reddit.com{s.permalink}")
                    return
        except Exception as scan_e:
            print(f"[UYARI] Mevcut haftalık gönderiler taranamadı: {scan_e}")

        print("[+] Haftalık oyuncu arama gönderisi oluşturuluyor ve sabitleniyor...")
        submission = sr.submit(title=title, selftext=body, send_replies=False, resubmit=False)
        if submission:
            try:
                # Pin to top (slot 1) and set suggested sort to 'new'
                submission.mod.sticky(state=True, bottom=False)
                try:
                    submission.mod.suggested_sort("new")
                except Exception as se:
                    print(f"[UYARI] suggested_sort ayarlanamadı: {se}")
                print(f"[+] Haftalık gönderi oluşturuldu ve sabitlendi: https://reddit.com{submission.permalink}")

                # Unsticky older megathreads so only the newest stays pinned
                try:
                    for slot in (1, 2):
                        try:
                            stickied = sr.sticky(number=slot)
                        except Exception:
                            stickied = None
                        if not stickied:
                            continue
                        try:
                            st_author = getattr(stickied.author, 'name', '') or ''
                        except Exception:
                            st_author = ''
                        st_title = getattr(stickied, 'title', '') or ''
                        if (
                            stickied.id != submission.id and
                            st_author.lower() == (REDDIT_USERNAME or '').lower() and
                            st_title.startswith(SCHEDULED_PIN_TITLE_PREFIX)
                        ):
                            try:
                                stickied.mod.sticky(state=False)
                                print(f"[+] Eski haftalık başlık unsticky yapıldı: https://reddit.com{stickied.permalink}")
                            except Exception as ue:
                                print(f"[UYARI] Unsticky başarısız: {ue}")
                except Exception as sweep_e:
                    print(f"[UYARI] Sticky temizleme sırasında hata: {sweep_e}")
                # Extra sweep: scan recent posts and unsticky any lingering older stickied megathreads
                try:
                    for s in sr.new(limit=100):
                        try:
                            if getattr(s, 'id', None) == submission.id:
                                continue
                            if not getattr(s, 'stickied', False):
                                continue
                            author_name = getattr(s.author, 'name', '') or ''
                            s_title = getattr(s, 'title', '') or ''
                            if (
                                author_name.lower() == (REDDIT_USERNAME or '').lower() and
                                s_title.startswith(SCHEDULED_PIN_TITLE_PREFIX)
                            ):
                                try:
                                    s.mod.sticky(state=False)
                                    print(f"[+] Eski stickied gönderi unsticky yapıldı: https://reddit.com{s.permalink}")
                                except Exception as ue2:
                                    print(f"[UYARI] Unsticky (scan) başarısız: {ue2}")
                        except Exception:
                            # Ignore errors for individual items in the sweep
                            continue
                except Exception as scan_uns_e:
                    print(f"[UYARI] Ek sticky tarama/temizleme hatası: {scan_uns_e}")
            except Exception as me:
                print(f"[UYARI] Gönderi sabitleme/moderasyon işlemi başarısız: {me}")
        else:
            print("[UYARI] Haftalık gönderi oluşturulamadı (PRAW submit falsy)")
    except Exception as e:
        print(f"[UYARI] Haftalık gönderi oluşturma hatası: {e}")

def upload_gallery_via_redditwarp(title, image_paths, subreddit_name, flair_id=None):
    """RedditWarp ile birden fazla resmi gallery olarak yükle"""
    if not redditwarp_client:
        print("[HATA] RedditWarp client mevcut değil")
        return False
        
    if not image_paths:
        print("[HATA] Yüklenecek resim yok")
        return False
        
    try:
        print(f"[+] {len(image_paths)} resim için gallery oluşturuluyor...")
        
        # Görselleri normalize et (RGB, boyut sınırı, baseline JPEG)
        def _normalize_image(path):
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    max_dim = 4096
                    w, h = im.size
                    if max(w, h) > max_dim:
                        if w >= h:
                            new_w = max_dim
                            new_h = int(h * (max_dim / w))
                        else:
                            new_h = max_dim
                            new_w = int(w * (max_dim / h))
                        im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    out_path = os.path.join(os.path.dirname(path), os.path.splitext(os.path.basename(path))[0] + "_norm.jpg")
                    im.save(out_path, format="JPEG", quality=90, optimize=True, progressive=False)
                    print(f"[+] Normalize edildi: {os.path.basename(out_path)}")
                    return out_path
            except Exception as _norm_e:
                print(f"[UYARI] Normalize edilemedi ({os.path.basename(path)}): {_norm_e}")
            return path
        
        norm_image_paths = [_normalize_image(p) for p in image_paths]
        
        # Her resim için upload lease al
        image_leases = []
        for i, image_path in enumerate(norm_image_paths):
            print(f"[+] Resim {i+1}/{len(image_paths)} yükleniyor: {os.path.basename(image_path)}")
            
            if not os.path.exists(image_path):
                print(f"[HATA] Resim dosyası bulunamadı: {image_path}")
                continue
                
            try:
                with open(image_path, 'rb') as image_file:
                    # RedditWarp ile resim upload
                    image_lease = redditwarp_client.p.submission.media_uploading.upload(image_file)
                    image_leases.append(image_lease)
                    print(f"[+] Resim lease alındı - Media ID: {image_lease.media_id}")
                
            except Exception as upload_e:
                print(f"[HATA] Resim yükleme hatası ({image_path}): {upload_e}")
                continue
        
        if not image_leases:
            print("[HATA] Hiçbir resim yüklenemedi")
            return False
            
        print(f"[+] {len(image_leases)} resim başarıyla yüklendi, gallery oluşturuluyor...")
        
        # Gallery post oluştur
        try:
            # RedditWarp gallery creation
            gallery_items = [
                SimpleNamespace(
                    id=idx,
                    media_id=lease.media_id,
                    caption=f"Resim {idx+1}",
                    outbound_link="",
                )
                for idx, lease in enumerate(image_leases)
            ]
            
            created = redditwarp_client.p.submission.create.gallery(
                sr=subreddit_name,
                title=title,
                items=gallery_items
            )
            
            if created:
                submission_id = getattr(created, 'id', str(created))
                print(f"[+] Gallery başarıyla oluşturuldu - ID: {submission_id}")
                # Flair uygula (mümkünse)
                try:
                    # Try to resolve flair per subreddit before applying
                    effective_flair_id = _resolve_flair_id_for_subreddit(subreddit_name, flair_id, _FLAIR_NAME_BY_ID.get(flair_id)) if flair_id else None
                    if effective_flair_id and submission_id and isinstance(submission_id, str):
                        try:
                            praw_sub = reddit.submission(id=submission_id)
                            praw_sub.flair.select(effective_flair_id)
                            print(f"[+] Gallery flair uygulandı: {effective_flair_id}")
                        except Exception as fe:
                            print(f"[UYARI] Gallery flair uygulanamadı: {fe}")
                    elif effective_flair_id:
                        # Başlığa göre yakın zamanda oluşturulan gönderiyi bul
                        try:
                            sr_obj = reddit.subreddit(subreddit_name)
                            for s in sr_obj.new(limit=10):
                                author_name = getattr(s.author, 'name', '') or ''
                                if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                                    s.flair.select(effective_flair_id)
                                    print(f"[+] Gallery flair uygulandı (arama ile): {effective_flair_id}")
                                    break
                        except Exception as fe2:
                            print(f"[UYARI] Gallery flair uygulanamadı (arama): {fe2}")
                except Exception:
                    pass
                # Başarılı gönderiden sonra disk temizliği
                try:
                    # Normalized dosyaları sil
                    for p in norm_image_paths:
                        if p and os.path.exists(p):
                            try:
                                os.remove(p)
                                print(f"[TEMİZLİK] Silindi: {p}")
                            except Exception as de:
                                print(f"[UYARI] Silinemedi: {p} - {de}")
                    # Orijinal dosyaları da sil
                    for p in image_paths:
                        if p and os.path.exists(p):
                            try:
                                os.remove(p)
                                print(f"[TEMİZLİK] Silindi: {p}")
                            except Exception as de:
                                print(f"[UYARI] Silinemedi: {p} - {de}")
                except Exception as ce:
                    print(f"[UYARI] Temizlik sırasında hata: {ce}")
                return True
            else:
                # RedditWarp bazen creation nesnesini döndürmeyebilir; canlıda doğrula
                print("[UYARI] Gallery API yanıtı falsy görünüyor, subreddit'te doğrulanıyor...")
                try:
                    sr_obj = reddit.subreddit(subreddit_name)
                    for s in sr_obj.new(limit=10):
                        author_name = getattr(s.author, 'name', '') or ''
                        if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                            print(f"[+] Gallery gönderisi doğrulandı: {s.url}")
                            # Flair uygula
                            try:
                                if flair_id:
                                    efid = _resolve_flair_id_for_subreddit(subreddit_name, flair_id, _FLAIR_NAME_BY_ID.get(flair_id))
                                    if efid:
                                        s.flair.select(efid)
                                        print(f"[+] Gallery flair uygulandı (doğrulama): {efid}")
                            except Exception as fe:
                                print(f"[UYARI] Gallery flair uygulanamadı (doğrulama): {fe}")
                            # Başarılı kabul et ve dosyaları temizle
                            try:
                                for p in norm_image_paths:
                                    if p and os.path.exists(p):
                                        try:
                                            os.remove(p)
                                            print(f"[TEMİZLİK] Silindi: {p}")
                                        except Exception as de:
                                            print(f"[UYARI] Silinemedi: {p} - {de}")
                                for p in image_paths:
                                    if p and os.path.exists(p):
                                        try:
                                            os.remove(p)
                                            print(f"[TEMİZLİK] Silindi: {p}")
                                        except Exception as de:
                                            print(f"[UYARI] Silinemedi: {p} - {de}")
                            except Exception as ce:
                                print(f"[UYARI] Temizlik sırasında hata: {ce}")
                            return True
                except Exception as ve:
                    print(f"[UYARI] Gallery doğrulama hatası: {ve}")
                print("[HATA] Gallery oluşturulamadı")
                return False
        except Exception as create_e:
            print(f"[HATA] Gallery oluşturma hatası: {create_e}")
            # Hata durumunda da doğrulamayı dene (async yaratılmış olabilir)
            try:
                sr_obj = reddit.subreddit(subreddit_name)
                for s in sr_obj.new(limit=10):
                    author_name = getattr(s.author, 'name', '') or ''
                    if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                        print(f"[+] Gallery gönderisi hata sonrasında doğrulandı: {s.url}")
                        # Flair uygula
                        try:
                            if flair_id:
                                efid = _resolve_flair_id_for_subreddit(subreddit_name, flair_id, _FLAIR_NAME_BY_ID.get(flair_id))
                                if efid:
                                    s.flair.select(efid)
                                    print(f"[+] Gallery flair uygulandı (hata sonrası doğrulama): {efid}")
                        except Exception as fe:
                            print(f"[UYARI] Gallery flair uygulanamadı (hata sonrası doğrulama): {fe}")
                        # Başarılı kabul et ve dosyaları temizle
                        try:
                            for p in norm_image_paths:
                                if p and os.path.exists(p):
                                    try:
                                        os.remove(p)
                                        print(f"[TEMİZLİK] Silindi: {p}")
                                    except Exception as de:
                                        print(f"[UYARI] Silinemedi: {p} - {de}")
                            for p in image_paths:
                                if p and os.path.exists(p):
                                    try:
                                        os.remove(p)
                                        print(f"[TEMİZLİK] Silindi: {p}")
                                    except Exception as de:
                                        print(f"[UYARI] Silinemedi: {p} - {de}")
                        except Exception as ce:
                            print(f"[UYARI] Temizlik sırasında hata: {ce}")
                        return True
            except Exception as ve:
                print(f"[UYARI] Gallery doğrulama hatası: {ve}")
            return False
        
    except Exception as e:
        print(f"[HATA] RedditWarp gallery yükleme genel hatası: {e}")
        import traceback
        traceback.print_exc()
        return False

def upload_video_via_redditwarp(title, media_path, subreddit_name, flair_id=None):
    """RedditWarp dokümantasyonuna göre video yükleme - Media Upload Protocol"""
    if not redditwarp_client:
        print("[HATA] RedditWarp client mevcut değil")
        return False
        
    try:
        print("[+] RedditWarp ile video yükleme başlatılıyor...")
        
        # Dosya kontrolleri
        if not os.path.exists(media_path):
            print(f"[HATA] Video dosyası bulunamadı: {media_path}")
            return False
            
        file_size = os.path.getsize(media_path)
        if file_size == 0:
            print(f"[HATA] Video dosyası boş: {media_path}")
            return False
            
        # Reddit limitleri - dokümantasyona göre
        max_size = 1024 * 1024 * 1024  # 1GB
        if file_size > max_size:
            print(f"[HATA] Video çok büyük ({file_size} bytes). Reddit limiti: {max_size} bytes")
            return False
            
        print(f"[+] Video dosyası geçerli: {file_size} bytes")
        
        # Video bilgilerini doğrula
        try:
            probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", media_path]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            video_info = json.loads(probe_result.stdout)
            
            duration = float(video_info['format']['duration'])
            if duration > 900:  # 15 dakika - dokümantasyona göre
                print(f"[HATA] Video çok uzun ({duration:.1f}s). Reddit limiti: 900s")
                return False
            
            # Video stream kontrolü
            video_streams = [s for s in video_info.get('streams', []) if s.get('codec_type') == 'video']
            if not video_streams:
                print("[HATA] Video stream bulunamadı")
                return False
                
            codec = video_streams[0].get('codec_name', '')
            print(f"[+] Video geçerli - Codec: {codec}, Süre: {duration:.1f}s")
            
        except Exception as probe_e:
            print(f"[HATA] Video doğrulama başarısız: {probe_e}")
            return False
        
        # Rate limiting
        print("[+] Rate limit için 3 saniye bekleniyor...")
        time.sleep(3)
        
        # RedditWarp Media Upload Protocol - dokümantasyona göre 2 adımlı süreç
        print("[+] RedditWarp Media Upload Protocol başlatılıyor...")
        
        # Adım 1: Video için upload lease al
        print("[+] Video upload lease alınıyor...")
        try:
            filename = os.path.basename(media_path)
            with open(media_path, 'rb') as video_file:
                # RedditWarp dokümantasyonuna göre: submission.media_uploading.upload()
                video_lease = redditwarp_client.p.submission.media_uploading.upload(video_file)
                print(f"[+] Video lease alındı - Media ID: {video_lease.media_id}")
                print(f"[+] Video S3 Location: {video_lease.location}")
                
        except Exception as video_lease_e:
            print(f"[HATA] Video upload lease hatası: {video_lease_e}")
            return False
        
        # Thumbnail oluştur (RedditWarp dokümantasyonu video post için thumbnail gerektirir)
        print("[+] Video thumbnail oluşturuluyor...")
        thumbnail_path = None
        try:
            # FFmpeg ile thumbnail oluştur
            thumbnail_filename = f"thumb_{os.path.splitext(filename)[0]}.jpg"
            thumbnail_path = os.path.join(os.path.dirname(media_path), thumbnail_filename)
            
            thumb_cmd = [
                "ffmpeg", "-i", media_path, "-ss", "00:00:01", "-vframes", "1",
                "-vf", "scale=640:360:force_original_aspect_ratio=decrease",
                "-y", thumbnail_path
            ]
            
            subprocess.run(thumb_cmd, capture_output=True, check=True)
            
            if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                print(f"[+] Thumbnail oluşturuldu: {thumbnail_path}")
                
                # Adım 2: Thumbnail için upload lease al
                print("[+] Thumbnail upload lease alınıyor...")
                with open(thumbnail_path, 'rb') as thumb_file:
                    thumb_lease = redditwarp_client.p.submission.media_uploading.upload(thumb_file)
                    print(f"[+] Thumbnail lease alındı - Media ID: {thumb_lease.media_id}")
                    print(f"[+] Thumbnail S3 Location: {thumb_lease.location}")
            else:
                print("[UYARI] Thumbnail oluşturulamadı, video olmadan devam ediliyor")
                thumb_lease = None
                
        except Exception as thumb_e:
            print(f"[UYARI] Thumbnail oluşturma hatası: {thumb_e}")
            thumb_lease = None
            if thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    os.remove(thumbnail_path)
                except:
                    pass
        
        # Adım 3: Video post oluştur - RedditWarp dokümantasyonuna göre
        print("[+] Video submission oluşturuluyor...")
        try:
            if thumb_lease:
                # Thumbnail ile video post - doğru RedditWarp metodu ve parametreler
                created = redditwarp_client.p.submission.create.video(
                    sr=subreddit_name,
                    title=title,
                    link=video_lease.location,
                    thumbnail=thumb_lease.location
                )
            else:
                # Sadece video ile post (thumbnail olmadan)
                # RedditWarp dokümantasyonuna göre thumbnail gerekli, bu durumda hata verebilir
                created = redditwarp_client.p.submission.create.video(
                    sr=subreddit_name,
                    title=title,
                    link=video_lease.location,
                    thumbnail=video_lease.location  # Thumbnail yerine video location kullan
                )
            
            # If we reach here without exception, the submission was successful
            print("[+] RedditWarp video submission başarılı!")
            
            # Oluşan gönderinin ID'sini elde etmeyi dene
            submission_id = None
            try:
                # Olası alan adları: id / id36 / post_id / submission_id / fullname (t3_xxxxx)
                if isinstance(created, str):
                    # Bazı sürümler fullname (t3_xxxxx) döndürebilir
                    if created.startswith("t3_"):
                        submission_id = created.split("t3_")[-1]
                    else:
                        submission_id = created
                elif hasattr(created, "id"):
                    submission_id = getattr(created, "id")
                elif hasattr(created, "id36"):
                    submission_id = getattr(created, "id36")
                elif hasattr(created, "submission_id"):
                    submission_id = getattr(created, "submission_id")
                elif hasattr(created, "post_id"):
                    submission_id = getattr(created, "post_id")
                elif hasattr(created, "fullname"):
                    fullname = getattr(created, "fullname")
                    if isinstance(fullname, str) and fullname.startswith("t3_"):
                        submission_id = fullname.split("t3_")[-1]
                elif hasattr(created, "get"):
                    # dict benzeri
                    submission_id = created.get("id") or created.get("id36") or created.get("submission_id") or created.get("post_id")
            except Exception as id_e:
                print(f"[UYARI] RedditWarp dönen nesneden ID çıkarılamadı: {id_e}")

            if submission_id:
                print(f"[+] Oluşan gönderi ID: {submission_id}")
                print(f"[+] URL: https://reddit.com/r/{subreddit_name}/comments/{submission_id}")
                # Flair uygula (ID mevcutsa)
                try:
                    if flair_id:
                        efid = _resolve_flair_id_for_subreddit(subreddit_name, flair_id, _FLAIR_NAME_BY_ID.get(flair_id))
                        if efid:
                            praw_sub = reddit.submission(id=submission_id)
                            praw_sub.flair.select(efid)
                            print(f"[+] Video flair uygulandı (ID ile): {efid}")
                except Exception as fe:
                    print(f"[UYARI] Video flair uygulanamadı (ID ile): {fe}")
            else:
                print("[UYARI] RedditWarp oluşturulan gönderi ID'si alınamadı")
                submission_id = ""
                
            # Video processing bekle
            print("[+] Video processing için 30 saniye bekleniyor...")
            time.sleep(30)
            
            # Flair yoksa, başlığa göre en son gönderiyi bulup uygula
            if (not submission_id) and flair_id:
                try:
                    efid = _resolve_flair_id_for_subreddit(subreddit_name, flair_id, _FLAIR_NAME_BY_ID.get(flair_id)) if flair_id else None
                    if efid:
                        sr_obj = reddit.subreddit(subreddit_name)
                        for s in sr_obj.new(limit=10):
                            author_name = getattr(s.author, 'name', '') or ''
                            if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                                s.flair.select(efid)
                                print(f"[+] Video flair uygulandı (arama ile): {efid}")
                                break
                except Exception as fe:
                    print(f"[UYARI] Video flair uygulanamadı (arama ile): {fe}")

            # Deterministik yorum için ID döndür
            return submission_id or True
                
        except Exception as submission_e:
            print(f"[HATA] Video submission hatası: {submission_e}")
            print(f"[DEBUG] Hata tipi: {type(submission_e).__name__}")
            
            # RedditError'u özel olarak handle et
            if hasattr(submission_e, 'label'):
                print(f"[DEBUG] Reddit Error Label: {submission_e.label}")
                if hasattr(submission_e, 'explanation'):
                    print(f"[DEBUG] Reddit Error Explanation: {submission_e.explanation}")
                    
                # Spesifik Reddit hataları
                if submission_e.label == 'NO_VIDEOS':
                    print("[!] Subreddit video post'lara izin vermiyor")
                elif submission_e.label == 'MISSING_VIDEO_URLS':
                    print("[!] Video URL'leri eksik veya geçersiz")
                elif submission_e.label == 'SUBREDDIT_NOTALLOWED':
                    print("[!] Subreddit'e post atma izni yok")
                elif submission_e.label == 'USER_REQUIRED':
                    print("[!] Kullanıcı kimlik doğrulama gerekli")
            
            # Genel hata türüne göre mesaj
            error_str = str(submission_e).lower()
            if "rate limit" in error_str or "429" in error_str:
                print("[!] Rate limit hatası - daha uzun bekleme gerekli")
            elif "413" in error_str or "too large" in error_str:
                print("[!] Dosya çok büyük hatası")
            elif "400" in error_str or "invalid" in error_str:
                print("[!] Geçersiz video formatı veya parametreler")
            elif "403" in error_str or "forbidden" in error_str:
                print("[!] İzin hatası - subreddit veya kullanıcı yetkileri")
            elif "timeout" in error_str:
                print("[!] Timeout hatası - video çok büyük veya ağ yavaş")
            
            # Tam traceback'i göster
            import traceback
            print("[DEBUG] Tam hata detayı:")
            traceback.print_exc()
            
            return False
            
    except Exception as e:
        print(f"[HATA] RedditWarp video yükleme genel hatası: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Thumbnail temizliği
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                os.remove(thumbnail_path)
                print(f"[+] Thumbnail temizlendi: {thumbnail_path}")
            except Exception as cleanup_e:
                print(f"[UYARI] Thumbnail temizleme hatası: {cleanup_e}")

def upload_video_via_reddit_api(title, media_path, subreddit_name, flair_id=None):
    """Video yükleme - önce RedditWarp, sonra PRAW fallback"""
    
    # Önce RedditWarp dene
    if redditwarp_client:
        print("[+] RedditWarp yöntemi deneniyor...")
        warp_result = upload_video_via_redditwarp(title, media_path, subreddit_name, flair_id=flair_id)
        if warp_result:
            # ID string dönebilir veya True olabilir
            return warp_result
        else:
            print("[!] RedditWarp başarısız, PRAW fallback deneniyor...")
    
    # PRAW fallback
    try:
        print("[+] PRAW fallback ile video yükleme...")
        
        # Dosya kontrolleri
        if not os.path.exists(media_path):
            print(f"[HATA] Video dosyası bulunamadı: {media_path}")
            return False
            
        file_size = os.path.getsize(media_path)
        if file_size == 0:
            print(f"[HATA] Video dosyası boş: {media_path}")
            return False
            
        print(f"[+] Video dosyası geçerli: {file_size} bytes")
        
        subreddit = reddit.subreddit(subreddit_name)
        
        # Rate limiting
        print("[+] Rate limit için 5 saniye bekleniyor...")
        time.sleep(5)
        
        # PRAW video upload
        submission = subreddit.submit_video(
            title=title,
            video_path=media_path,
            videogif=False,
            without_websockets=True,
            nsfw=False,
            spoiler=False,
            send_replies=True,
            resubmit=True,
            timeout=300,
            thumbnail_path=None
        )
        
        if submission:
            print(f"[+] PRAW video yüklemesi başarılı - ID: {submission.id}")
            print(f"[+] URL: https://reddit.com/r/{subreddit_name}/comments/{submission.id}")
            # Flair uygula
            try:
                if flair_id:
                    efid = _resolve_flair_id_for_subreddit(subreddit_name, flair_id, _FLAIR_NAME_BY_ID.get(flair_id))
                    if efid:
                        submission.flair.select(efid)
                        print(f"[+] Video flair uygulandı (PRAW): {efid}")
            except Exception as fe:
                print(f"[UYARI] Video flair uygulanamadı (PRAW): {fe}")
            # Başarılıysa Submission nesnesini döndür
            return submission
        else:
            print("[HATA] PRAW submission oluşturulamadı")
            return False
            
    except Exception as praw_e:
        print(f"[HATA] PRAW fallback hatası: {praw_e}")
        return False

def try_alternative_upload(title, media_path, subreddit, flair_id=None):
    """WebSocket hatası durumunda alternatif yükleme yöntemleri"""
    
    print("[+] Alternatif yükleme yöntemleri deneniyor...")
    
    # 1. Daha küçük boyutta yeniden kodlama
    try:
        print("[+] Video'yu daha küçük boyutta yeniden kodluyorum...")
        
        alt_output = media_path.replace('.mp4', '_small.mp4')
        command = [
            "ffmpeg",
            "-i", media_path,
            "-c:v", "libx264",
            "-preset", "ultrafast",  # Hızlı kodlama
            "-crf", "28",  # Daha yüksek sıkıştırma
            "-vf", "scale=640:360",  # 360p'ye düşür
            "-c:a", "aac",
            "-b:a", "64k",  # Daha düşük ses kalitesi
            "-movflags", "+faststart",
            "-y",
            alt_output
        ]
        
        subprocess.run(command, check=True, capture_output=True, timeout=120)
        
        if os.path.exists(alt_output) and os.path.getsize(alt_output) > 0:
            print(f"[+] Küçük video oluşturuldu: {os.path.getsize(alt_output)} bytes")
            
            # Küçük videoyu yüklemeyi dene - PRAW dokümantasyonu uyumlu
            time.sleep(5)
            submission = subreddit.submit_video(
                title=title, 
                video_path=alt_output, 
                videogif=False,
                without_websockets=True,
                nsfw=False,
                spoiler=False,
                send_replies=True,
                resubmit=True,
                timeout=300,  # Daha uzun timeout
                thumbnail_path=None
            )
            
            if submission:
                print(f"[+] Alternatif yöntemle video gönderildi: {submission.url}")
                # Flair uygula
                try:
                    if flair_id:
                        submission.flair.select(flair_id)
                        print(f"[+] Video flair uygulandı (alternatif): {flair_id}")
                except Exception as fe:
                    print(f"[UYARI] Video flair uygulanamadı (alternatif): {fe}")
                
                # Geçici dosyaları temizle
                try:
                    os.remove(media_path)
                    os.remove(alt_output)
                    print("[+] Geçici dosyalar temizlendi")
                except:
                    pass
                    
                return True
            else:
                print("[HATA] Alternatif video yükleme başarısız")
        else:
            print("[HATA] Alternatif video oluşturulamadı")
            
    except Exception as e:
        print(f"[HATA] Alternatif yükleme başarısız: {e}")
    
    # 2. Son çare text post kaldırıldı: medya başarısız olursa burada dur
    print("[!] Alternatifler de başarısız oldu, text post fallback devre dışı. İşlem sonlandırılıyor.")
    return False

def smart_split_title(text: str, max_len: int = 300):
    """Metni başlık ve kalan olarak akıllıca ayırır.
    - max_len sınırını aşmayacak şekilde son boşlukta keser.
    - Kesme olduysa başlığa "…" ekler ve kalan kısmı döndürür.
    """
    text = (text or "").strip()
    if len(text) <= max_len:
        return text, ""
    # Son boşluğu bul (maks uzunluk içinde)
    cutoff = text.rfind(" ", 0, max_len)
    if cutoff == -1:
        cutoff = max_len
    title = text[:cutoff].rstrip()
    remainder = text[cutoff:].lstrip()
    # Başlığa ellipsis ekle
    if title and not title.endswith("…"):
        title = (title + " …")[:max_len]
    return title, remainder


def submit_post(title, media_files, original_tweet_text="", remainder_text: str = ""):
    """Geliştirilmiş post gönderme fonksiyonu - AI flair seçimi ile"""
    subreddit = reddit.subreddit(SUBREDDIT)
    # Sanitize inputs for Reddit to avoid encoding artifacts
    title = _sanitize_for_reddit(title or "")
    remainder_text = _sanitize_for_reddit(remainder_text or "")
    
    # Medya dosyalarını türlerine göre ayır
    image_files = []
    video_files = []
    
    for media_file in media_files:
        if media_file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            image_files.append(media_file)
        elif media_file.lower().endswith('.mp4'):
            video_files.append(media_file)
    
    print(f"[+] Medya analizi: {len(image_files)} resim, {len(video_files)} video")

    # AI ile flair seçimi (gallery dahil tüm yollar için önce seç)
    has_video = len(video_files) > 0
    selected_flair_id = select_flair_with_ai(title, original_tweet_text, has_video=has_video)
    print(f"[+] Seçilen flair ID: {selected_flair_id}")
    # Resolve flair for this subreddit; if not valid, we'll omit flair during submit
    effective_flair_id = _resolve_flair_id_for_subreddit(SUBREDDIT, selected_flair_id, _FLAIR_NAME_BY_ID.get(selected_flair_id)) if selected_flair_id else None
    if not effective_flair_id and selected_flair_id:
        print(f"[UYARI] Seçilen flair bu subredditte yok. Flair'siz gönderilecek. (ID: {selected_flair_id})")
    
    # Önce resimleri gallery olarak yükle (eğer birden fazla resim varsa)
    if len(image_files) > 1:
        print(f"[+] {len(image_files)} resim gallery olarak yükleniyor...")
        gallery_result = upload_gallery_via_redditwarp(title, image_files, SUBREDDIT, flair_id=selected_flair_id)
        if gallery_result:
            print("[+] Gallery başarıyla yüklendi")
            # Geçici resim dosyalarını temizle
            for img_path in image_files:
                try:
                    if os.path.exists(img_path):
                        os.remove(img_path)
                        print(f"[+] Geçici resim silindi: {img_path}")
                except Exception as cleanup_e:
                    print(f"[UYARI] Resim silinirken hata: {cleanup_e}")
            return True
        else:
            # Fallback öncesi, Reddit'te gönderi oluşmuş mı kontrol et
            try:
                sr_obj = reddit.subreddit(SUBREDDIT)
                for s in sr_obj.new(limit=10):
                    author_name = getattr(s.author, 'name', '') or ''
                    if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                        print(f"[+] Gallery aslında oluşturulmuş (fallback iptal): {s.url}")
                        return True
            except Exception as ve:
                print(f"[UYARI] Fallback öncesi doğrulama hatası: {ve}")
            # Gallery başarısız görünüyor; tekil resim fallback DUPLICATE riski yaratıyor.
            # Bu nedenle burada dur ve False döndür; ana döngü yeniden deneyebilir.
            print("[!] Gallery yüklenemedi; tekil resim fallback devre dışı bırakıldı (duplicate önleme)")
            return False
    
    # Tekil resim veya video yükleme (mevcut kod)
    
    # Başlık doğrulama ve yedekler (Reddit 'Post title is required' hatasını önlemek için)
    raw_title = (title or "").strip()
    if not raw_title:
        # Yedek: orijinal tweet metni veya sabit başlık
        fallback = (original_tweet_text or "").strip()
        if fallback:
            raw_title = fallback
        else:
            raw_title = "Twitter medyası"
    # Reddit başlık limiti ~300 karakter
    title = raw_title[:300]
    
    if not media_files:
        # Medya yoksa sadece text post
        try:
            print("[+] Medya yok, text post gönderiliyor.")
            if effective_flair_id:
                submission = subreddit.submit(title=title, selftext=(remainder_text or ""), flair_id=effective_flair_id)
            else:
                submission = subreddit.submit(title=title, selftext=(remainder_text or ""))
            print(f"[+] Text post gönderildi: {submission.url}")
            return True
        except Exception as e:
            print(f"[HATA] Text post hatası: {e}")
            return False
    
    # Medya var
    media_path = media_files[0]
    
    if not os.path.exists(media_path):
        print(f"[HATA] Medya dosyası bulunamadı: {media_path}")
        return False
        
    file_size = os.path.getsize(media_path)
    if file_size == 0:
        print(f"[HATA] Medya dosyası boş: {media_path}")
        return False
        
    print(f"[+] Medya dosyası hazır: {media_path} ({file_size} bytes)")
    
    ext = os.path.splitext(media_path)[1].lower()
    
    try:
        if ext in [".jpg", ".jpeg", ".png", ".gif"]:
            # Resim yükleme
            print(f"[+] Resim gönderiliyor: {media_path}")
            if effective_flair_id:
                submission = subreddit.submit_image(title=title, image_path=media_path, flair_id=effective_flair_id)
            else:
                submission = subreddit.submit_image(title=title, image_path=media_path)
            print(f"[+] Resim başarıyla gönderildi: {submission.url}")
            # Uzun metnin kalanı yorum olarak ekle
            try:
                if remainder_text:
                    submission.reply(_sanitize_for_reddit(remainder_text))
                    print("[+] Başlığın kalan kısmı yorum olarak eklendi")
            except Exception as ce:
                print(f"[UYARI] Kalan metin yorum olarak eklenemedi: {ce}")
            return True
            
        elif ext in [".mp4", ".mov", ".webm"]:
            # Video yükleme
            print(f"[+] Video gönderiliyor: {media_path}")
            
            # Önce dosya boyutunu kontrol et (Reddit için güvenli limit)
            max_video_size = 512 * 1024 * 1024  # 512MB
            if file_size > max_video_size:
                print(f"[HATA] Video çok büyük ({file_size} bytes). Limit: {max_video_size} bytes")
                # Text post fallback kaldırıldı
                return False
            
            # Video upload denemesi
            result = upload_video_via_reddit_api(title, media_path, SUBREDDIT, selected_flair_id)
            
            if result:
                print("[+] Video başarıyla yüklendi!")
                # Eğer Submission nesnesi geldiyse kalan metni yorum olarak ekle
                try:
                    if hasattr(result, "reply") and remainder_text:
                        result.reply(_sanitize_for_reddit(remainder_text))
                        print("[+] Başlığın kalan kısmı video gönderisine yorum olarak eklendi")
                    elif isinstance(result, str) and remainder_text:
                        # Deterministik: RedditWarp ID döndü
                        try:
                            praw_sub = reddit.submission(id=result)
                            praw_sub.reply(_sanitize_for_reddit(remainder_text))
                            print("[+] Başlığın kalan kısmı (ID ile) video gönderisine yorum olarak eklendi")
                        except Exception as idc_e:
                            print(f"[UYARI] ID ile yorum ekleme başarısız: {idc_e}")
                    elif remainder_text:
                        # RedditWarp yolu: Submission nesnesi yok. Son gönderiyi bulup yorum eklemeyi dene.
                        try:
                            for s in subreddit.new(limit=10):
                                author_name = getattr(s.author, 'name', '') or ''
                                if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                                    s.reply(_sanitize_for_reddit(remainder_text))
                                    print("[+] Başlığın kalan kısmı (RedditWarp) video gönderisine yorum olarak eklendi")
                                    break
                        except Exception as se:
                            print(f"[UYARI] RedditWarp sonrası yorum ekleme başarısız: {se}")
                except Exception as ve:
                    print(f"[UYARI] Video yorum ekleme başarısız: {ve}")
                return True
            else:
                print("[!] Video yüklenemedi, alternatif yöntemler deneniyor...")
                # Alternatif yöntem dene
                alt_success = try_alternative_upload(title, media_path, subreddit)
                if alt_success:
                    return True
                else:
                    # Son çare text post kaldırıldı
                    return False
                
        else:
            print(f"[!] Desteklenmeyen dosya türü: {ext}")
            if effective_flair_id:
                submission = subreddit.submit(title=title, selftext=(remainder_text or ""), flair_id=effective_flair_id)
            else:
                submission = subreddit.submit(title=title, selftext=(remainder_text or ""))
            print(f"[+] Text post gönderildi: {submission.url}")
            return True
            
    except Exception as e:
        print(f"[HATA] Post gönderimi başarısız: {e}")
        
        # Özel durum: Reddit PRAW 'Websocket error. Check your media file. Your post may still have been created.'
        # Bu hata geldiğinde ve medya varsa ASLA text post gönderme.
        try:
            err_msg = str(e).lower()
        except Exception:
            err_msg = ""

        if (media_files and len(media_files) > 0) and ("websocket error" in err_msg and "check your media file" in err_msg):
            print("[!] Websocket error sonrası text post atlanıyor (medya var). Reddit'te gönderi oluşmuş olabilir, kontrol ediliyor...")
            # Son 10 gönderide başlığa bakarak oluşmuş mu kontrol et
            try:
                for s in subreddit.new(limit=10):
                    author_name = getattr(s.author, 'name', '') or ''
                    if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                        print(f"[+] Gönderi aslında oluşturulmuş: {s.url}")
                        return True
            except Exception as chk_e:
                print(f"[UYARI] Hata sonrası doğrulama yapılamadı: {chk_e}")
            # Emin olamıyorsak başarısız say ve tekrar denemeye bırak
            return False

        # Diğer hatalarda text post fallback devre dışı
        return False
    finally:
        # Geçici dosyaları temizle
        try:
            if "temp_media" in media_path and os.path.exists(media_path):
                os.remove(media_path)
                print(f"[+] Geçici dosya temizlendi: {media_path}")
        except:
            pass

def load_posted_tweet_ids():
    """🧹 Daha önce gönderilmiş tweet ID'lerini veritabanından veya dosyadan yükle (memory optimized)"""
    # 1) Veritabanı kullanılabiliyorsa DB'den oku
    if USE_DB_FOR_POSTED_IDS:
        try:
            _ensure_posted_ids_table()
            ids = _db_load_posted_ids()
            # 🧹 Logging azaltıldı
            result = set(ids)
            # 🧹 Temizlik
            del ids
            return result
        except Exception as e:
            if FAIL_IF_DB_UNAVAILABLE:
                raise RuntimeError(f"DB gerekli ancak erişilemedi (load): {e}")
            # 🧹 Logging azaltıldı - sadece hata durumunda
    
    # 2) Dosya fallback - 🧹 Generator kullan
    posted_ids_file = "posted_tweet_ids.txt"
    alt_posted_ids_file = "posted_tweets_ids.txt"  # legacy/mistyped filename support
    posted_ids = set()
    
    def _read_file_lines(filename):
        """🧹 Generator - dosyayı satır satır oku"""
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    for line in f:
                        tweet_id = line.strip()
                        if tweet_id:
                            yield tweet_id
        except Exception:
            pass
    
    try:
        # Ana dosyayı oku
        for tweet_id in _read_file_lines(posted_ids_file):
            posted_ids.add(tweet_id)
        
        # Legacy dosyayı oku
        for tweet_id in _read_file_lines(alt_posted_ids_file):
            posted_ids.add(tweet_id)
            
    except Exception:
        pass  # 🧹 Logging azaltıldı
    
    return posted_ids

def save_posted_tweet_id(tweet_id):
    """Yeni gönderilmiş tweet ID'sini veritabanına veya dosyaya kaydet"""
    # 1) Veritabanı kullanılabiliyorsa önce DB'ye yaz
    if USE_DB_FOR_POSTED_IDS:
        try:
            _ensure_posted_ids_table()
            _db_save_posted_id(tweet_id)
            # Son 8 kaydı tut, eskilerini sil
            try:
                _db_prune_posted_ids_keep_latest(POSTED_IDS_RETENTION)
            except Exception as _prune_e:
                print(f"[UYARI] (DB) Prune başarısız: {_prune_e}")
            print(f"[+] (DB) Tweet ID kaydedildi: {tweet_id}")
            return
        except Exception as e:
            if FAIL_IF_DB_UNAVAILABLE:
                raise RuntimeError(f"DB gerekli ancak erişilemedi (save): {e}")
            print(f"[UYARI] (DB) Tweet ID kaydedilemedi, dosyaya düşülecek: {e}")
    # 2) Dosya fallback
    posted_ids_file = "posted_tweet_ids.txt"
    try:
        with open(posted_ids_file, 'a', encoding='utf-8') as f:
            f.write(f"{tweet_id}\n")
        # Dosyada da son 8 kaydı tut
        try:
            _file_prune_posted_ids_keep_latest(posted_ids_file, POSTED_IDS_RETENTION)
        except Exception as _fprune_e:
            print(f"[UYARI] (Fallback) Prune başarısız: {_fprune_e}")
        print(f"[+] (Fallback) Tweet ID dosyaya kaydedildi: {tweet_id}")
    except Exception as e:
        print(f"[UYARI] (Fallback) Tweet ID kaydedilirken hata: {e}")

############################################################
# Postgres helper functions for posted_tweet_ids persistence
############################################################
_POSTED_IDS_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS posted_tweet_ids (\n"
    "    id BIGINT PRIMARY KEY,\n"
    "    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()\n"
    ")"
)

def _db_prune_posted_ids_keep_latest(limit: int = 8):
    """posted_tweet_ids tablosunda yalnızca en yeni 'limit' kadar kaydı (created_at DESC) bırak."""
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM posted_tweet_ids
                    WHERE id NOT IN (
                        SELECT id FROM posted_tweet_ids
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                    )
                    """,
                    (limit,),
                )
    finally:
        conn.close()

def _file_prune_posted_ids_keep_latest(file_path: str = "posted_tweet_ids.txt", limit: int = 8):
    """Dosyada son 'limit' satırı koru, eskileri sil."""
    try:
        if not os.path.exists(file_path):
            return
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if len(lines) <= limit:
            return
        to_keep = lines[-limit:]
        with open(file_path, 'w', encoding='utf-8') as f:
            for tid in to_keep:
                f.write(f"{tid}\n")
        print(f"[+] (Prune) {file_path} son {limit} ID ile güncellendi")
    except Exception as e:
        print(f"[UYARI] (Prune) Dosya temizleme hatası: {e}")

# -------------------- Repost (bf6_tr) storage helpers --------------------
_POSTED_RT_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS posted_retweet_ids (\n"
    "    id BIGINT PRIMARY KEY,\n"
    "    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()\n"
    ")"
)

def _ensure_posted_retweet_ids_table():
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(_POSTED_RT_TABLE_SQL)
    finally:
        conn.close()

def _db_save_posted_retweet_id(tweet_id: str):
    try:
        id_int = int(str(tweet_id))
    except Exception:
        return
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO posted_retweet_ids (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (id_int,),
                )
    finally:
        conn.close()

def _db_prune_posted_retweets_keep_latest(limit: int = 3):
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM posted_retweet_ids
                    WHERE id NOT IN (
                        SELECT id FROM posted_retweet_ids
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                    )
                    """,
                    (limit,),
                )
    finally:
        conn.close()

def _file_prune_posted_retweets_keep_latest(file_path: str = "posted_retweet_ids.txt", limit: int = 3):
    try:
        if not os.path.exists(file_path):
            return
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if len(lines) <= limit:
            return
        to_keep = lines[-limit:]
        with open(file_path, 'w', encoding='utf-8') as f:
            for tid in to_keep:
                f.write(f"{tid}\n")
        print(f"[+] (Prune) {file_path} son {limit} RT ID ile güncellendi")
    except Exception as e:
        print(f"[UYARI] (Prune) RT dosya temizleme hatası: {e}")

def save_posted_retweet_id(tweet_id):
    """bf6_tr repost ID'sini kalıcı depoya yaz ve sadece son 3 kaydı tut."""
    if USE_DB_FOR_POSTED_IDS:
        try:
            _ensure_posted_retweet_ids_table()
            _db_save_posted_retweet_id(tweet_id)
            try:
                _db_prune_posted_retweets_keep_latest(3)
            except Exception as _rt_prune_e:
                print(f"[UYARI] (DB) RT prune başarısız: {_rt_prune_e}")
            print(f"[+] (DB) RT ID kaydedildi: {tweet_id}")
            return
        except Exception as e:
            if FAIL_IF_DB_UNAVAILABLE:
                raise RuntimeError(f"DB gerekli ancak erişilemedi (save RT): {e}")
            print(f"[UYARI] (DB) RT ID kaydedilemedi, dosyaya düşülecek: {e}")
    # Fallback file mode
    rt_file = "posted_retweet_ids.txt"
    try:
        with open(rt_file, 'a', encoding='utf-8') as f:
            f.write(f"{tweet_id}\n")
        try:
            _file_prune_posted_retweets_keep_latest(rt_file, 3)
        except Exception as _frt_e:
            print(f"[UYARI] (Fallback) RT prune başarısız: {_frt_e}")
        print(f"[+] (Fallback) RT ID dosyaya kaydedildi: {tweet_id}")
    except Exception as e:
        print(f"[UYARI] (Fallback) RT ID kaydedilirken hata: {e}")

def _db_connect():
    """🧹 Get a psycopg2 connection using DATABASE_URL (lazy import)"""
    # 🧹 Lazy import - sadece ihtiyaç duyulduğunda import et
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        raise RuntimeError("psycopg2 mevcut değil")
    
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env yok")
    
    # Sanitize value: strip spaces/newlines
    dsn = (DATABASE_URL or "").strip()
    # Strip accidental leading key e.g. "DATABASE_URL=postgres://..."
    if dsn.lower().startswith("database_url="):
        dsn = dsn.split("=", 1)[1].strip()
    # Strip surrounding quotes if present
    if (dsn.startswith('"') and dsn.endswith('"')) or (dsn.startswith("'") and dsn.endswith("'")):
        dsn = dsn[1:-1]
    
    # 🧹 Logging azaltıldı - debug log kaldırıldı
    # Connect
    conn = psycopg2.connect(dsn)
    return conn

def _ensure_posted_ids_table():
    """Ensure table exists."""
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(_POSTED_IDS_TABLE_SQL)
    finally:
        conn.close()

def _db_load_posted_ids():
    """Load all posted ids from DB as list of strings."""
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM posted_tweet_ids")
                rows = cur.fetchall()
                return [str(r[0]) for r in rows]
    finally:
        conn.close()

def _db_save_posted_id(tweet_id: str):
    """Insert id if not exists (id bigint)."""
    # Convert to int if possible; ignore if non-numeric
    try:
        id_int = int(str(tweet_id))
    except Exception:
        # store as bigint not possible; skip
        return
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO posted_tweet_ids (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (id_int,),
                )
    finally:
        conn.close()

def get_latest_tweets_with_retweet_check(count: int = 8):
    """🧹 TWSCRAPE ile tweet çekme (memory optimized)
    Sadece TWSCRAPE kullanır, fallback'ler kaldırıldı.
    Dönüş: list[{'id','text','created_at','media_urls'}]
    """
    try:
        # Global rate-limit uygula
        global LAST_REQUEST_TIME
        current_time = time.time()
        time_since_last_request = current_time - LAST_REQUEST_TIME
        if time_since_last_request < MIN_REQUEST_INTERVAL:
            wait_time = MIN_REQUEST_INTERVAL - time_since_last_request
            time.sleep(wait_time)
        LAST_REQUEST_TIME = time.time()

        def _twscrape_fetch_sync():
            async def _run():
                api = None
                user = None
                tweets_generator = None
                try:
                    api = await init_twscrape_api()
                    # Kullanıcıyı ID ile getir (daha güvenilir)
                    try:
                        user = await api.user_by_id(int(TWITTER_USER_ID))
                    except Exception as ue:
                        print(f"[HATA] user_by_id hatası: {ue} | ID={TWITTER_USER_ID}")
                        try:
                            nat = await api.pool.next_available_at("timeline")
                            print(f"[DIAG] next_available_at: {nat}")
                        except Exception as de:
                            print(f"[DIAG] next_available_at hatası: {de}")
                        return []
                    if not user:
                        print(f"[HATA] Twitter kullanıcısı bulunamadı: ID {TWITTER_USER_ID} | muhtemel neden: pasif hesap/oturum yok/yanlış ID")
                        try:
                            nat = await api.pool.next_available_at("timeline")
                            print(f"[DIAG] next_available_at: {nat}")
                        except Exception as de:
                            print(f"[DIAG] next_available_at hatası: {de}")
                        return []
                    
                    # 🧹 Generator kullan - büyük listeleri RAM'e yükleme
                    tweets_generator = api.user_tweets(user.id, limit=max(10, count * 3))
                    out = []
                    
                    async for tw in tweets_generator:
                        # Reply veya retweet olanları atla
                        if getattr(tw, 'inReplyToTweetId', None):
                            continue
                        if getattr(tw, 'retweetedTweet', None):
                            continue
                        # Alıntı (quote) tweet'leri atla
                        if getattr(tw, 'quotedTweet', None) or getattr(tw, 'isQuoted', False) or getattr(tw, 'isQuote', False):
                            continue

                        # Medya URL'lerini çıkar
                        media_urls = []
                        md = getattr(tw, 'media', None)
                        if md:
                            # 🧹 Lazy evaluation - sadece gerektiğinde işle
                            photos = getattr(md, 'photos', []) or []
                            for p in photos:
                                url = getattr(p, 'url', None)
                                if url:
                                    media_urls.append(url)
                            
                            videos = getattr(md, 'videos', []) or []
                            for v in videos:
                                variants = getattr(v, 'variants', []) or []
                                if variants:
                                    best = max(variants, key=lambda x: getattr(x, 'bitrate', 0))
                                    url = getattr(best, 'url', None)
                                    if url:
                                        media_urls.append(url)
                            
                            animated = getattr(md, 'animated', []) or []
                            for a in animated:
                                url = getattr(a, 'videoUrl', None)
                                if url:
                                    media_urls.append(url)
                            
                            # 🧹 Temizlik - kullanılmayan objeleri serbest bırak
                            del photos, videos, animated

                        tweet_data = {
                            'id': str(getattr(tw, 'id', getattr(tw, 'id_str', ''))),
                            'text': getattr(tw, 'rawContent', ''),
                            'created_at': getattr(tw, 'date', None),
                            'media_urls': media_urls,
                            'url': getattr(tw, 'url', None),
                        }
                        out.append(tweet_data)
                        
                        # 🧹 Temizlik
                        del media_urls, md, tweet_data
                        
                        if len(out) >= count:
                            break
                    
                    # Eskiden yeniye sırala
                    try:
                        out.sort(key=_tweet_sort_key, reverse=False)
                    except Exception:
                        pass
                    
                    return out
                except Exception as e:
                    return []
                finally:
                    # 🧹 Async generator düzgün kapat
                    try:
                        if 'tweets_generator' in locals() and tweets_generator is not None:
                            aclose = getattr(tweets_generator, 'aclose', None)
                            if callable(aclose):
                                await aclose()
                    except Exception:
                        pass
                    # 🧹 Temizlik - kullanılmayan objeleri serbest bırak
                    del api, user, tweets_generator

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(_run())
                return result
            finally:
                loop.close()
                # 🧹 Loop temizliği
                del loop

        # TWSCRAPE PRIMARY (fallback'ler kaldırıldı)
        normalized = _twscrape_fetch_sync()
        
        # 🧹 Temizlik
        del _twscrape_fetch_sync
        
        return normalized or []
        
    except Exception as e:
        return []

def main_loop():
    # Persistent storage ile posted tweet IDs'leri yükle
    posted_tweet_ids = load_posted_tweet_ids()
    # Compute high-watermark from persisted IDs
    try:
        _numeric_ids = [int(str(s)) for s in posted_tweet_ids if str(s).isdigit()]
        max_seen_id = max(_numeric_ids) if _numeric_ids else 0
    except Exception:
        max_seen_id = 0
    
    print(f"[+] Reddit Bot başlatılıyor...")
    print(f"[+] Subreddit: r/{SUBREDDIT}")
    print(f"[+] Twitter: @{TWITTER_SCREENNAME} (ID: {TWITTER_USER_ID})")
    print("[+] Retweet'ler otomatik olarak atlanacak")
    print(f"[+] Şu ana kadar {len(posted_tweet_ids)} tweet işlenmiş")
    # Diagnostics for queue/manifest mode
    try:
        print(f"[DIAG] USE_EXTERNAL_QUEUE={USE_EXTERNAL_QUEUE} | MANIFEST_TEST_FIRST_ITEM={MANIFEST_TEST_FIRST_ITEM}")
        if MANIFEST_URL:
            print(f"[DIAG] MANIFEST_URL={MANIFEST_URL}")
        else:
            print(f"[DIAG] MANIFEST_PATH={MANIFEST_PATH}")
    except Exception:
        pass
    
    # .env ile verilen özel tweet ID'lerini (bir kereye mahsus) işle
    try:
        env_ids: list[str] = []
        if PROCESS_TWEET_ID:
            env_ids.append(PROCESS_TWEET_ID)
        if PROCESS_TWEET_IDS:
            env_ids.extend([s.strip() for s in PROCESS_TWEET_IDS.split(',') if s.strip()])
        # Dedupe while preserving order
        seen = set()
        env_ids = [x for x in env_ids if not (x in seen or seen.add(x))]
        for eid in env_ids:
            if eid in PROCESSED_ENV_IDS:
                continue
            if eid in posted_tweet_ids:
                print(f"[ENV] Tweet ID zaten işlenmiş görünüyor, atlanıyor: {eid}")
                PROCESSED_ENV_IDS.add(eid)
                continue
            print(f"[ENV] Özel tweet ID işleniyor: {eid}")
            res = process_specific_tweet(eid)
            ok = isinstance(res, dict) and res.get("processed") is True
            reason = None if ok else (res.get("reason") if isinstance(res, dict) else "unknown")
            if ok:
                posted_tweet_ids.add(eid)
                save_posted_tweet_id(eid)
                print(f"[ENV] Başarılı: {eid}")
            else:
                print(f"[ENV] İşlenemedi: {eid} | sebep: {reason}")
            PROCESSED_ENV_IDS.add(eid)
    except Exception as _env_proc_err:
        print(f"[UYARI] .env tweet ID işleme hatası: {_env_proc_err}")
    
    while True:
        try:
            print("\n" + "="*50)
            print(f"[+] Tweet kontrol ediliyor... ({time.strftime('%Y-%m-%d %H:%M:%S')})")
            # Önce planlı haftalık gönderiyi kontrol et/oluştur
            _create_and_pin_weekly_post_if_due()

            # External queue modu: manifest'ten zaman gelenleri post et ve döngüye devam et
            if USE_EXTERNAL_QUEUE:
                print("[MODE] USE_EXTERNAL_QUEUE=true -> Manifest işleniyor (twscrape atlanır)")
                process_external_due_items(posted_tweet_ids)
                # Döngü beklemesi
                print(f"\n[+] Sonraki kontrol: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + 300))}")
                print("⏳ 5 dakika bekleniyor...")
                time.sleep(300)
                continue
            
            # Son 8 tweet'i al ve retweet kontrolü yap (daha fazla tweet kontrol et)
            tweets_data = get_latest_tweets_with_retweet_check(8)
            
            if isinstance(tweets_data, dict) and "error" in tweets_data:
                print(f"[!] TWSCRAPE hatası: {tweets_data['error']}")
                time.sleep(MIN_REQUEST_INTERVAL)
                continue
            elif not tweets_data:
                print("[!] Tweet bulunamadı veya TWSCRAPE hatası.")
                time.sleep(MIN_REQUEST_INTERVAL)
                continue
            
            tweets = tweets_data if isinstance(tweets_data, list) else tweets_data.get("tweets", [])
            if not tweets:
                print("[!] İşlenecek tweet bulunamadı.")
                time.sleep(MIN_REQUEST_INTERVAL)
                continue
            
            # Eskiden yeniye işle - created_at/id'e göre deterministik sırala
            def _tweet_sort_key(td):
                # created_at zamanı (varsa) -> epoch saniyesi
                ts = td.get('created_at') if isinstance(td, dict) else None
                tsv = 0.0
                try:
                    if hasattr(ts, 'timestamp'):
                        tsv = float(ts.timestamp())
                    elif isinstance(ts, (int, float)):
                        tsv = float(ts)
                except Exception:
                    tsv = 0.0
                # numeric tweet id (Snowflake) -> daha büyük daha yeni
                idv = 0
                if isinstance(td, dict):
                    for k in ('id', 'tweet_id', 'id_str', 'rest_id'):
                        v = td.get(k)
                        if v is None:
                            continue
                        s = str(v).strip()
                        if s.isdigit():
                            try:
                                idv = int(s)
                                break
                            except Exception:
                                pass
                return (tsv, idv)

            try:
                tweets.sort(key=_tweet_sort_key, reverse=False)
            except Exception:
                # Her ihtimale karşı önce reverse deneyip sonra işle
                tweets = list(reversed(tweets))
            print(f"[+] {len(tweets)} tweet bulundu, eskiden yeniye doğru işlenecek...")
            
            # Her tweet'i eskiden yeniye doğru işle
            for tweet_index, tweet_data in enumerate(tweets, 1):
                # ID normalizasyonu
                tweet_id = (
                    (tweet_data.get("tweet_id") if isinstance(tweet_data, dict) else None)
                    or (tweet_data.get("id") if isinstance(tweet_data, dict) else None)
                    or (tweet_data.get("id_str") if isinstance(tweet_data, dict) else None)
                    or (tweet_data.get("rest_id") if isinstance(tweet_data, dict) else None)
                )
                if tweet_id is not None:
                    tweet_id = str(tweet_id).strip()
                if not tweet_id:
                    print(f"[HATA] Tweet {tweet_index}/{len(tweets)} - Tweet ID bulunamadı!")
                    continue
                # Engelli tweet ID'lerini atla ve işlenmiş olarak kaydet
                if tweet_id in EXCLUDED_TWEET_IDS:
                    print(f"[SKIP] Engelli tweet ID (gönderilmeyecek): {tweet_id}")
                    posted_tweet_ids.add(tweet_id)
                    save_posted_tweet_id(tweet_id)
                    # Update watermark if needed
                    try:
                        if HIGH_WATERMARK_ENABLED and str(tweet_id).isdigit():
                            ti = int(tweet_id)
                            if ti > max_seen_id:
                                max_seen_id = ti
                    except Exception:
                        pass
                    continue
                
                # High-watermark filter: skip anything older/equal than last seen
                if HIGH_WATERMARK_ENABLED and max_seen_id:
                    try:
                        if str(tweet_id).isdigit() and int(tweet_id) <= max_seen_id:
                            print(f"[SKIP] High-watermark nedeniyle atlandı (<= {max_seen_id}): {tweet_id}")
                            continue
                    except Exception:
                        pass
                
                if tweet_id in posted_tweet_ids:
                    print(f"[!] Tweet {tweet_index}/{len(tweets)} zaten işlendi: {tweet_id}")
                    continue
                
                # Ek güvenlik: detay sorgusu ile RT/Quote ise atla
                try:
                    if _is_retweet_or_quote_by_id(tweet_id):
                        print(f"[SKIP] Retweet/Quote tespit edildi, atlanıyor: {tweet_id}")
                        # RT/Quote'lar posted olarak işaretlenmesin
                        # Yüksek su seviyesi (watermark) için güncelleme yapılabilir
                        try:
                            if HIGH_WATERMARK_ENABLED and str(tweet_id).isdigit():
                                ti = int(tweet_id)
                                if ti > max_seen_id:
                                    max_seen_id = ti
                        except Exception:
                            pass
                        continue
                except Exception:
                    pass

                print(f"[+] Tweet {tweet_index}/{len(tweets)} işleniyor: {tweet_id}")
                posted_tweet_ids.add(tweet_id)
                save_posted_tweet_id(tweet_id)
                print(f"[+] Tweet ID kaydedildi (işlem öncesi): {tweet_id}")
                print(f"[+] Tweet linki: https://x.com/{TWITTER_SCREENNAME}/status/{tweet_id}")
                # Update watermark after save
                try:
                    if HIGH_WATERMARK_ENABLED and str(tweet_id).isdigit():
                        ti = int(tweet_id)
                        if ti > max_seen_id:
                            max_seen_id = ti
                except Exception:
                    pass
                
                # Tweet metni ve çeviri
                text = tweet_data.get("text", "")
                print(f"[+] Orijinal Tweet: {text[:100]}{'...' if len(text) > 100 else ''}")
                cleaned_text = clean_tweet_text(text)
                print(f"[+] Temizlenmiş Tweet: {cleaned_text[:100]}{'...' if len(cleaned_text) > 100 else ''}")
                # Countdown filter: skip if pattern like 'XX days until' and XX > 10
                try:
                    cd_days = _extract_countdown_days(text) or _extract_countdown_days(cleaned_text)
                except Exception:
                    cd_days = None
                if cd_days is not None and cd_days > 10:
                    print(f"[SKIP] Geri sayım ({cd_days} gün) > 10: {tweet_id}")
                    continue
                
                # Medya çıkarımı (önce video var mı tespit et)
                print("[+] Medya URL'leri çıkarılıyor...")
                media_urls = get_media_urls_from_tweet_data(tweet_data)
                media_files = []
                
                image_urls: list[str] = []
                video_urls: list[str] = []
                for media_url in media_urls:
                    u = media_url.lower()
                    is_image = (
                        any(ext in u for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']) or
                        'format=jpg' in u or 'format=jpeg' in u or 'format=png' in u or 'format=webp' in u or
                        'pbs.twimg.com/media' in u
                    )
                    is_video = ('.mp4' in u or 'format=mp4' in u or 'video.twimg.com' in u)
                    if is_image:
                        image_urls.append(media_url)
                    elif is_video:
                        video_urls.append(media_url)
                print(f"[+] Medya analizi: {len(image_urls)} resim, {len(video_urls)} video")

                # Medya bağlamıyla çeviri (reload->Şarjör vb.)
                translated = translate_text(cleaned_text, has_video=bool(video_urls))
                if translated:
                    print(f"[+] Çeviri: {translated[:100]}{'...' if len(translated) > 100 else ''}")
                else:
                    print(f"[UYARI] Çeviri başarısız, tweet atlanıyor: {tweet_id}")
                    continue
                
                # Resimler
                if len(image_urls) > 1:
                    print("[+] Birden fazla resim tespit edildi, toplu indirme başlatılıyor...")
                    downloaded_images = download_multiple_images(image_urls, tweet_id)
                    media_files.extend(downloaded_images)
                elif len(image_urls) == 1:
                    media_url = image_urls[0]
                    ext = os.path.splitext(media_url)[1].split("?")[0] or ".jpg"
                    filename = f"temp_image_{tweet_id}_0{ext}"
                    print(f"[+] Tek resim indiriliyor: {media_url[:50]}...")
                    path = download_media(media_url, filename)
                    if path:
                        media_files.append(path)
                        print(f"[+] Resim hazır: {path}")
                
                # Videolar (twscrape üzerinden en kaliteli varyant)
                if video_urls:
                    try:
                        filename = f"temp_video_{tweet_id}_0.mp4"
                        print("[+] En kaliteli video indiriliyor (twscrape/HLS öncelikli)...")
                        path = download_best_video_for_tweet(tweet_id, filename)
                        if path:
                            # Süre kontrolü: Reddit limitini aşarsa tüm tweet'i atla
                            dur = get_video_duration_seconds(path)
                            if dur is not None and dur > REDDIT_MAX_VIDEO_SECONDS:
                                print(f"[SKIP] Video çok uzun ({dur:.1f}s > {REDDIT_MAX_VIDEO_SECONDS}s). Tweet atlanıyor: {tweet_id}")
                                try:
                                    if os.path.exists(path):
                                        os.remove(path)
                                except Exception:
                                    pass
                                # Önceden indirilen medya (resimler) varsa temizle
                                for fpath in media_files:
                                    try:
                                        if os.path.exists(fpath):
                                            os.remove(fpath)
                                    except Exception:
                                        pass
                                # Sonraki tweet'e geç
                                continue

                            converted = f"converted_{filename}"
                            print(f"[+] Video dönüştürülüyor: {path} -> {converted}")
                            converted_path = convert_video_to_reddit_format(path, converted)
                            if converted_path:
                                media_files.append(converted_path)
                                print(f"[+] Video dönüştürme başarılı: {converted_path}")
                            else:
                                print("[!] Video dönüştürme başarısız")
                            if os.path.exists(path):
                                os.remove(path)
                        else:
                            print("[!] Video indirilemedi (best-quality yoluyla)")
                    except Exception as media_e:
                        print(f"[HATA] Video işleme hatası: {media_e}")
                
                print(f"[+] Toplam {len(media_files)} medya dosyası hazır")
                
                # Medya doğrulaması
                original_text = tweet_data.get("text", "")
                has_media_in_original = any(ind in original_text for ind in ['pic.twitter.com', 'video.twitter.com', 'pbs.twimg.com'])
                if has_media_in_original and len(media_files) == 0:
                    print(f"[UYARI] Orijinal tweet'te medya var ama indirilemedi, post atlanıyor: {tweet_id}")
                    for fpath in media_files:
                        try:
                            if os.path.exists(fpath):
                                os.remove(fpath)
                        except Exception:
                            pass
                    continue
                
                # Post gönderme
                candidates = [
                    (translated or "").strip(),
                    (cleaned_text or "").strip(),
                    (text or "").strip(),
                ]
                chosen_text = next((c for c in candidates if c), "")
                if not chosen_text:
                    chosen_text = f"@{TWITTER_SCREENNAME} paylaşımı - {tweet_id}"
                title_to_use, remainder_to_post = smart_split_title(chosen_text, 300)
                print(f"[+] Kullanılacak başlık ({len(title_to_use)}): {title_to_use[:80]}{'...' if len(title_to_use) > 80 else ''}")
                if remainder_to_post:
                    print(f"[+] Başlığın kalan kısmı ({len(remainder_to_post)} karakter) gönderi açıklaması/yorum olarak eklenecek")
                print("[+] Reddit'e post gönderiliyor...")
                success = submit_post(title_to_use, media_files, text, remainder_text=remainder_to_post)
                if success:
                    print(f"[+] Tweet başarıyla işlendi: {tweet_id}")
                else:
                    print(f"[UYARI] Tweet işlenemedi ama ID zaten kaydedildi: {tweet_id}")
                    for fpath in media_files:
                        try:
                            if os.path.exists(fpath):
                                os.remove(fpath)
                                print(f"[+] Geçici dosya silindi: {fpath}")
                        except Exception as cleanup_e:
                            print(f"[UYARI] Dosya silinirken hata: {cleanup_e}")
                
                # Tweet'ler arası 5 dakika bekle (son tweet hariç)
                if tweet_index < len(tweets):
                    print(f"[+] Sonraki tweet için 5 dakika bekleniyor... ({tweet_index}/{len(tweets)} tamamlandı)")
                    time.sleep(300)
            # EK: TheBFWire akışındaki @bf6_tr retweet'lerini (8/8 tamamlandıysa) aynı mantıkla işle
            try:
                if ENABLE_SECONDARY_RETWEETS and isinstance(tweets, list) and len(tweets) >= 8:
                    print("\n" + "-"*50)
                    print("[+] Ek görev: @bf6_tr retweet'leri işleniyor (aynı pipeline)...")
                    rt_list = get_latest_bf6_retweets(3)
                    if not rt_list:
                        print("[INFO] İşlenecek @bf6_tr retweet'i bulunamadı")
                    else:
                        print(f"[+] {len(rt_list)} retweet bulundu (eskiden yeniye işlenecek)")
                        for rt_index, tweet_data in enumerate(rt_list, 1):
                            tweet_id = (
                                (tweet_data.get("tweet_id") if isinstance(tweet_data, dict) else None)
                                or (tweet_data.get("id") if isinstance(tweet_data, dict) else None)
                                or (tweet_data.get("id_str") if isinstance(tweet_data, dict) else None)
                                or (tweet_data.get("rest_id") if isinstance(tweet_data, dict) else None)
                            )
                            if tweet_id is not None:
                                tweet_id = str(tweet_id).strip()
                            if not tweet_id:
                                print(f"[HATA] RT {rt_index}/{len(rt_list)} - Tweet ID bulunamadı!")
                                continue
                            if tweet_id in EXCLUDED_TWEET_IDS:
                                print(f"[SKIP] Engelli tweet ID (RT): {tweet_id}")
                                posted_tweet_ids.add(tweet_id)
                                save_posted_tweet_id(tweet_id)
                                # Ayrı repost storage'ına da yaz ve 3'e prune et
                                save_posted_retweet_id(tweet_id)
                                continue
                            if tweet_id in posted_tweet_ids:
                                print(f"[!] RT {rt_index}/{len(rt_list)} zaten işlendi: {tweet_id}")
                                continue
                            print(f"[+] RT {rt_index}/{len(rt_list)} işleniyor: {tweet_id}")
                            posted_tweet_ids.add(tweet_id)
                            save_posted_tweet_id(tweet_id)
                            # Ayrı repost storage'ına da yaz ve 3'e prune et
                            save_posted_retweet_id(tweet_id)
                            print(f"[+] RT ID kaydedildi (işlem öncesi): {tweet_id}")
                            print(f"[+] RT linki: https://x.com/{TWITTER_SCREENNAME}/status/{tweet_id}")

                            text = tweet_data.get("text", "")
                            print(f"[+] Orijinal RT Metin: {text[:100]}{'...' if len(text) > 100 else ''}")
                            cleaned_text = clean_tweet_text(text)
                            print(f"[+] Temizlenmiş RT Metin: {cleaned_text[:100]}{'...' if len(cleaned_text) > 100 else ''}")
                            # Countdown filter for RT: skip if 'XX days until' and XX > 10
                            try:
                                cd_days = _extract_countdown_days(text) or _extract_countdown_days(cleaned_text)
                            except Exception:
                                cd_days = None
                            if cd_days is not None and cd_days > 10:
                                print(f"[SKIP] RT Geri sayım ({cd_days} gün) > 10: {tweet_id}")
                                continue
                            # 'Kaynak' BAŞLIĞI: yalnızca temizleme sonrası metin tamamen boşsa
                            fallback_source_title = None
                            if not cleaned_text.strip():
                                rt_url = tweet_data.get("url") or f"https://x.com/i/web/status/{tweet_id}"
                                rt_author = extract_username_from_tweet_url(rt_url)
                                fallback_source_title = f"Kaynak: @{rt_author}"
                                translated = None
                                print(f"[INFO] RT temizlenince metin boş, başlık kaynak olarak ayarlanacak: {fallback_source_title}")
                            else:
                                # Önce medya çıkar ve video var mı tespit et
                                print("[+] RT Medya URL'leri çıkarılıyor...")
                                media_urls = get_media_urls_from_tweet_data(tweet_data)
                                media_files = []
                                image_urls = []
                                video_urls = []
                                for media_url in media_urls:
                                    u = media_url.lower()
                                    is_image = (
                                        any(ext in u for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']) or
                                        'format=jpg' in u or 'format=jpeg' in u or 'format=png' in u or 'format=webp' in u or
                                        'pbs.twimg.com/media' in u
                                    )
                                    is_video = ('.mp4' in u or 'format=mp4' in u or 'video.twimg.com' in u)
                                    if is_image:
                                        image_urls.append(media_url)
                                    elif is_video:
                                        video_urls.append(media_url)
                                print(f"[+] RT Medya analizi: {len(image_urls)} resim, {len(video_urls)} video")
                                translated = translate_text(cleaned_text, has_video=bool(video_urls))
                            if translated:
                                print(f"[+] RT Çeviri: {translated[:100]}{'...' if len(translated) > 100 else ''}")
                            elif fallback_source_title:
                                # Çeviri yok ama kaynak başlığı mevcut; devam edilecek
                                print("[INFO] RT çeviri atlandı, kaynak başlığı kullanılacak")
                            else:
                                print(f"[UYARI] RT çeviri başarısız, atlanıyor: {tweet_id}")
                                continue

                            if len(image_urls) > 1:
                                print("[+] RT: Birden fazla resim tespit edildi, toplu indirme başlatılıyor...")
                                downloaded_images = download_multiple_images(image_urls, tweet_id)
                                media_files.extend(downloaded_images)
                            elif len(image_urls) == 1:
                                media_url = image_urls[0]
                                ext = os.path.splitext(media_url)[1].split("?")[0] or ".jpg"
                                filename = f"temp_image_{tweet_id}_0{ext}"
                                print(f"[+] RT Tek resim indiriliyor: {media_url[:50]}...")
                                path = download_media(media_url, filename)
                                if path:
                                    media_files.append(path)
                                    print(f"[+] RT Resim hazır: {path}")

                            if video_urls:
                                try:
                                    filename = f"temp_video_{tweet_id}_0.mp4"
                                    print("[+] RT En kaliteli video indiriliyor (twscrape/HLS öncelikli)...")
                                    path = download_best_video_for_tweet(tweet_id, filename)
                                    if path:
                                        # Süre kontrolü: Reddit limitini aşarsa tüm RT tweet'i atla
                                        dur = get_video_duration_seconds(path)
                                        if dur is not None and dur > REDDIT_MAX_VIDEO_SECONDS:
                                            print(f"[SKIP] RT Video çok uzun ({dur:.1f}s > {REDDIT_MAX_VIDEO_SECONDS}s). RT atlanıyor: {tweet_id}")
                                            try:
                                                if os.path.exists(path):
                                                    os.remove(path)
                                            except Exception:
                                                pass
                                            for fpath in media_files:
                                                try:
                                                    if os.path.exists(fpath):
                                                        os.remove(fpath)
                                                except Exception:
                                                    pass
                                            # Bir sonraki RT'ye geç
                                            continue

                                        converted = f"converted_{filename}"
                                        print(f"[+] RT Video dönüştürülüyor: {path} -> {converted}")
                                        converted_path = convert_video_to_reddit_format(path, converted)
                                        if converted_path:
                                            media_files.append(converted_path)
                                            print(f"[+] RT Video dönüştürme başarılı: {converted_path}")
                                        else:
                                            print("[!] RT Video dönüştürme başarısız")
                                        if os.path.exists(path):
                                            os.remove(path)
                                    else:
                                        print("[!] RT Video indirilemedi (best-quality yoluyla)")
                                except Exception as media_e:
                                    print(f"[HATA] RT Video işleme hatası: {media_e}")

                            print(f"[+] RT Toplam {len(media_files)} medya dosyası hazır")

                            original_text = tweet_data.get("text", "")
                            has_media_in_original = any(ind in original_text for ind in ['pic.twitter.com', 'video.twitter.com', 'pbs.twimg.com'])
                            if has_media_in_original and len(media_files) == 0:
                                print(f"[UYARI] RT tweet'te medya var ama indirilemedi, atlanıyor: {tweet_id}")
                                for fpath in media_files:
                                    try:
                                        if os.path.exists(fpath):
                                            os.remove(fpath)
                                    except Exception:
                                        pass
                                continue

                            # Raw 'text' KULLANMA: link sızmasını önlemek için sadece çeviri veya temiz metin kullan
                            candidates = [
                                (translated or "").strip(),
                                (cleaned_text or "").strip(),
                            ]
                            chosen_text = next((c for c in candidates if c), "")
                            if not chosen_text:
                                # Sadece temizlenmiş metin boş olduğunda oluşturulan kaynak başlığını kullan
                                if 'fallback_source_title' in locals() and fallback_source_title:
                                    chosen_text = fallback_source_title
                                else:
                                    # Eski davranış: genel fallback (Kaynak kullanma!)
                                    chosen_text = f"@{TWITTER_SCREENNAME} paylaşımı - {tweet_id}"
                            title_to_use, remainder_to_post = smart_split_title(chosen_text, 300)
                            print(f"[+] RT Kullanılacak başlık ({len(title_to_use)}): {title_to_use[:80]}{'...' if len(title_to_use) > 80 else ''}")
                            if remainder_to_post:
                                print(f"[+] RT Başlığın kalan kısmı ({len(remainder_to_post)} karakter) gönderi açıklaması/yorum olarak eklenecek")
                            print("[+] RT Reddit'e post gönderiliyor...")
                            success = submit_post(title_to_use, media_files, text, remainder_text=remainder_to_post)
                            if success:
                                print(f"[+] RT başarıyla işlendi: {tweet_id}")
                            else:
                                print(f"[UYARI] RT işlenemedi ama ID zaten kaydedildi: {tweet_id}")
                                for fpath in media_files:
                                    try:
                                        if os.path.exists(fpath):
                                            os.remove(fpath)
                                            print(f"[+] RT Geçici dosya silindi: {fpath}")
                                    except Exception as cleanup_e:
                                        print(f"[UYARI] RT dosya silinirken hata: {cleanup_e}")
                            if rt_index < len(rt_list):
                                print(f"[+] Sonraki RT için 5 dakika bekleniyor... ({rt_index}/{len(rt_list)} tamamlandı)")
                                time.sleep(300)
            except Exception as _rt_err:
                print(f"[UYARI] @bf6_tr retweet işleme hatası: {_rt_err}")
        except Exception as loop_e:
            print(f"[HATA] Ana döngü hatası: {loop_e}")
            import traceback
            traceback.print_exc()
        
        # Dış döngü beklemesi: 5 dakika
        print(f"\n[+] Sonraki kontrol: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + 300))}")
        print("⏳ 5 dakika bekleniyor...")
        time.sleep(300)

if __name__ == "__main__":
    if os.getenv("LOCAL_ONLY"):
        # Sadece iş döngüsünü çalıştır
        try:
            main_loop()
        except KeyboardInterrupt:
            pass
    else:
        # 🧹 Lazy import ve initialization
        try:
            import uvicorn
        except ImportError:
            print("[HATA] uvicorn mevcut değil")
            sys.exit(1)
        # FastAPI app'i initialize et
        app = _init_fastapi()
        # Lokal geliştirme/test için HTTP sunucusunu ayağa kaldır
        port = int(os.getenv("PORT", "8000"))
        uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
