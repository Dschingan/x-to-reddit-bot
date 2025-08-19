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
import random
import hashlib
import requests
import subprocess
from pathlib import Path
from urllib.parse import unquote
from PIL import Image
import io
import asyncio
from bs4 import BeautifulSoup
from base64 import b64decode

# RedditWarp imports
import redditwarp.SYNC
from redditwarp.SYNC import Client as RedditWarpClient

# Windows encoding sorununu çöz
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

load_dotenv()

SUBREDDIT = "bf6_tr"

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT = "python:bf6-gaming-news-bot:v1.1.0 (by /u/BFHaber_Bot)"
RAPIDAPI_TRANSLATE_KEY = os.getenv("RAPIDAPI_TRANSLATE_KEY")

# Nitter configuration
_DEFAULT_NITTER_INSTANCES = [
    "https://twitt.re",             # Prefer first
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.fdn.fr",
    "https://nitter.esmailelbob.xyz",
    "https://nitter.kavin.rocks",
    "https://n.func.dev",
    "https://nitter.moomoo.me",
    "https://nitter.namazso.eu",
    "https://nitter.1d4.us",
]
# Allow override via env: NITTER_INSTANCES=https://a,https://b
_env_instances = os.getenv("NITTER_INSTANCES", "").strip()
if _env_instances:
    NITTER_INSTANCES = [u.strip() for u in _env_instances.split(",") if u.strip()]
else:
    NITTER_INSTANCES = _DEFAULT_NITTER_INSTANCES[:]
CURRENT_NITTER_INDEX = 0
TWITTER_SCREENNAME = "TheBFWire"
NITTER_REQUEST_DELAY = 5  # seconds between requests
MAX_RETRIES = 3  # Maximum number of retries for failed requests

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

def clean_tweet_text(text):
    if not text:
        return ""
    # RT @TheBFWire: ifadesini kaldır
    text = re.sub(r'^RT @TheBFWire:\s*', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r't\.co/\S+', '', text)
    text = re.sub(r'#\w+', '', text)
    text = text.replace('|', '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_latest_tweets_with_retweet_check(count=3, retry_count=0):
    """Nitter üzerinden son tweet'leri al, retweet/pin'leri atla, medya URL'lerini çıkar.
    Öncelik: nitter-scraper (twitt.re -> nitter.net), başarısız olursa mevcut RSS fallback.
    """
    global CURRENT_NITTER_INDEX

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
        # Prefer first two, then randomize the rest
        preferred = NITTER_INSTANCES[:2]
        others = NITTER_INSTANCES[2:]
        random.shuffle(others)
        try_order = [*preferred, *others]

        from datetime import datetime, timedelta
        to_dt = datetime.utcnow()
        from_dt = to_dt - timedelta(days=3)  # even smaller window to reduce search workload

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
                print(f"[+] Pnytter instance deneniyor: {inst}")
                pny = Pnytter(nitter_instances=[inst])
                # Try a couple of times per instance to bypass transient 429/403
                per_inst_attempts = 0
                pny_tweets = None
                while per_inst_attempts < 2 and pny_tweets is None:
                    per_inst_attempts += 1
                    try:
                        # Some versions require a range
                        try:
                            pny_tweets = pny.get_user_tweets_list(TWITTER_SCREENNAME)
                        except TypeError:
                            pny_tweets = pny.get_user_tweets_list(
                                TWITTER_SCREENNAME,
                                filter_from=from_dt.strftime('%Y-%m-%d'),
                                filter_to=to_dt.strftime('%Y-%m-%d'),
                            )
                    except Exception as inner_e:
                        msg = str(inner_e)
                        if '429' in msg or 'Forbidden' in msg or '403' in msg:
                            sleep_s = 3 + per_inst_attempts * 2 + random.uniform(0, 2)
                            print(f"[UYARI] {inst} yanıtı: {msg} -> {int(sleep_s)} sn bekle ve yeniden dene")
                            time.sleep(sleep_s)
                        else:
                            raise

                slice_count = max(count * 3, 10)
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
                    has_punct = any(ch in raw_txt for ch in [':', '-', '—', '!', '?', '“', '”', '"', '\''])
                    has_domain_terms = any(k in raw_txt for k in ['BF', 'Battlefield', 'battlefield', 'BF6'])
                    short_len_threshold = 50
                    if (len(raw_txt.strip()) < short_len_threshold) and not (has_url or has_hashtag or has_punct or has_domain_terms):
                        print(f"[INFO] Kısa/bağlamsız tweet atlandı (muhtemel yanıt): {tid} -> '{raw_txt[:80]}'")
                        continue
                    # Nitter HTML'den medya URL'leri topla (çoklu instance dene)
                    media_urls = _fetch_media_from_nitter_html_multi(TWITTER_SCREENNAME, tid, preferred=inst) or []
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
                print(f"[UYARI] Pnytter instance başarısız: {inst} -> {_per_inst_err}")
                time.sleep(1)
        print("[!] Pnytter ile uygun tweet bulunamadı, RSS fallback deneniyor")
    except Exception as e:
        print(f"[UYARI] Pnytter kullanımı başarısız veya mevcut değil: {e}. RSS fallback deneniyor")

    # 2) RSS fallback (mevcut mantık, instance fallback ve retry ile)
    nitter_instance = NITTER_INSTANCES[CURRENT_NITTER_INDEX]
    url = f"{nitter_instance}/{TWITTER_SCREENNAME}/rss"
    try:
        print(f"[+] RSS ile çekiliyor: {nitter_instance}")
        ua_pool = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
        ]
        headers = {
            'User-Agent': random.choice(ua_pool),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.content)
        items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}item')

        tweets = []
        slice_count = max(count * 3, 10)
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
            has_punct = any(ch in raw_text for ch in [':', '-', '—', '!', '?', '“', '”', '"', '\''])
            has_domain_terms = any(k in raw_text for k in ['BF', 'Battlefield', 'battlefield', 'BF6'])
            short_len_threshold = 50
            cleaned_len = len(clean_tweet_text(raw_text))
            if (cleaned_len < short_len_threshold) and not (has_url or has_hashtag or has_punct or has_domain_terms):
                print(f"[INFO] Kısa ve bağlamsız tweet atlandı (muhtemel yanıt, RSS)")
                continue
            tweet_id = link.split('/')[-1].split('#')[0]
            tweet_text = clean_tweet_text(description)
            # Nitter HTML'den medya URL'leri topla (öncelikli, çoklu instance dene)
            media_urls = _fetch_media_from_nitter_html_multi(TWITTER_SCREENNAME, tweet_id, preferred=nitter_instance) or []
            if not media_urls and 'pic.twitter.com' in description:
                media_matches = re.findall(r'pic\.twitter\.com/[\w]+', description)
                media_urls = [f"https://{m}" for m in media_matches]
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
        print(f"[HATA] RSS istek hatası ({nitter_instance}): {e}")
        # 429 özel backoff
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        if status == 429:
            jitter = random.uniform(0, 3)
            backoff = min(300, (retry_count + 1) * NITTER_REQUEST_DELAY * 2 + jitter)
            print(f"[!] 429 Too Many Requests - {int(backoff)} sn bekleniyor...")
            time.sleep(backoff)
        # Sonraki instance'a geç
        if retry_count < MAX_RETRIES and (CURRENT_NITTER_INDEX + 1) < len(NITTER_INSTANCES):
            CURRENT_NITTER_INDEX += 1
            print(f"[!] Bir sonraki Nitter instance'ı deneniyor: {NITTER_INSTANCES[CURRENT_NITTER_INDEX]}")
            time.sleep(NITTER_REQUEST_DELAY)
            return get_latest_tweets_with_retweet_check(count, retry_count + 1)
        # Son şans da başarısızsa boş liste dön (sürekli gürültü yapmamak için)
        return {"tweets": []}
    except Exception as e:
        print(f"[HATA] RSS fallback beklenmeyen hata: {e}")
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
        s = requests.Session()
        ua_pool = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
        ]
        s.headers.update({
            'User-Agent': random.choice(ua_pool),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Host': base.split('://', 1)[1],
        })

        resp = s.get(url, cookies={'hlsPlayback': 'on'}, timeout=15)
        resp.raise_for_status()
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

def _fetch_media_from_nitter_html_multi(screen_name: str, tweet_id: str, preferred: str = None):
    """Birden fazla Nitter instance'ını deneyerek HTML'den medya URL'leri çıkarmayı dener."""
    try_list = []
    if preferred:
        try_list.append(preferred)
    # Kalanları ekle (tekrar olmasın)
    for inst in NITTER_INSTANCES:
        if inst not in try_list:
            try_list.append(inst)

    for inst in try_list:
        try:
            media = _fetch_media_from_nitter_html(inst, screen_name, tweet_id)
            if media:
                return media
        except Exception as e:
            # 4xx durumlarında sıradaki instance'a geç
            msg = str(e)
            if any(code in msg for code in ['403', '404', '418', '429']):
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
    return []

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
    # Boş metin veya API anahtarı yoksa çevirmeden geri döndür
    if not text or not text.strip():
        return ""
    if not RAPIDAPI_TRANSLATE_KEY:
        print("[!] RAPIDAPI_TRANSLATE_KEY bulunamadı, çeviri atlanıyor")
        return text

    translate_url = "https://translateai.p.rapidapi.com/google/translate/json"
    payload = {
        "origin_language": "en",
        "target_language": "tr",
        "words_not_to_translate": "Battlefield",
        "paths_to_exclude": "product.media.img_desc",
        "common_keys_to_exclude": "name; price",
        "json_content": {
            "product": {
                "productDesc": text
            }
        }
    }
    headers = {
        "x-rapidapi-key": RAPIDAPI_TRANSLATE_KEY,
        "x-rapidapi-host": "translateai.p.rapidapi.com",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(translate_url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        translated = data.get('translated_json', {}).get('product', {}).get('productDesc')
        if translated:
            return translated
        print("[UYARI] Çeviri boş döndü, orijinal metin kullanılacak")
        return text
    except requests.exceptions.RequestException as rexc:
        print(f"[UYARI] Çeviri servisine ulaşılamadı: {rexc}")
        return text
    except Exception as e:
        print("Çeviri alınamadı:", e)
        return text

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
            # Sadece resim dosyalarını işle
            if not any(ext in media_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
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
        
        # OPTIMIZE EDİLMİŞ FFmpeg komutu - 4K video ve bellek sorunları için
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-c:v", "libx264",
            "-profile:v", "baseline",  # En uyumlu profil
            "-level", "3.1",  # Daha düşük level (daha az bellek)
            "-preset", "fast",  # Hızlı işlem için
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
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)  # 5 dakika timeout
        
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
        print("[HATA] FFmpeg timeout - Video çok karmaşık")
        return None
    except Exception as e:
        print(f"[HATA] Video dönüştürme hatası: {e}")
        return None

def upload_gallery_via_redditwarp(title, image_paths, subreddit_name):
    """RedditWarp ile birden fazla resmi gallery olarak yükle"""
    if not redditwarp_client:
        print("[HATA] RedditWarp client mevcut değil")
        return False
        
    if not image_paths:
        print("[HATA] Yüklenecek resim yok")
        return False
        
    try:
        print(f"[+] {len(image_paths)} resim için gallery oluşturuluyor...")
        
        # Her resim için upload lease al
        image_leases = []
        for i, image_path in enumerate(image_paths):
            print(f"[+] Resim {i+1}/{len(image_paths)} yükleniyor: {os.path.basename(image_path)}")
            
            if not os.path.exists(image_path):
                print(f"[HATA] Resim dosyası bulunamadı: {image_path}")
                continue
                
            try:
                with open(image_path, 'rb') as image_file:
                    # RedditWarp ile resim upload
                    image_lease = redditwarp_client.p.submission.media_uploading.upload(image_file)
                    image_leases.append({
                        'media_id': image_lease.media_id,
                        'location': image_lease.location,
                        'caption': f"Resim {i+1}"
                    })
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
            gallery_items = []
            for lease in image_leases:
                gallery_items.append({
                    'media_id': lease['media_id'],
                    'caption': lease['caption']
                })
            
            created = redditwarp_client.p.submission.create.gallery(
                sr=subreddit_name,
                title=title,
                items=gallery_items
            )
            
            if created:
                submission_id = getattr(created, 'id', str(created))
                print(f"[+] Gallery başarıyla oluşturuldu - ID: {submission_id}")
                print(f"[+] URL: https://reddit.com/r/{subreddit_name}/comments/{submission_id}")
                return created
            else:
                print("[HATA] Gallery oluşturulamadı")
                return False
                
        except Exception as gallery_e:
            print(f"[HATA] Gallery oluşturma hatası: {gallery_e}")
            return False
            
    except Exception as e:
        print(f"[HATA] RedditWarp gallery yükleme genel hatası: {e}")
        import traceback
        traceback.print_exc()
        return False

def upload_video_via_redditwarp(title, media_path, subreddit_name):
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
            else:
                print("[UYARI] RedditWarp oluşturulan gönderi ID'si alınamadı")
                submission_id = ""
                
            # Video processing bekle
            print("[+] Video processing için 30 saniye bekleniyor...")
            time.sleep(30)
            
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
        warp_result = upload_video_via_redditwarp(title, media_path, subreddit_name)
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
            # Başarılıysa Submission nesnesini döndür
            return submission
        else:
            print("[HATA] PRAW submission oluşturulamadı")
            return False
            
    except Exception as praw_e:
        print(f"[HATA] PRAW fallback hatası: {praw_e}")
        return False

def try_alternative_upload(title, media_path, subreddit):
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
            selftext=""
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
    
    # Önce resimleri gallery olarak yükle (eğer birden fazla resim varsa)
    if len(image_files) > 1:
        print(f"[+] {len(image_files)} resim gallery olarak yükleniyor...")
        gallery_result = upload_gallery_via_redditwarp(title, image_files, SUBREDDIT)
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
            print("[!] Gallery yüklenemedi, tekil resim yükleme deneniyor...")
    
    # Tekil resim veya video yükleme (mevcut kod)
    
    # AI ile flair seçimi
    selected_flair_id = select_flair_with_ai(title, original_tweet_text)
    print(f"[+] Seçilen flair ID: {selected_flair_id}")
    
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
    """Daha önce gönderilmiş tweet ID'lerini dosyadan yükle"""
    posted_ids_file = "posted_tweet_ids.txt"
    posted_ids = set()
    
    try:
        if os.path.exists(posted_ids_file):
            with open(posted_ids_file, 'r', encoding='utf-8') as f:
                for line in f:
                    tweet_id = line.strip()
                    if tweet_id:
                        posted_ids.add(tweet_id)
            print(f"[+] {len(posted_ids)} adet önceki tweet ID'si yüklendi")
        else:
            print("[+] Yeni posted_tweet_ids.txt dosyası oluşturulacak")
    except Exception as e:
        print(f"[UYARI] Posted tweet IDs yüklenirken hata: {e}")
    
    return posted_ids

def save_posted_tweet_id(tweet_id):
    """Yeni gönderilmiş tweet ID'sini dosyaya kaydet"""
    posted_ids_file = "posted_tweet_ids.txt"
    
    try:
        with open(posted_ids_file, 'a', encoding='utf-8') as f:
            f.write(f"{tweet_id}\n")
        print(f"[+] Tweet ID kaydedildi: {tweet_id}")
    except Exception as e:
        print(f"[UYARI] Tweet ID kaydedilirken hata: {e}")

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
            
            # Son 5 tweet'i al ve retweet kontrolü yap
            tweets_data = get_latest_tweets_with_retweet_check(5)
            
            if "error" in tweets_data:
                print(f"[!] Hata oluştu: {tweets_data['error']}")
                print(f"[!] {NITTER_REQUEST_DELAY} saniye sonra tekrar denenecek...")
                time.sleep(NITTER_REQUEST_DELAY)
                continue
            elif not tweets_data:
                print("[!] Tweet bulunamadı veya API hatası.")
                time.sleep(NITTER_REQUEST_DELAY)
                continue
            # Tüm öğeler retweet ise artık uzun bekleme yok, kısa bekleme ile devam
                
            tweets = tweets_data.get("tweets", [])
            if not tweets:
                print("[!] İşlenecek tweet bulunamadı.")
                time.sleep(NITTER_REQUEST_DELAY)
                continue
            
            # Eskiden yeniye işle
            tweets = list(reversed(tweets))
            print(f"[+] {len(tweets)} tweet bulundu, eskiden yeniye doğru işlenecek...")
            
            # Her tweet'i eskiden yeniye doğru işle
            for tweet_index, tweet_data in enumerate(tweets, 1):
                tweet_id = tweet_data.get("tweet_id")
                
                if not tweet_id:
                    print(f"[HATA] Tweet {tweet_index}/3 - Tweet ID bulunamadı!")
                    continue
                
                if tweet_id in posted_tweet_ids:
                    print(f"[!] Tweet {tweet_index}/3 zaten işlendi: {tweet_id}")
                    continue  # Bu tweet'i atla ve sonrakine geç
                else:
                    print(f"[+] Tweet {tweet_index}/3 işleniyor: {tweet_id}")
                    
                    # Tweet ID'sini hemen kaydet (işlem başlamadan önce)
                    posted_tweet_ids.add(tweet_id)
                    save_posted_tweet_id(tweet_id)
                    print(f"[+] Tweet ID kaydedildi (işlem öncesi): {tweet_id}")
                    
                    # Tweet işleme
                    text = tweet_data.get("text", "")
                    print(f"[+] Orijinal Tweet: {text[:100]}{'...' if len(text) > 100 else ''}")
                    
                    cleaned_text = clean_tweet_text(text)
                    print(f"[+] Temizlenmiş Tweet: {cleaned_text[:100]}{'...' if len(cleaned_text) > 100 else ''}")
                    
                    translated = translate_text(cleaned_text)
                    print(f"[+] Çeviri: {translated[:100]}{'...' if len(translated) > 100 else ''}")
                    
                    # Medya işleme - zaten çekilmiş veriden
                    print("[+] Medya URL'leri çıkarılıyor...")
                    media_urls = get_media_urls_from_tweet_data(tweet_data)
                    media_files = []
                    
                    # Resimleri ve videoları ayır
                    image_urls = []
                    video_urls = []
                    
                    for media_url in media_urls:
                        if any(ext in media_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                            image_urls.append(media_url)
                        elif '.mp4' in media_url.lower():
                            video_urls.append(media_url)
                    
                    print(f"[+] Medya analizi: {len(image_urls)} resim, {len(video_urls)} video")
                    
                    # Birden fazla resim varsa toplu indirme kullan
                    if len(image_urls) > 1:
                        print("[+] Birden fazla resim tespit edildi, toplu indirme başlatılıyor...")
                        downloaded_images = download_multiple_images(image_urls, tweet_id)
                        media_files.extend(downloaded_images)
                    elif len(image_urls) == 1:
                        # Tek resim için normal indirme
                        media_url = image_urls[0]
                        ext = os.path.splitext(media_url)[1].split("?")[0] or ".jpg"
                        filename = f"temp_image_{tweet_id}_0{ext}"
                        print(f"[+] Tek resim indiriliyor: {media_url[:50]}...")
                        path = download_media(media_url, filename)
                        if path:
                            media_files.append(path)
                            print(f"[+] Resim hazır: {path}")
                    
                    # Videoları işle (mevcut kod)
                    for i, media_url in enumerate(video_urls):
                        try:
                            ext = ".mp4"
                            filename = f"temp_video_{tweet_id}_{i}{ext}"
                            
                            print(f"[+] Video indiriliyor ({i+1}/{len(video_urls)}): {media_url[:50]}...")
                            path = download_media(media_url, filename)
                            
                            if path:
                                # Video dönüştürme
                                converted = f"converted_{filename}"
                                print(f"[+] Video dönüştürülüyor: {path} -> {converted}")
                                converted_path = convert_video_to_reddit_format(path, converted)
                                
                                if converted_path:
                                    media_files.append(converted_path)
                                    print(f"[+] Video dönüştürme başarılı: {converted_path}")
                                else:
                                    print("[!] Video dönüştürme başarısız")
                                
                                # Orijinal dosyayı sil
                                if os.path.exists(path):
                                    os.remove(path)
                            else:
                                print(f"[!] Video indirilemedi: {media_url}")
                                
                        except Exception as media_e:
                            print(f"[HATA] Video işleme hatası: {media_e}")
                        
                    print(f"[+] Toplam {len(media_files)} medya dosyası hazır")
                    
                    # Post gönderme
                    # Başlık oluşturma ve doğrulama (çeviri -> temizlenmiş -> orijinal -> varsayılan)
                    candidates = [
                        (translated or "").strip(),
                        (cleaned_text or "").strip(),
                        (text or "").strip(),
                    ]
                    chosen_text = next((c for c in candidates if c), "")
                    if not chosen_text:
                        chosen_text = f"@{TWITTER_SCREENNAME} paylaşımı - {tweet_id}"
                    # Uzun metni başlık + kalan olarak böl
                    title_to_use, remainder_to_post = smart_split_title(chosen_text, 300)
                    print(f"[+] Kullanılacak başlık ({len(title_to_use)}): {title_to_use[:80]}{'...' if len(title_to_use) > 80 else ''}")
                    if remainder_to_post:
                        print(f"[+] Başlığın kalan kısmı ({len(remainder_to_post)} karakter) gönderi açıklaması/yorum olarak eklenecek")
                    print("[+] Reddit'e post gönderiliyor...")
                    success = submit_post(title_to_use, media_files, text, remainder_text=remainder_to_post)  # Orijinal tweet text'i yedek olarak gönder
                    
                    if success:
                        print(f"[+] Tweet başarıyla işlendi: {tweet_id}")
                    else:
                        print(f"[UYARI] Tweet işlenemedi ama ID zaten kaydedildi: {tweet_id}")
                        
                        # Geçici dosyaları temizle
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
                        time.sleep(300)  # 5 dakika = 300 saniye
                            
        except Exception as loop_e:
            print(f"[HATA] Ana döngü hatası: {loop_e}")
            import traceback
            traceback.print_exc()
        
        print(f"\n[+] Sonraki kontrol: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + 5184))}")
        print("⏳ 1 saat 26 dakika bekleniyor...")
        time.sleep(5184)  # 1 saat 26 dakika (5184 saniye)

if __name__ == "__main__":
    while True:
        try:
            print("[+] Bot başlatılıyor...")
            main_loop()
        except KeyboardInterrupt:
            print("\n[!] Bot durduruldu (Ctrl+C)")
            break
        except Exception as e:
            print(f"\n[HATA] Kritik hata: {e}")
            import traceback
            traceback.print_exc()
            print("\n[+] 30 saniye sonra yeniden başlatılıyor...")
            time.sleep(30)
            continue
