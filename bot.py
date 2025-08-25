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
from twscrape import API, gather
from types import SimpleNamespace
# Pnytter opsiyonel (pydantic çakışması nedeniyle requirements dışına alındı)
try:
    from pnytter import Pnytter
    PNYTTER_AVAILABLE = True
except Exception:
    PNYTTER_AVAILABLE = False
from google import genai
from google.genai import types

# FastAPI for web service
import threading
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn
import psycopg2
from psycopg2.extras import RealDictCursor

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

# Nitter configuration - Using twiiit.com for dynamic instance selection + working instances
_DEFAULT_NITTER_INSTANCES = [
    "https://twiiit.com",           # Dynamic service that redirects to working instances
    "https://xcancel.com",          # Backup - most reliable RSS
    "https://nitter.privacydev.net", # Often working
    "https://nitter.poast.org",     # Alternative instance
    "https://nitter.it",            # Italian instance
    "https://nitter.cz",            # Czech instance
    "https://nitter.net",           # Original domain fallback
]

# Circuit breaker for failing instances
_INSTANCE_FAILURES = {}
_FAILURE_THRESHOLD = 3
_COOLDOWN_PERIOD = 300  # 5 minutes
# Allow override via env: NITTER_INSTANCES=https://a,https://b
_env_instances = os.getenv("NITTER_INSTANCES", "").strip()
if _env_instances:
    NITTER_INSTANCES = [u.strip() for u in _env_instances.split(",") if u.strip()]
else:
    NITTER_INSTANCES = _DEFAULT_NITTER_INSTANCES[:]
CURRENT_NITTER_INDEX = 0
TWITTER_SCREENNAME = "TheBFWire"
NITTER_REQUEST_DELAY = 15  # seconds between requests (artırıldı)
MAX_RETRIES = 2  # Maximum number of retries for failed requests (azaltıldı)
MIN_REQUEST_INTERVAL = 30  # Minimum seconds between any requests
LAST_REQUEST_TIME = 0  # Son istek zamanı
TWSCRAPE_DETAIL_TIMEOUT = 8  # seconds to wait for tweet_details before skipping

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
    """Instance için session al veya yeni oluştur"""
    global SESSION_POOL, SESSION_LAST_USED
    
    current_time = time.time()
    
    # Eski session'ları temizle
    expired_keys = []
    for key, last_used in SESSION_LAST_USED.items():
        if current_time - last_used > MAX_SESSION_AGE:
            expired_keys.append(key)
    
    for key in expired_keys:
        if key in SESSION_POOL:
            SESSION_POOL[key].close()
            del SESSION_POOL[key]
        del SESSION_LAST_USED[key]
    
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
                print(f"[+] Session proxy ayarlandı: {instance_url}")
            else:
                print(f"[UYARI] Proxy başarısız, direkt bağlantı kullanılıyor")
        
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
    # RT @TheBFWire: ifadesini kaldır
    text = re.sub(r'^RT @TheBFWire:\s*', '', text)
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
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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
        twscrape_api = API(ACCOUNTS_DB_PATH)
        print("[+] twscrape API başlatıldı")
    return twscrape_api

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


def _fallback_pnytter_tweets(count=3, retry_count=0):
    """Pnytter fallback fonksiyonu - Twint başarısız olursa kullanılır"""
    print("[+] Pnytter fallback başlatılıyor...")
    
    try:
        # Ana instance'ları ekle (opsiyonel)
        if not PNYTTER_AVAILABLE:
            print("[INFO] Pnytter mevcut değil, fallback atlanıyor")
            return []
        pnytter = Pnytter(nitter_instances=[NITTER_INSTANCES[0]])
        
        # Diğer instance'ları ekle (times parametresi ile güvenilirlik artır)
        for instance in NITTER_INSTANCES[1:]:
            pnytter.add_instance(instance, times=2)
        
        print(f"[+] Pnytter başlatıldı, {len(NITTER_INSTANCES)} instance kullanılıyor")
        
        # Tweet'leri çek (filter_from ve filter_to parametreleri ekle)
        from datetime import datetime, timedelta
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        tweets = pnytter.get_user_tweets_list(TWITTER_SCREENNAME, 
                                            filter_from=week_ago.strftime("%Y-%m-%d"),
                                            filter_to=today.strftime("%Y-%m-%d"))
        
        if not tweets:
            print("[UYARI] Pnytter ile tweet bulunamadı, RSS fallback'e geçiliyor...")
            return _fallback_rss_tweets(count, retry_count)
        
        print(f"[+] Pnytter ile {len(tweets)} tweet bulundu")
        
        # Tweet'leri filtrele ve medya URL'lerini çıkar
        filtered_tweets = []
        for i, tweet in enumerate(tweets[:count * 2]):  # Daha fazla tweet al, filtreleme için
            # Debug: tweet obje yapısını göster (sadece ilk tweet için)
            if i == 0:
                print(f"[DEBUG] twscrape Tweet {i+1} type: {type(tweet)}")
                print(f"[DEBUG] twscrape Tweet {i+1} attributes: {[attr for attr in dir(tweet) if not attr.startswith('_')]}")
                if hasattr(tweet, '__dict__'):
                    print(f"[DEBUG] twscrape Tweet {i+1} dict keys: {list(tweet.__dict__.keys())}")
                elif isinstance(tweet, dict):
                    print(f"[DEBUG] twscrape Tweet {i+1} dict keys: {list(tweet.keys())}")
                    
                # Test farklı ID alanları
                id_fields = ['id', 'id_str', 'tweetId', 'tweet_id', 'restId', 'rest_id']
                for field in id_fields:
                    if hasattr(tweet, field):
                        value = getattr(tweet, field)
                        print(f"[DEBUG] Found {field}: {value}")
                    elif isinstance(tweet, dict) and field in tweet:
                        print(f"[DEBUG] Found {field}: {tweet[field]}")
                    print(f"[DEBUG] twscrape Tweet {i+1} keys: {tweet.keys()}")
                    print(f"[DEBUG] twscrape Tweet {i+1} sample: {list(tweet.items())[:5]}")
            # Debug: tweet obje yapısını göster (sadece ilk tweet için)
            if i == 0:
                print(f"[DEBUG] Tweet {i+1} attributes: {dir(tweet)}")
                print(f"[DEBUG] Tweet {i+1} type: {type(tweet)}")
                if hasattr(tweet, '__dict__'):
                    print(f"[DEBUG] Tweet {i+1} dict: {tweet.__dict__}")
                elif isinstance(tweet, dict):
                    print(f"[DEBUG] Tweet {i+1} keys: {tweet.keys()}")
                    print(f"[DEBUG] Tweet {i+1} sample: {list(tweet.items())[:5]}")
            # Retweet kontrolü
            if hasattr(tweet, 'text') and tweet.text:
                if tweet.text.startswith('RT @') or 'RT @' in tweet.text:
                    print(f"[SKIP] Retweet atlandı: {tweet.tweet_id}")
                    continue
                
                # Pin kontrolü
                if 'pinned' in tweet.text.lower() or 'sabitlenmiş' in tweet.text.lower():
                    print(f"[SKIP] Pin tweet atlandı: {tweet.tweet_id}")
                    continue
            
            # Medya URL'lerini çıkar
            media_urls = []
            if hasattr(tweet, 'tweet_id'):
                # Her instance'ı dene
                for instance in NITTER_INSTANCES:
                    try:
                        instance_media = _fetch_media_from_nitter_html(instance, TWITTER_SCREENNAME, str(tweet.tweet_id))
                        if instance_media:
                            media_urls.extend(instance_media)
                            break
                    except Exception as e:
                        print(f"[UYARI] {instance} medya çekme hatası: {e}")
                        continue
            
            # Tweet objesini uygun formata çevir
            tweet_data = {
                'id': tweet.tweet_id if hasattr(tweet, 'tweet_id') else None,
                'text': tweet.text if hasattr(tweet, 'text') else '',
                'created_at': tweet.created_on if hasattr(tweet, 'created_on') else None,
                'media_urls': media_urls,
                'stats': {
                    'retweet_count': tweet.stats.retweets if hasattr(tweet, 'stats') and hasattr(tweet.stats, 'retweets') else 0,
                    'favorite_count': tweet.stats.likes if hasattr(tweet, 'stats') and hasattr(tweet.stats, 'likes') else 0,
                    'reply_count': tweet.stats.comments if hasattr(tweet, 'stats') and hasattr(tweet.stats, 'comments') else 0,
                }
            }
            
            filtered_tweets.append(tweet_data)
            
            if len(filtered_tweets) >= count:
                break
        
        print(f"[+] {len(filtered_tweets)} tweet filtrelendi ve hazırlandı")
        return filtered_tweets
        
    except Exception as e:
        print(f"[HATA] Pnytter hatası: {e}")
        print("[+] RSS fallback'e geçiliyor...")
        return _fallback_rss_tweets(count, retry_count)

def _fallback_rss_tweets(count=3, retry_count=0):
    """RSS fallback fonksiyonu - Pnytter başarısız olursa kullanılır"""
    print("[+] RSS fallback başlatılıyor...")
    
    def _normalize_urls(seq):
        urls = []
        for v in (seq or []):
            if isinstance(v, str):
                urls.append(v)
            elif isinstance(v, dict):
                for k in ("url", "src", "href"):
                    if k in v:
                        urls.append(v[k])
                        break
        return urls

    # 1) Pnytter ile dene (instance'ları tek tek dene, sırayı karıştır ama tercih edilenleri öncele)
    try:
        from pnytter import Pnytter
        print("[+] Pnytter ile tweetler çekiliyor")
        # Prefer first three working instances, then randomize the rest
        preferred = NITTER_INSTANCES[:3]
        others = NITTER_INSTANCES[3:]
        random.shuffle(others)
        try_order = [*preferred, *others]

        from datetime import datetime, timedelta
        to_dt = datetime.utcnow() + timedelta(days=1)  # Tomorrow to ensure we get today's tweets
        from_dt = datetime.utcnow() - timedelta(days=2)  # Last 2 days to get recent tweets

        tweets = []

        def _is_reply_text(txt: str) -> bool:
            t = (txt or "").strip()
            # Yanıt tespiti: @ ile başlayan veya yaygın yanıt kalıpları
            if not t:
                return False
            if t.startswith('@'):
                return True
            low = t.lower()
            reply_markers = [
                'replying to', 'in reply to', 'yanıt olarak', 'yanit olarak',
                'cevap olarak', 'yanıtladı', 'cevapladı', 'replied to'
            ]
            return any(m in low for m in reply_markers)

        def _is_quote_text(txt: str) -> bool:
            low = (txt or '').lower()
            quote_markers = ['quote tweet', 'quoted tweet', 'alıntı', 'alinti']
            return any(m in low for m in quote_markers)
        for inst in try_order:
            try:
                if not PNYTTER_AVAILABLE:
                    raise RuntimeError("Pnytter mevcut değil")
                print(f"[+] Pnytter instance deneniyor: {inst}")
                pny = Pnytter(nitter_instances=[inst])
                # Try a couple of times per instance to bypass transient 429/403
                per_inst_attempts = 0
                pny_tweets = None
                while per_inst_attempts < 3 and pny_tweets is None:  # Increased attempts
                    per_inst_attempts += 1
                    try:
                        # Always try without date filter first to get latest tweets
                        try:
                            pny_tweets = pny.get_user_tweets_list(TWITTER_SCREENNAME)
                        except TypeError:
                            # If date filtering is required, use a wider range
                            pny_tweets = pny.get_user_tweets_list(
                                TWITTER_SCREENNAME,
                                filter_from=from_dt.strftime('%Y-%m-%d'),
                                filter_to=to_dt.strftime('%Y-%m-%d'),
                            )
                        # Check if we got valid tweets
                        if pny_tweets and len(pny_tweets) > 0:
                            print(f"[+] {inst} başarılı: {len(pny_tweets)} tweet bulundu")
                            break
                        else:
                            print(f"[UYARI] {inst} boş sonuç döndü")
                            pny_tweets = None
                    except Exception as inner_e:
                        msg = str(inner_e)
                        if '403' in msg and 'Forbidden' in msg:
                            print(f"[UYARI] {inst} - 403 Forbidden (dosya izinleri sorunu), sonraki deneme...")
                            sleep_s = 2 + per_inst_attempts + random.uniform(0, 1)
                            time.sleep(sleep_s)
                        elif '429' in msg:
                            sleep_s = 5 + per_inst_attempts * 3 + random.uniform(0, 3)
                            print(f"[UYARI] {inst} - 429 Too Many Requests -> {int(sleep_s)} sn bekle ve yeniden dene")
                            time.sleep(sleep_s)
                        elif 'No address associated with hostname' in msg or 'Failed to establish' in msg:
                            print(f"[UYARI] {inst} erişilemez: {msg}")
                            break  # Bu instance'ı atla
                        elif 'Connection refused' in msg:
                            print(f"[UYARI] {inst} bağlantı reddedildi")
                            break  # Bu instance'ı atla
                        else:
                            print(f"[UYARI] {inst} beklenmeyen hata: {msg}")
                            if per_inst_attempts >= 3:
                                break

                slice_count = max(count * 2, 15)  # Increased slice to catch more tweets
                for t in pny_tweets[:slice_count]:
                    tid = str(getattr(t, 'tweet_id', '') or '')
                    txt = getattr(t, 'text', '') or ''
                    if not tid:
                        continue
                    # Pinned kontrolü (varsa atla)
                    if getattr(t, 'is_pinned', False):
                        print(f"[INFO] Pinned tweet atlandı: {tid}")
                        continue
                    # Retweet heuristics (Pnytter explicit flag yok)
                    if txt.strip().startswith('RT @'):
                        # Metinden retweet sinyali -> kesin atla
                        print(f"[INFO] Retweet (RT @ ile başlıyor) atlandı: {tid}")
                        continue
                    # Retweet alan/flag kontrolleri -> herhangi biri varsa kesin atla
                    try:
                        is_retweet_flag = False
                        for rattr in (
                            'is_retweet', 'retweet', 'retweeted', 'retweeted_status_id',
                            'retweeted_status', 'retweeted_by', 'rt', 'is_rt'
                        ):
                            rval = getattr(t, rattr, None)
                            if isinstance(rval, bool) and rval:
                                is_retweet_flag = True
                                break
                            if rval not in (None, '', 0, False):
                                is_retweet_flag = True
                                break
                        if is_retweet_flag:
                            print(f"[INFO] Retweet bayrakları tespit edildi, atlandı: {tid}")
                            continue
                    except Exception:
                        pass
                    # Pnytter nesnesinde yanıtla ilgili alanlar varsa kontrol et
                    is_reply_flag = False
                    for attr in (
                        'is_reply', 'is_reply_to', 'reply_to',
                        'in_reply_to_status_id', 'in_reply_to_user_id', 'in_reply_to_screen_name'
                    ):
                        val = getattr(t, attr, None)
                        if isinstance(val, bool) and val:
                            is_reply_flag = True
                            break
                        if val not in (None, '', 0, False):
                            is_reply_flag = True
                            break
                    # YANIT/ALINTI TESPİTİ: KESİN ATLA
                    # Metin '@' ile başlıyorsa doğrudan yanıt kabul et
                    if txt.strip().startswith('@'):
                        print(f"[INFO] Reply (metin '@' ile başlıyor) atlandı: {tid}")
                        continue
                    # Alan/flag kontrolleri + metin sezgileri -> herhangi biri varsa atla
                    if is_reply_flag or _is_reply_text(txt) or _is_quote_text(txt):
                        print(f"[INFO] Yanıt/alıntı olduğundan atlandı: {tid}")
                        continue
                    # Ek kural: Kısa ve bağlamsız (URL/hashtag yok) metinler genelde yanıttır
                    raw_txt = txt or ''
                    has_url = bool(re.search(r'https?://\S+', raw_txt))
                    has_hashtag = bool(re.search(r'#\w+', raw_txt))
                    has_punct = any(ch in raw_txt for ch in [':', '-', '—', '!', '?', '"', '"', '"', '\''])
                    has_domain_terms = any(k in raw_txt for k in ['BF', 'Battlefield', 'battlefield', 'BF6'])
                    short_len_threshold = 50
                    if (len(raw_txt.strip()) < short_len_threshold) and not (has_url or has_hashtag or has_punct or has_domain_terms):
                        print(f"[INFO] Kısa/bağlamsız tweet atlandı (muhtemel yanıt): {tid} -> '{raw_txt[:80]}'")
                        continue
                    # Tweet'te medya var mı kontrol et
                    has_media_indicator = any(indicator in raw_txt for indicator in ['pic.twitter.com', 'video.twitter.com', 'pbs.twimg.com'])
                    
                    # Nitter HTML'den medya URL'leri topla (çoklu instance dene)
                    media_urls = _fetch_media_from_nitter_html_multi(TWITTER_SCREENNAME, tid, preferred=inst)
                    
                    # Medya beklenen ama alınamadıysa tweet'i atla
                    if has_media_indicator and media_urls is None:
                        print(f"[INFO] Medya bekleniyordu ama alınamadı, tweet atlanıyor: {tid}")
                        continue
                    
                    # media_urls None ise boş liste yap
                    if media_urls is None:
                        media_urls = []
                    
                    tweets.append({
                        'tweet_id': tid,
                        'text': clean_tweet_text(txt),
                        'media_urls': media_urls,
                        'link': f"https://x.com/{TWITTER_SCREENNAME}/status/{tid}",
                    })
                    if len(tweets) >= count:
                        break
                if tweets:
                    print(f"[+] Pnytter ile {len(tweets)} tweet bulundu ({inst})")
                    return {"tweets": tweets}
            except Exception as _per_inst_err:
                error_msg = str(_per_inst_err)
                if 'No address associated with hostname' in error_msg:
                    print(f"[UYARI] {inst} DNS hatası - instance erişilemez")
                elif 'Connection refused' in error_msg:
                    print(f"[UYARI] {inst} bağlantı reddedildi - instance kapalı")
                elif 'timeout' in error_msg.lower():
                    print(f"[UYARI] {inst} timeout - instance yavaş")
                else:
                    print(f"[UYARI] Pnytter instance başarısız: {inst} -> {_per_inst_err}")
                time.sleep(1)
        print("[!] Pnytter ile uygun tweet bulunamadı, RSS fallback deneniyor")
    except ImportError:
        print("[UYARI] Pnytter kütüphanesi bulunamadı, RSS fallback deneniyor")
    except Exception as e:
        print(f"[UYARI] Pnytter genel hatası: {e}. RSS fallback deneniyor")

    # 2) RSS fallback - önce twiiit.com dene (dinamik yönlendirme), sonra diğer instance'lar
    # twiiit.com'u öncelikle dene (dinamik instance seçimi)
    rss_instances_to_try = ["https://twiiit.com", "https://xcancel.com", "https://nitter.privacydev.net"]
    # Sonra mevcut instance'ı ekle (eğer zaten listede değilse)
    current_instance = NITTER_INSTANCES[CURRENT_NITTER_INDEX]
    if current_instance not in rss_instances_to_try:
        rss_instances_to_try.append(current_instance)
    
    # Tüm instance'ları dene (403 hatalarına karşı)
    for backup_instance in NITTER_INSTANCES:
        if backup_instance not in rss_instances_to_try:
            rss_instances_to_try.append(backup_instance)
    
    for rss_instance in rss_instances_to_try:
        url = f"{rss_instance}/{TWITTER_SCREENNAME}/rss"
        try:
            print(f"[+] RSS ile çekiliyor: {rss_instance}")
            ua_pool = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1.1 Safari/605.1.15',
            ]
            selected_ua = random.choice(ua_pool)
            headers = {
                'User-Agent': selected_ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'X-Requested-With': 'XMLHttpRequest',  # AJAX request gibi görün
                'Origin': rss_instance,  # Origin header ekle
                'Referer': f"{rss_instance}/{TWITTER_SCREENNAME}",  # Referer ekle
            }
            # Session kullan ve tarayıcı benzeri davranış
            session = get_or_create_session(rss_instance)
            session.headers.update(headers)
            
            # İlk önce ana sayfayı ziyaret et (tarayıcı benzeri davranış)
            try:
                base_url = rss_instance
                session.get(base_url, timeout=10)
                time.sleep(random.uniform(5, 15))  # Daha uzun bekleme (IP ban önleme)
            except:
                pass  # Ana sayfa hatası önemli değil
            
            response = session.get(url, timeout=15)
            response.raise_for_status()

            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}item')

            tweets = []
            slice_count = max(count * 2, 15)  # Increased slice for RSS as well
            for item in items[:slice_count]:
                title_elem = item.find('title') or item.find('{http://www.w3.org/2005/Atom}title')
                link_elem = item.find('link') or item.find('{http://www.w3.org/2005/Atom}link')
                desc_elem = item.find('description') or item.find('{http://www.w3.org/2005/Atom}description')
                if not all([title_elem, link_elem]):
                    continue
                title = (title_elem.text or '').strip()
                link = link_elem.text
                description = desc_elem.text if desc_elem is not None else ''
                # Retweet heuristics
                if title.startswith('RT @') or 'retweeted' in description.lower():
                    continue
                # Reply/Quote heuristics: @ ile başlıyorsa ya da yaygın kalıpları içeriyorsa
                desc_low = (description or '').lower()
                if (
                    title.startswith('@') or desc_low.startswith('@') or
                    any(m in desc_low for m in ['replying to', 'in reply to', 'yanıt olarak', 'yanit olarak', 'cevap olarak', 'replied to']) or
                    any(m in desc_low for m in ['quote tweet', 'quoted tweet', 'alıntı', 'alinti'])
                ):
                    print(f"[INFO] Yanıt/alıntı olduğundan atlandı (RSS)")
                    continue
                # Ek kural: Kısa ve bağlamsız metinler genelde yanıttır
                raw_text = description or ''
                has_url = bool(re.search(r'https?://\S+', raw_text))
                has_hashtag = bool(re.search(r'#\w+', raw_text))
                has_punct = any(ch in raw_text for ch in [':', '-', '—', '!', '?', '"', '"', '"', '\''])
                has_domain_terms = any(k in raw_text for k in ['BF', 'Battlefield', 'battlefield', 'BF6'])
                short_len_threshold = 50
                cleaned_len = len(clean_tweet_text(raw_text))
                if (cleaned_len < short_len_threshold) and not (has_url or has_hashtag or has_punct or has_domain_terms):
                    print(f"[INFO] Kısa ve bağlamsız tweet atlandı (muhtemel yanıt, RSS)")
                    continue
                tweet_id = link.split('/')[-1].split('#')[0]
                tweet_text = clean_tweet_text(description)
                # Tweet'te medya var mı kontrol et
                has_media_indicator = 'pic.twitter.com' in description or any(indicator in description for indicator in ['video.twitter.com', 'pbs.twimg.com'])
                
                # Nitter HTML'den medya URL'leri topla (öncelikli, çoklu instance dene)
                media_urls = _fetch_media_from_nitter_html_multi(TWITTER_SCREENNAME, tweet_id, preferred=rss_instance)
                
                # Fallback: RSS'te pic.twitter.com varsa ama medya alınamadıysa
                if media_urls is None and 'pic.twitter.com' in description:
                    media_matches = re.findall(r'pic\.twitter\.com/[\w]+', description)
                    media_urls = [f"https://{m}" for m in media_matches]
                
                # Medya beklenen ama alınamadıysa tweet'i atla
                if has_media_indicator and (media_urls is None or len(media_urls) == 0):
                    print(f"[INFO] RSS: Medya bekleniyordu ama alınamadı, tweet atlanıyor: {tweet_id}")
                    continue
                
                # media_urls None ise boş liste yap
                if media_urls is None:
                    media_urls = []
                
                tweets.append({
                    'tweet_id': tweet_id,
                    'text': tweet_text,
                    'media_urls': media_urls,
                    'link': link,
                })
                if len(tweets) >= count:
                    break
            return {"tweets": tweets}
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            
            # Özel hata mesajları
            if status == 403:
                print(f"[UYARI] {rss_instance} - 403 Forbidden (dosya izinleri sorunu)")
                # 403 hatası için alternatif erişim yöntemi dene
                try:
                    print(f"[+] {rss_instance} için alternatif erişim deneniyor...")
                    alt_headers = headers.copy()
                    alt_headers.update({
                        'Accept': 'application/rss+xml, application/xml, text/xml',
                        'X-Forwarded-For': f"192.168.1.{random.randint(1, 254)}",  # Fake IP
                        'X-Real-IP': f"10.0.0.{random.randint(1, 254)}",
                        'Via': '1.1 proxy.example.com',
                        'Cache-Control': 'no-cache, must-revalidate',
                    })
                    alt_response = session.get(url, headers=alt_headers, timeout=15)
                    if alt_response.status_code == 200:
                        print(f"[+] {rss_instance} alternatif erişim başarılı!")
                        response = alt_response  # Başarılı response'u kullan
                    else:
                        print(f"[UYARI] {rss_instance} alternatif erişim de başarısız, sonraki instance deneniyor...")
                        continue
                except Exception as alt_e:
                    print(f"[UYARI] {rss_instance} alternatif erişim hatası: {alt_e}")
                    continue
            elif status == 429:
                jitter = random.uniform(0, 3)
                backoff = min(300, (retry_count + 1) * NITTER_REQUEST_DELAY * 2 + jitter)
                print(f"[UYARI] {rss_instance} - 429 Too Many Requests, {int(backoff)} sn bekleyip sonraki instance deneniyor...")
                time.sleep(backoff)
            elif status == 502:
                print(f"[UYARI] {rss_instance} - 502 Bad Gateway, sonraki instance deneniyor...")
            elif status == 503:
                print(f"[UYARI] {rss_instance} - 503 Service Unavailable, sonraki instance deneniyor...")
            elif 'No address associated with hostname' in error_msg:
                print(f"[UYARI] {rss_instance} - DNS hatası, instance erişilemez")
            else:
                print(f"[UYARI] RSS istek hatası ({rss_instance}): {e}")
            continue
        except Exception as e:
            print(f"[HATA] RSS genel hata ({rss_instance}): {e}")
            continue
    
    # Tüm RSS instance'ları başarısızsa boş liste dön
    print("[HATA] Tüm RSS instance'ları başarısız")
    
    # Son çare: Direkt Twitter API veya alternatif kaynaklar denenmeli
    # Şimdilik boş liste döndür ama gelecekte başka API'ler eklenebilir
    print("[INFO] Alternatif tweet kaynakları için geliştirilmeyi bekliyor...")
    return {"tweets": []}

def get_media_urls_from_tweet_data(tweet_data):
    """Nitter'dan alınan tweet verisinden medya URL'lerini çıkar"""
    if not tweet_data or "media_urls" not in tweet_data:
        print("[HATA] Geçersiz tweet verisi veya medya URL'leri yok")
        return []
    
    try:
        tweet_id = tweet_data.get("tweet_id", "")
        media_urls = tweet_data.get("media_urls", [])
        
        print(f"[+] {len(media_urls)} medya URL'si bulundu: {media_urls}")
        return media_urls
        
    except Exception as e:
        print(f"[HATA] Medya URL'leri alınırken hata: {e}")
        return []

def _fetch_media_from_nitter_html(instance_base: str, screen_name: str, tweet_id: str):
    """Nitter tekil tweet HTML'inden medya URL'leri çıkar (BS4 + enc/base64 desteği).
    Resim (.jpg/.jpeg/.png/.webp) ve video (.mp4) döndürür. HLS (.m3u8) dışlanır.
    """
    try:
        if not instance_base or not screen_name or not tweet_id:
            return []

        base = instance_base.rstrip('/')
        url = f"{base}/{screen_name}/status/{tweet_id}"

        # Session + header + cookie (hlsPlayback bazı instance'larda mp4 kaynağını açar)
        s = get_or_create_session(instance_base)
        s.headers.update({
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Host': base.split('://', 1)[1],
        })

        # Tarayıcı benzeri davranış: İlk önce ana sayfayı ziyaret et
        try:
            base_url = rss_instance
            session.get(base_url, timeout=10)
            time.sleep(random.uniform(10, 20))  # Çok daha uzun bekleme (IP ban önleme)
        except:
            pass  # Ana sayfa hatası önemli değil
        
        # Retry logic with exponential backoff
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Rastgele kısa bekleme (bot tespitini zorlaştır)
                time.sleep(random.uniform(0.2, 1))
                resp = s.get(url, cookies={'hlsPlayback': 'on'}, timeout=15)
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as he:
                if he.response.status_code == 403:
                    print(f"[UYARI] {instance_base} - 403 Forbidden, alternatif erişim deneniyor...")
                    # 403 için özel bypass headers
                    try:
                        bypass_headers = s.headers.copy()
                        bypass_headers.update({
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'X-Forwarded-For': f"192.168.1.{random.randint(1, 254)}",
                            'X-Real-IP': f"10.0.0.{random.randint(1, 254)}",
                            'Via': '1.1 proxy.example.com',
                            'Cache-Control': 'no-cache, must-revalidate',
                            'Pragma': 'no-cache',
                        })
                        bypass_resp = s.get(url, headers=bypass_headers, cookies={'hlsPlayback': 'on'}, timeout=15)
                        if bypass_resp.status_code == 200:
                            print(f"[+] {instance_base} bypass başarılı!")
                            resp = bypass_resp
                            break
                        else:
                            print(f"[UYARI] {instance_base} bypass başarısız")
                            if attempt < max_attempts - 1:
                                time.sleep(2)
                                continue
                    except Exception as bypass_e:
                        print(f"[UYARI] {instance_base} bypass hatası: {bypass_e}")
                elif he.response.status_code in [418, 429, 503, 502]:
                    if attempt < max_attempts - 1:
                        wait_time = (2 ** attempt) + random.uniform(0, 1)
                        print(f"[INFO] {instance_base} HTTP {he.response.status_code}, {wait_time:.1f}s bekleyip yeniden deneniyor...")
                        time.sleep(wait_time)
                        continue
                raise he
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as ce:
                if attempt < max_attempts - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    print(f"[INFO] {instance_base} bağlantı hatası, {wait_time:.1f}s bekleyip yeniden deneniyor...")
                    time.sleep(wait_time)
                    continue
                raise ce
        soup = BeautifulSoup(resp.text, 'lxml')

        # Encoded medya kullanılıyor mu?
        def _instance_uses_enc() -> bool:
            try:
                avatar = soup.find('a', class_='profile-card-avatar')
                img = avatar and avatar.find('img')
                return bool(img and '/enc/' in (img.get('src') or ''))
            except Exception:
                return False

        is_enc = _instance_uses_enc()

        def _decode_enc_path(path: str) -> str:
            try:
                enc = path.split('/enc/', 1)[1].split('/', 1)[-1]
                return b64decode(enc.encode('utf-8')).decode('utf-8')
            except Exception:
                return ''

        def _norm_image_src(src: str) -> str:
            if not src:
                return ''
            if is_enc and '/enc/' in src:
                decoded = _decode_enc_path(src)
                if decoded:
                    # pbs path tam gelir (pbs.twimg.com/..)
                    if decoded.startswith('http'):
                        return decoded.split('?')[0]
                    return ('https://' + decoded).split('?')[0]
                return ''
            # Normal instance: /pic/... -> pbs
            if '/pic/' in src:
                try:
                    return ('https://pbs.twimg.com' + unquote(src.split('/pic', 1)[1])).split('?')[0]
                except Exception:
                    return ''
            # Bazı durumlarda zaten https pbs olabilir
            if src.startswith('http'):
                return src.split('?')[0]
            # Göreli ise instance ile birleştir
            return (base + src).split('?')[0]

        def _norm_video_src(video_tag) -> str:
            if not video_tag:
                return ''
            # Öncelik data-url, sonra <source src>
            if video_tag.has_attr('data-url'):
                v = video_tag['data-url']
                if is_enc and '/enc/' in v:
                    v = _decode_enc_path(v)
                if v:
                    v = (('https://' + v) if not v.startswith('http') else v)
                    v = v.split('?')[0]
                    return v
            src_el = video_tag.find('source')
            v = src_el.get('src') if src_el else ''
            if is_enc and v and '/enc/' in v:
                v = _decode_enc_path(v)
            if v:
                v = (('https://' + v) if not v.startswith('http') else v)
                v = v.split('?')[0]
                return v
            return ''

        out = []

        # Eğer bu sayfa bir 'retweet' veya 'reply' ise medyayı hiç toplama (sıkı politika)
        try:
            # Retweet tespiti: Nitter arayüzünde genelde 'retweet-header' veya 'Retweeted by' görülür
            rt_header = soup.find(class_='retweet-header')
            rt_text_hit = soup.find(string=lambda s: isinstance(s, str) and ('Retweeted by' in s or 'Retweetledi' in s))
            if rt_header or rt_text_hit:
                print(f"[INFO] Tekil sayfa retweet olarak tespit edildi, medya toplanmayacak: {url}")
                return []
            # Reply tespiti: "Replying to" ibaresi veya 'replying-to' sınıfı
            reply_banner = soup.find(class_='replying-to')
            reply_text_hit = soup.find(string=lambda s: isinstance(s, str) and ('Replying to' in s or 'Yanıt olarak' in s or 'Yanit olarak' in s))
            if reply_banner or reply_text_hit:
                print(f"[INFO] Tekil sayfa reply olarak tespit edildi, medya toplanmayacak: {url}")
                return []
        except Exception:
            pass

        # Ana tweet attachments
        body = soup.find('div', class_='tweet-body')
        attach = body.find('div', class_='attachments', recursive=False) if body else None
        if attach:
            # images
            for img in attach.find_all('img'):
                u = _norm_image_src(img.get('src'))
                if u:
                    out.append(u)
            # videos (gif olmayan)
            for vid in attach.find_all('video', class_=''):
                u = _norm_video_src(vid)
                if u:
                    out.append(u)
            # gifs
            for gif in attach.find_all('video', class_='gif'):
                src_el = gif.find('source')
                u = _norm_image_src(src_el.get('src') if src_el else '')
                if u:
                    out.append(u)

        # Alıntı (quote) içi medya DAHİL EDİLMEZ: sadece ana tweet'in medyası isteniyor
        # quote = soup.find('div', class_='quote')
        # if quote:
        #     q_attach = quote.find('div', class_='attachments')
        #     if q_attach:
        #         for img in q_attach.find_all('img'):
        #             u = _norm_image_src(img.get('src'))
        #             if u:
        #                 out.append(u)
        #         for vid in q_attach.find_all('video', class_=''):
        #             u = _norm_video_src(vid)
        #             if u:
        #                 out.append(u)
        #         for gif in q_attach.find_all('video', class_='gif'):
        #             src_el = gif.find('source')
        #             u = _norm_image_src(src_el.get('src') if src_el else '')
        #             if u:
        #                 out.append(u)

        # Filtre: yalnızca resim ve mp4, m3u8'i çıkar
        def _acceptable(u: str) -> bool:
            if not u:
                return False
            ul = u.lower()
            if ul.endswith('.m3u8'):
                return False
            return any(ul.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp', '.mp4')) or \
                   ('pbs.twimg.com/media' in ul) or ('video.twimg.com' in ul)

        # unique sırayı koru
        seen = set()
        unique = []
        for u in out:
            if _acceptable(u) and u not in seen:
                seen.add(u)
                unique.append(u)
        return unique
    except Exception as e:
        print(f"[UYARI] Nitter HTML medya çıkarma hatası: {e}")
        return []

def _is_tweet_reply_or_retweet_html(instance_base: str, screen_name: str, tweet_id: str) -> bool:
    """Tekil tweet HTML'inden reply/retweet olup olmadığını hızlıca tespit et.
    Reply/retweet ise True döner, aksi halde False.
    """
    try:
        if not instance_base or not screen_name or not tweet_id:
            return False
        base = instance_base.rstrip('/')
        url = f"{base}/{screen_name}/status/{tweet_id}"
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0'})
        r = s.get(url, timeout=15)
        if r.status_code != 200:
            return False
        soup = BeautifulSoup(r.text, 'html.parser')
        # Retweet sinyalleri
        rt_header = soup.find(class_='retweet-header')
        rt_text_hit = soup.find(string=lambda s: isinstance(s, str) and ('Retweeted by' in s or 'Retweetledi' in s))
        if rt_header or rt_text_hit:
            return True
        # Reply sinyalleri
        reply_banner = soup.find(class_='replying-to')
        reply_text_hit = soup.find(string=lambda s: isinstance(s, str) and ('Replying to' in s or 'Yanıt olarak' in s or 'Yanit olarak' in s))
        if reply_banner or reply_text_hit:
            return True
        return False
    except Exception:
        return False

def _is_instance_in_cooldown(instance: str) -> bool:
    """Instance'ın cooldown durumunda olup olmadığını kontrol et."""
    current_time = time.time()
    if instance in _INSTANCE_FAILURES:
        failure_count, last_failure_time = _INSTANCE_FAILURES[instance]
        if failure_count >= _FAILURE_THRESHOLD:
            if current_time - last_failure_time < _COOLDOWN_PERIOD:
                return True
            else:
                # Cooldown süresi doldu, sıfırla
                del _INSTANCE_FAILURES[instance]
    return False

def _record_instance_failure(instance: str):
    """Instance başarısızlığını kaydet."""
    current_time = time.time()
    if instance in _INSTANCE_FAILURES:
        failure_count, _ = _INSTANCE_FAILURES[instance]
        _INSTANCE_FAILURES[instance] = (failure_count + 1, current_time)
    else:
        _INSTANCE_FAILURES[instance] = (1, current_time)

def get_instance_health_status():
    """Nitter instance'larının sağlık durumunu göster."""
    current_time = time.time()
    healthy = []
    cooldown = []
    failed = []
    
    for inst in NITTER_INSTANCES:
        if inst in _INSTANCE_FAILURES:
            failure_count, last_failure = _INSTANCE_FAILURES[inst]
            if failure_count >= _FAILURE_THRESHOLD:
                if current_time - last_failure < _COOLDOWN_PERIOD:
                    cooldown_remaining = int(_COOLDOWN_PERIOD - (current_time - last_failure))
                    cooldown.append(f"{inst} ({cooldown_remaining}s kaldı)")
                else:
                    healthy.append(inst)
            else:
                failed.append(f"{inst} ({failure_count} başarısızlık)")
        else:
            healthy.append(inst)
    
    print(f"[INFO] Instance durumu - Sağlıklı: {len(healthy)}, Cooldown: {len(cooldown)}, Başarısız: {len(failed)}")
    if cooldown:
        print(f"[INFO] Cooldown'da: {', '.join(cooldown)}")
    return {"healthy": healthy, "cooldown": cooldown, "failed": failed}

# -------------------- Web Service (FastAPI) --------------------
# Not: Render Web Service için bir HTTP portu dinlemek gerekir. Aşağıdaki app,
# / ve /healthz endpoint'leri sağlar ve uygulama başlarken bot döngüsünü
# arka planda bir thread ile başlatır.

app = FastAPI(title="X-to-Reddit Bot")
_worker_started = False
_worker_lock = threading.Lock()

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
                print("[WEB] DB preflight OK: posted_tweet_ids table ensured")
            except Exception as e:
                print(f"[HATA] DB preflight başarısız: {e}")
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
                print("[WEB] Background worker starting main_loop()...")
                main_loop()
            except Exception as e:
                print(f"[WEB] Background worker stopped: {e}")
        t = threading.Thread(target=_run, name="bot-worker", daemon=True)
        t.start()
        _worker_started = True

def _fetch_media_from_nitter_html_multi(screen_name: str, tweet_id: str, preferred: str = None):
    """Birden fazla Nitter instance'ını deneyerek HTML'den medya URL'leri çıkarmayı dener."""
    try:
        try_list = []
        if preferred and not _is_instance_in_cooldown(preferred):
            try_list.append(preferred)
        
        # Kalanları ekle (cooldown'da olmayanlar)
        for inst in NITTER_INSTANCES:
            if inst not in try_list and not _is_instance_in_cooldown(inst):
                try_list.append(inst)
        
        # Eğer tüm instance'lar cooldown'daysa, en az başarısızlığı olanı dene
        if not try_list:
            print("[UYARI] Tüm instance'lar cooldown'da, en az başarısızlığı olan deneniyor")
            min_failures = min(_INSTANCE_FAILURES.get(inst, (0, 0))[0] for inst in NITTER_INSTANCES)
            for inst in NITTER_INSTANCES:
                if _INSTANCE_FAILURES.get(inst, (0, 0))[0] == min_failures:
                    try_list.append(inst)
                    break

        for inst in try_list:
            try:
                media = _fetch_media_from_nitter_html(inst, screen_name, tweet_id)
                if media:
                    # Başarılı olursa failure kaydını temizle
                    if inst in _INSTANCE_FAILURES:
                        del _INSTANCE_FAILURES[inst]
                    return media
            except Exception as e:
                # Instance başarısızlığını kaydet
                _record_instance_failure(inst)
                
                # Gelişmiş hata işleme
                msg = str(e)
                status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                
                # HTTP hata kodlarına göre işlem
                if status_code == 418:
                    print(f"[UYARI] {inst} anti-bot koruması (418 I'm a teapot)")
                    continue
                elif status_code == 503:
                    print(f"[UYARI] {inst} geçici olarak kullanılamıyor (503)")
                    continue
                elif status_code == 502:
                    print(f"[UYARI] {inst} ağ geçidi hatası (502)")
                    continue
                elif any(code in msg for code in ['403', '404', '418', '429', '502', '503']):
                    print(f"[UYARI] {inst} HTTP hatası: {status_code or 'unknown'}")
                    continue
                elif any(err in msg for err in ['getaddrinfo failed', 'Failed to establish', 'Connection refused', 'timeout']):
                    print(f"[UYARI] {inst} bağlantı hatası: {type(e).__name__}")
                    continue
                else:
                    print(f"[UYARI] {inst} beklenmeyen hata: {e}")
                    continue
        # Hepsi başarısızsa: Önce tweet reply/retweet mi diye kontrol et, öyleyse fallback'i devre dışı bırak
        try:
            inspect_base = preferred or (try_list[0] if try_list else (NITTER_INSTANCES[0] if NITTER_INSTANCES else None))
            if inspect_base and _is_tweet_reply_or_retweet_html(inspect_base, screen_name, tweet_id):
                print(f"[INFO] Tweet reply/retweet olarak tespit edildi, gallery-dl fallback atlandı: {screen_name}/{tweet_id}")
                return []
        except Exception:
            pass

        # Reply/retweet değilse gallery-dl fallback dene
        try:
            urls = _fetch_media_with_gallery_dl(screen_name, tweet_id, preferred or (try_list[0] if try_list else None))
            if urls:
                return urls
        except Exception as _gde:
            print(f"[UYARI] gallery-dl fallback başarısız: {_gde}")
    
        # Son çare: medya alınamadı, None döndür (tweet atlanacak)
        print(f"[UYARI] {screen_name}/{tweet_id} için medya alınamadı")
        return None

    except Exception as e:
        print(f"[HATA] _fetch_media_from_nitter_html_multi beklenmeyen hata: {e}")
        return None

def _fetch_media_with_gallery_dl(screen_name: str, tweet_id: str, instance_base: str = None):
    """gallery-dl aracılığıyla medya URL'lerini çıkar (indirMEdEN -g)."""
    try:
        # Önce Nitter URL, sonra x.com URL dene
        urls_to_try = []
        if instance_base:
            base = instance_base.rstrip('/')
            urls_to_try.append(f"{base}/{screen_name}/status/{tweet_id}")
        urls_to_try.append(f"https://x.com/{screen_name}/status/{tweet_id}")

        out_urls = []
        for tu in urls_to_try:
            try:
                proc = subprocess.run(
                    [sys.executable, '-m', 'gallery_dl', '-g', tu],
                    capture_output=True, text=True, timeout=25
                )
                if proc.returncode == 0:
                    raw_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
                    # gallery-dl alternatif boyutları '|' prefiksi ile yazar; indirilebilir URL için temizle
                    lines = []
                    for ln in raw_lines:
                        if ln.startswith('| '):
                            lines.append(ln[2:].strip())
                        elif ln.startswith('|'):
                            lines.append(ln[1:].strip())
                        else:
                            lines.append(ln)
                    # Filtre: m3u8 çıkar, jpg/png/webp/mp4 bırak
                    acc = []
                    for u in lines:
                        ul = u.lower()
                        if ul.endswith('.m3u8'):
                            continue
                        if (
                            any(ul.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp', '.mp4'))
                            or 'pbs.twimg.com/media' in ul
                            or 'video.twimg.com' in ul
                        ):
                            acc.append(u)
                    # En kaliteli varyantı seç: aynı medyanın (soru işaretinden önceki kısım) ilk görülenini koru (genelde 'orig' ilk gelir)
                    best_only = []
                    seen_base = set()
                    for u in acc:
                        base_no_q = u.split('?', 1)[0]
                        if base_no_q in seen_base:
                            continue
                        seen_base.add(base_no_q)
                        best_only.append(u)
                    if best_only:
                        out_urls.extend(best_only)
                        break  # İlk başarılı kaynaktan çık
            except Exception as _inner:
                print(f"[UYARI] gallery-dl denemesi başarısız: {tu} -> {_inner}")
                continue
        # benzersiz sırayı koru
        seen = set()
        uniq = []
        for u in out_urls:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq
    except Exception as e:
        print(f"[UYARI] gallery-dl fallback genel hata: {e}")
        return []

def translate_text(text):
    """Gemini 2.5 Flash ile İngilizce -> Türkçe çeviri.
    Çıkış: Sadece ham çeviri (ek açıklama, tırnak, etiket vs. yok).
    Özel terimleri ÇEVİRME: battlefield, free pass, battle pass.
    """
    try:
        if not text or not text.strip():
            return None

        # Gemini client (API anahtarı ortam değişkeni: GEMINI_API_KEY)
        # Ortam değişkeni yoksa client init hata verebilir; yakalayalım
        client = genai.Client()

        # Talimat: sadece ham çeviri, belirli terimler çevrilmez.
        prompt = (
            "Translate the text from English to Turkish. Output ONLY the translation with no extra words, "
            "no quotes, no labels. Do NOT translate these terms and keep their original casing: "
            "battlefield, free pass, battle pass, Operation Firestorm, Easter Egg, Plus, Trickshot.\n"
            "Preserve the original tweet's capitalization EXACTLY for all words where possible; do not change upper/lower casing from the source text.\n"
            "If the input includes any mentions like @nickname or patterns like 'via @nickname', exclude them from the output entirely.\n"
            "If the content appears to be a short gameplay/clip highlight rather than a news/article, compress it into ONE coherent Turkish sentence (no bullet points, no multiple sentences).\n"
            "Additionally, if the source text contains these tags/keywords, translate them EXACTLY as follows (preserve casing where appropriate):\n"
            "BREAKING => SON DAKİKA; LEAK => SIZINTI; HUMOUR => SÖYLENTİ.\n"
            "Don't make mistakes like this translation: \"What is your FINAL Rating of the Battlefield 6 Beta? (1-10) Turkish translation: Battlefield 6 Beta'nızın SON Derecelendirmesi nedir? (1-10)\" Should be: Battlefield 6 Beta için SON derecelendirmeniz nedir?\n\n"
            "Text:\n" + text.strip()
        )

        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            ),
        )
        out = (resp.text or "").strip()
        # Boş veya değişmemişse None döndür (muhtemelen zaten TR veya başarısız)
        if out and out != text.strip():
            return out
        print("[UYARI] Çeviri boş döndü veya orijinal ile aynı")
        return None
    except Exception as e:
        print(f"[UYARI] Gemini çeviri hatası: {e}")
        return None

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

def select_flair_with_ai(title, original_tweet_text=""):
    """AI ile otomatik flair seçimi"""
    print("[+] AI ile flair seçimi başlatılıyor...")
    print(f"[DEBUG] Başlık: {title}")
    print(f"[DEBUG] Orijinal tweet: {original_tweet_text[:100]}..." if original_tweet_text else "[DEBUG] Orijinal tweet yok")
    
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
            print("[!] OPENAI_API_KEY bulunamadı, kural tabanlı seçim kullanılıyor")
            return selected_flair_id
        
        # OpenAI API için prompt hazırla
        content_to_analyze = f"Başlık: {title}"
        if original_tweet_text:
            content_to_analyze += f"\nOrijinal Tweet: {original_tweet_text}"
        
        prompt = f"""Aşağıdaki Battlefield 6 ile ilgili içeriği analiz et ve en uygun flair'i seç.

İçerik:
{content_to_analyze}

Mevcut flair seçenekleri:
1. Haberler - Oyun haberleri, duyurular, resmi açıklamalar
2. Klip - Video klipler, gameplay videoları
3. Tartışma - Genel tartışmalar, görüşler
4. Soru - Sorular ve yardım istekleri
5. İnceleme - Oyun incelemeleri, değerlendirmeler
6. Kampanya - Kampanya modu ile ilgili içerik
7. Arkaplan - Oyun arkaplanı, hikaye, lore
8. Sızıntı - Sızıntılar, leak'ler, söylentiler

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
        r = requests.get(media_url, stream=True, timeout=30)
        if r.status_code == 200:
            with open(filename, "wb") as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return filename
        else:
            print(f"[HATA] Medya indirilemedi: {media_url} - Status: {r.status_code}")
            return None
    except Exception as e:
        print(f"[HATA] Medya indirirken: {e}")
        return None

def get_image_hash(image_path):
    """Resim dosyasının hash'ini hesapla (duplicate detection için)"""
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
            return hashlib.md5(image_data).hexdigest()
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
            "-threads", "2",  # Daha az thread
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
                    if flair_id:
                        try:
                            # Öncelikle ID ile dene
                            if submission_id and isinstance(submission_id, str) and submission_id:
                                praw_sub = reddit.submission(id=submission_id)
                                praw_sub.flair.select(flair_id)
                                print(f"[+] Gallery flair uygulandı (ID ile): {flair_id}")
                            else:
                                # Başlığa göre yakın zamanda oluşturulan gönderiyi bul
                                sr_obj = reddit.subreddit(subreddit_name)
                                for s in sr_obj.new(limit=10):
                                    author_name = getattr(s.author, 'name', '') or ''
                                    if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                                        s.flair.select(flair_id)
                                        print(f"[+] Gallery flair uygulandı (arama ile): {flair_id}")
                                        break
                        except Exception as fe:
                            print(f"[UYARI] Gallery flair uygulanamadı: {fe}")
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
                                    s.flair.select(flair_id)
                                    print(f"[+] Gallery flair uygulandı (doğrulama): {flair_id}")
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
                                s.flair.select(flair_id)
                                print(f"[+] Gallery flair uygulandı (hata sonrası doğrulama): {flair_id}")
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
                        praw_sub = reddit.submission(id=submission_id)
                        praw_sub.flair.select(flair_id)
                        print(f"[+] Video flair uygulandı (ID ile): {flair_id}")
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
                    sr_obj = reddit.subreddit(subreddit_name)
                    for s in sr_obj.new(limit=10):
                        author_name = getattr(s.author, 'name', '') or ''
                        if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                            s.flair.select(flair_id)
                            print(f"[+] Video flair uygulandı (arama ile): {flair_id}")
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
                    submission.flair.select(flair_id)
                    print(f"[+] Video flair uygulandı (PRAW): {flair_id}")
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
    
    # 2. Son çare: Sadece başlık gönder
    try:
        print("[!] Son çare: Text post gönderiliyor...")
        submission = subreddit.submit(
            title=title + " [Video yüklenemedi - Twitter'dan izleyebilirsiniz]", 
            selftext="",
            flair_id=flair_id
        )
        print(f"[+] Text post gönderildi: {submission.url}")
        return True
    except Exception as text_e:
        print(f"[HATA] Text post bile gönderilemedi: {text_e}")
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
    selected_flair_id = select_flair_with_ai(title, original_tweet_text)
    print(f"[+] Seçilen flair ID: {selected_flair_id}")
    
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
            print("[!] Gallery yüklenemedi, tekil resim yükleme deneniyor...")
    
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
            submission = subreddit.submit(title=title, selftext=(remainder_text or ""), flair_id=selected_flair_id)
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
            submission = subreddit.submit_image(title=title, image_path=media_path, flair_id=selected_flair_id)
            print(f"[+] Resim başarıyla gönderildi: {submission.url}")
            # Uzun metnin kalanı yorum olarak ekle
            try:
                if remainder_text:
                    submission.reply(remainder_text)
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
                # Büyük video için text post gönder
                submission = subreddit.submit(title=title + " [Video çok büyük - Twitter linkini kontrol edin]", selftext=(remainder_text or ""), flair_id=selected_flair_id)
                print(f"[+] Text post gönderildi: {submission.url}")
                return True
            
            # Video upload denemesi
            result = upload_video_via_reddit_api(title, media_path, SUBREDDIT, selected_flair_id)
            
            if result:
                print("[+] Video başarıyla yüklendi!")
                # Eğer Submission nesnesi geldiyse kalan metni yorum olarak ekle
                try:
                    if hasattr(result, "reply") and remainder_text:
                        result.reply(remainder_text)
                        print("[+] Başlığın kalan kısmı video gönderisine yorum olarak eklendi")
                    elif isinstance(result, str) and remainder_text:
                        # Deterministik: RedditWarp ID döndü
                        try:
                            praw_sub = reddit.submission(id=result)
                            praw_sub.reply(remainder_text)
                            print("[+] Başlığın kalan kısmı (ID ile) video gönderisine yorum olarak eklendi")
                        except Exception as idc_e:
                            print(f"[UYARI] ID ile yorum ekleme başarısız: {idc_e}")
                    elif remainder_text:
                        # RedditWarp yolu: Submission nesnesi yok. Son gönderiyi bulup yorum eklemeyi dene.
                        try:
                            for s in subreddit.new(limit=10):
                                author_name = getattr(s.author, 'name', '') or ''
                                if author_name.lower() == (REDDIT_USERNAME or '').lower() and s.title == title:
                                    s.reply(remainder_text)
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
                    # Son çare text post
                    print("[!] Tüm yöntemler başarısız, text post gönderiliyor...")
                    submission = subreddit.submit(title=title + " [Video yüklenemedi - Twitter linkini kontrol edin]", selftext=(remainder_text or ""), flair_id=selected_flair_id)
                    print(f"[+] Alternatif text post gönderildi: {submission.url}")
                    return True
                
        else:
            print(f"[!] Desteklenmeyen dosya türü: {ext}")
            submission = subreddit.submit(title=title, selftext=(remainder_text or ""), flair_id=selected_flair_id)
            print(f"[+] Text post gönderildi: {submission.url}")
            return True
            
    except Exception as e:
        print(f"[HATA] Post gönderimi başarısız: {e}")
        
        # Hata durumunda bile text post göndermeyi dene
        try:
            print("[!] Hata sonrası text post deneniyor...")
            submission = subreddit.submit(title=title + " [Medya yüklenemedi]", selftext=(remainder_text or ""), flair_id=selected_flair_id)
            print(f"[+] Hata sonrası text post gönderildi: {submission.url}")
            return True
        except Exception as text_e:
            print(f"[HATA] Text post bile gönderilemedi: {text_e}")
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
    """Daha önce gönderilmiş tweet ID'lerini veritabanından veya dosyadan yükle"""
    # 1) Veritabanı kullanılabiliyorsa DB'den oku
    if USE_DB_FOR_POSTED_IDS:
        try:
            _ensure_posted_ids_table()
            ids = _db_load_posted_ids()
            print(f"[+] DB'den {len(ids)} adet önceki tweet ID'si yüklendi")
            return set(ids)
        except Exception as e:
            if FAIL_IF_DB_UNAVAILABLE:
                raise RuntimeError(f"DB gerekli ancak erişilemedi (load): {e}")
            print(f"[UYARI] DB'den posted_tweet_ids yüklenemedi, dosyaya düşülecek: {e}")
    # 2) Dosya fallback
    posted_ids_file = "posted_tweet_ids.txt"
    posted_ids = set()
    try:
        if os.path.exists(posted_ids_file):
            with open(posted_ids_file, 'r', encoding='utf-8') as f:
                for line in f:
                    tweet_id = line.strip()
                    if tweet_id:
                        posted_ids.add(tweet_id)
            print(f"[+] (Fallback) {len(posted_ids)} adet önceki tweet ID'si dosyadan yüklendi")
        else:
            print("[INFO] (Fallback) posted_tweet_ids.txt mevcut değil; yeni oluşturulabilir")
    except Exception as e:
        print(f"[UYARI] (Fallback) Posted tweet IDs yüklenirken hata: {e}")
    return posted_ids

def save_posted_tweet_id(tweet_id):
    """Yeni gönderilmiş tweet ID'sini veritabanına veya dosyaya kaydet"""
    # 1) Veritabanı kullanılabiliyorsa önce DB'ye yaz
    if USE_DB_FOR_POSTED_IDS:
        try:
            _ensure_posted_ids_table()
            _db_save_posted_id(tweet_id)
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

def _db_connect():
    """Get a psycopg2 connection using DATABASE_URL.
    Defensively sanitize common misconfigurations like values starting with
    'DATABASE_URL=' or surrounding quotes coming from platform dashboards.
    """
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
    # Brief masked log to help diagnose format issues (do not print secrets)
    try:
        masked = dsn
        if "://" in masked and "@" in masked:
            # postgres://user:pass@host -> mask pass
            proto, rest = masked.split("://", 1)
            creds_host = rest.split("@", 1)
            if len(creds_host) == 2:
                creds, hostpart = creds_host
                if ":" in creds:
                    u, _p = creds.split(":", 1)
                    creds = f"{u}:***"
                masked = f"{proto}://{creds}@{hostpart}"
        print(f"[DEBUG] Using DB DSN: {masked}")
    except Exception:
        pass
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
    """TheBFWire timeline'ını twscrape ile oku (birincil),
    reply/retweet'leri ele ve medya URL'lerini çıkar. Hata olursa Pnytter/RSS fallback.
    Dönüş: list[{'id','text','created_at','media_urls'}]
    """
    try:
        # Global rate-limit uygula
        global LAST_REQUEST_TIME
        current_time = time.time()
        time_since_last_request = current_time - LAST_REQUEST_TIME
        if time_since_last_request < MIN_REQUEST_INTERVAL:
            wait_time = MIN_REQUEST_INTERVAL - time_since_last_request
            print(f"[+] (TL) Rate limiting: {int(wait_time)} saniye bekleniyor...")
            time.sleep(wait_time)
        LAST_REQUEST_TIME = time.time()

        def _twscrape_fetch_sync():
            async def _run():
                try:
                    api = await init_twscrape_api()
                    # Kullanıcıyı login ile getir
                    user = await api.user_by_login(TWITTER_SCREENNAME)
                    if not user:
                        return []
                    out = []
                    # Daha fazlasını çekip filtreleyeceğimiz için limit*3 oku
                    async for tw in api.user_tweets(user.id, limit=max(10, count * 3)):
                        # Reply veya retweet olanları atla
                        if getattr(tw, 'inReplyToTweetId', None):
                            continue
                        if getattr(tw, 'retweetedTweet', None):
                            continue

                        # Medya URL'lerini çıkar
                        media_urls: list[str] = []
                        md = getattr(tw, 'media', None)
                        if md:
                            for p in getattr(md, 'photos', []) or []:
                                if getattr(p, 'url', None):
                                    media_urls.append(p.url)
                            for v in getattr(md, 'videos', []) or []:
                                variants = getattr(v, 'variants', []) or []
                                if variants:
                                    best = max(variants, key=lambda x: getattr(x, 'bitrate', 0))
                                    if getattr(best, 'url', None):
                                        media_urls.append(best.url)
                            for a in getattr(md, 'animated', []) or []:
                                if getattr(a, 'videoUrl', None):
                                    media_urls.append(a.videoUrl)

                        out.append({
                            'id': str(getattr(tw, 'id', getattr(tw, 'id_str', ''))),
                            'text': getattr(tw, 'rawContent', ''),
                            'created_at': getattr(tw, 'date', None),
                            'media_urls': media_urls,
                            'url': getattr(tw, 'url', None),
                        })
                        if len(out) >= count:
                            break
                    # Eskiden yeniye sırala
                    try:
                        out.sort(key=_tweet_sort_key, reverse=False)
                    except Exception:
                        pass
                    return out
                except Exception as e:
                    print(f"[UYARI] twscrape timeline hatası: {e}")
                    return []

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_run())
            finally:
                loop.close()

        # 1) TWSCRAPE PRIMARY
        normalized = _twscrape_fetch_sync()
        if normalized:
            return normalized

        # 2) FALLBACKS
        tweets = _fallback_pnytter_tweets(count=count) or []
        if not tweets:
            tweets = _fallback_rss_tweets(count=count) or []

        out = []
        for t in tweets:
            try:
                tid = (
                    t.get('id') if isinstance(t, dict) else None
                ) or (
                    t.get('tweet_id') if isinstance(t, dict) else None
                ) or (
                    t.get('id_str') if isinstance(t, dict) else None
                ) or (
                    t.get('rest_id') if isinstance(t, dict) else None
                )
                tid = str(tid).strip() if tid is not None else ''
                if not tid:
                    continue

                text = (t.get('text') if isinstance(t, dict) else '') or ''
                if _is_reply_text(text):
                    continue
                low = text.strip().lower()
                if low.startswith('rt '):
                    continue
                if _is_retweet_of_target(text, TWITTER_SCREENNAME):
                    continue

                out.append({
                    'id': tid,
                    'text': text,
                    'created_at': t.get('created_at') if isinstance(t, dict) else None,
                    'media_urls': (t.get('media_urls') if isinstance(t, dict) else []) or []
                })
                if len(out) >= count:
                    break
            except Exception:
                continue
        return out
    except Exception as e:
        print(f"[HATA] get_latest_tweets_with_retweet_check hata: {e}")
        return []

def main_loop():
    # Persistent storage ile posted tweet IDs'leri yükle
    posted_tweet_ids = load_posted_tweet_ids()
    
    print("[+] Reddit Bot başlatılıyor...")
    print(f"[+] Subreddit: r/{SUBREDDIT}")
    print(f"[+] Twitter: @{TWITTER_SCREENNAME}")
    print("[+] Retweet'ler otomatik olarak atlanacak")
    print(f"[+] Şu ana kadar {len(posted_tweet_ids)} tweet işlenmiş")
    
    while True:
        try:
            print("\n" + "="*50)
            print(f"[+] Tweet kontrol ediliyor... ({time.strftime('%Y-%m-%d %H:%M:%S')})")
            
            # Son 8 tweet'i al ve retweet kontrolü yap (daha fazla tweet kontrol et)
            tweets_data = get_latest_tweets_with_retweet_check(8)
            
            if isinstance(tweets_data, dict) and "error" in tweets_data:
                print(f"[!] Hata oluştu: {tweets_data['error']}")
                print(f"[!] {NITTER_REQUEST_DELAY} saniye sonra tekrar denenecek...")
                time.sleep(NITTER_REQUEST_DELAY)
                continue
            elif not tweets_data:
                print("[!] Tweet bulunamadı veya API hatası.")
                time.sleep(NITTER_REQUEST_DELAY)
                continue
            
            tweets = tweets_data if isinstance(tweets_data, list) else tweets_data.get("tweets", [])
            if not tweets:
                print("[!] İşlenecek tweet bulunamadı.")
                time.sleep(NITTER_REQUEST_DELAY)
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
                    continue
                
                if tweet_id in posted_tweet_ids:
                    print(f"[!] Tweet {tweet_index}/{len(tweets)} zaten işlendi: {tweet_id}")
                    continue
                
                print(f"[+] Tweet {tweet_index}/{len(tweets)} işleniyor: {tweet_id}")
                posted_tweet_ids.add(tweet_id)
                save_posted_tweet_id(tweet_id)
                print(f"[+] Tweet ID kaydedildi (işlem öncesi): {tweet_id}")
                print(f"[+] Tweet linki: https://x.com/{TWITTER_SCREENNAME}/status/{tweet_id}")
                
                # Tweet metni ve çeviri
                text = tweet_data.get("text", "")
                print(f"[+] Orijinal Tweet: {text[:100]}{'...' if len(text) > 100 else ''}")
                cleaned_text = clean_tweet_text(text)
                print(f"[+] Temizlenmiş Tweet: {cleaned_text[:100]}{'...' if len(cleaned_text) > 100 else ''}")
                translated = translate_text(cleaned_text)
                if translated:
                    print(f"[+] Çeviri: {translated[:100]}{'...' if len(translated) > 100 else ''}")
                else:
                    print(f"[UYARI] Çeviri başarısız, tweet atlanıyor: {tweet_id}")
                    continue
                
                # Medya çıkarımı
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
                
                # Videolar
                for i, media_url in enumerate(video_urls):
                    try:
                        filename = f"temp_video_{tweet_id}_{i}.mp4"
                        print(f"[+] Video indiriliyor ({i+1}/{len(video_urls)}): {media_url[:50]}...")
                        path = download_media(media_url, filename)
                        if path:
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
                            print(f"[!] Video indirilemedi: {media_url}")
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
                if isinstance(tweets, list) and len(tweets) >= 8:
                    print("\n" + "-"*50)
                    print("[+] Ek görev: @bf6_tr retweet'leri işleniyor (aynı pipeline)...")
                    rt_list = get_latest_bf6_retweets(8)
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
                                continue
                            if tweet_id in posted_tweet_ids:
                                print(f"[!] RT {rt_index}/{len(rt_list)} zaten işlendi: {tweet_id}")
                                continue
                            print(f"[+] RT {rt_index}/{len(rt_list)} işleniyor: {tweet_id}")
                            posted_tweet_ids.add(tweet_id)
                            save_posted_tweet_id(tweet_id)
                            print(f"[+] RT ID kaydedildi (işlem öncesi): {tweet_id}")
                            print(f"[+] RT linki: https://x.com/{TWITTER_SCREENNAME}/status/{tweet_id}")

                            text = tweet_data.get("text", "")
                            print(f"[+] Orijinal RT Metin: {text[:100]}{'...' if len(text) > 100 else ''}")
                            cleaned_text = clean_tweet_text(text)
                            print(f"[+] Temizlenmiş RT Metin: {cleaned_text[:100]}{'...' if len(cleaned_text) > 100 else ''}")
                            # 'Kaynak' BAŞLIĞI: yalnızca temizleme sonrası metin tamamen boşsa
                            fallback_source_title = None
                            if not cleaned_text.strip():
                                rt_url = tweet_data.get("url") or f"https://x.com/i/web/status/{tweet_id}"
                                rt_author = extract_username_from_tweet_url(rt_url)
                                fallback_source_title = f"Kaynak: @{rt_author}"
                                translated = None
                                print(f"[INFO] RT temizlenince metin boş, başlık kaynak olarak ayarlanacak: {fallback_source_title}")
                            else:
                                translated = translate_text(cleaned_text)
                            if translated:
                                print(f"[+] RT Çeviri: {translated[:100]}{'...' if len(translated) > 100 else ''}")
                            elif fallback_source_title:
                                # Çeviri yok ama kaynak başlığı mevcut; devam edilecek
                                print("[INFO] RT çeviri atlandı, kaynak başlığı kullanılacak")
                            else:
                                print(f"[UYARI] RT çeviri başarısız, atlanıyor: {tweet_id}")
                                continue

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

                            for i, media_url in enumerate(video_urls):
                                try:
                                    filename = f"temp_video_{tweet_id}_{i}.mp4"
                                    print(f"[+] RT Video indiriliyor ({i+1}/{len(video_urls)}): {media_url[:50]}...")
                                    path = download_media(media_url, filename)
                                    if path:
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
                                        print(f"[!] RT Video indirilemedi: {media_url}")
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
    # Lokal geliştirme/test için HTTP sunucusunu ayağa kaldır
    port = int(os.getenv("PORT", "8000"))
    print(f"[WEB] Uvicorn ile FastAPI başlatılıyor :0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
