import os
import sys
import time
import logging
import sqlite3
import threading
import schedule
import requests
import shutil
import mimetypes
from pathlib import Path
from datetime import timedelta
from typing import List, Optional, Dict
from collections import deque

# 3rd Party Imports
import praw
import tweepy
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# --- KONFİGÜRASYON VE LOGGING ---

load_dotenv()

# Loglama Ayarları
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[
    logging.FileHandler("bot.log", encoding='utf-8'),
    logging.StreamHandler(sys.stdout)
])
logger = logging.getLogger("BF6Bot")

# Admin paneli için log geçmişi
log_capture_string = deque(maxlen=200)

class ListHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        log_capture_string.append(log_entry)

list_handler = ListHandler()
list_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(list_handler)

# --- VERİTABANI YÖNETİCİSİ ---

class DatabaseManager:
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv('DATABASE_URL')
        self.is_postgres = bool(self.db_url)
        self.local_db = "bot_data.db"
        self._init_db()

    def _get_connection(self):
        if self.is_postgres:
            return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
        return sqlite3.connect(self.local_db)

    def _init_db(self):
        query_posted = """
        CREATE TABLE IF NOT EXISTS posted_tweets (
            tweet_id TEXT PRIMARY KEY,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(query_posted)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Veritabanı başlatma hatası: {e}")

    def is_posted(self, tweet_id: str) -> bool:
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            if self.is_postgres:
                cur.execute("SELECT 1 FROM posted_tweets WHERE tweet_id = %s", (str(tweet_id),))
            else:
                cur.execute("SELECT 1 FROM posted_tweets WHERE tweet_id = ?", (str(tweet_id),))
            result = cur.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            logger.error(f"DB Read Error: {e}")
            return False

    def mark_as_posted(self, tweet_id: str):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            if self.is_postgres:
                cur.execute("INSERT INTO posted_tweets (tweet_id) VALUES (%s) ON CONFLICT DO NOTHING", (str(tweet_id),))
            else:
                cur.execute("INSERT OR IGNORE INTO posted_tweets (tweet_id) VALUES (?)", (str(tweet_id),))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Write Error: {e}")

# --- TWITTER SERVİSİ (API v2) ---

class TwitterService:
    def __init__(self):
        # HATA DÜZELTME: Hem yeni hem eski isme bakıyoruz
        self.bearer_token = os.getenv("TWITTER_API_V2_BEARER_TOKEN") or os.getenv("TWITTER_BEARER_TOKEN")
        self.target_username = os.getenv("TWITTER_SCREENNAME", "BF6Media")
        self.client = None
        
        if self.bearer_token:
            try:
                self.client = tweepy.Client(bearer_token=self.bearer_token, wait_on_rate_limit=True)
                logger.info("Twitter servisi başlatıldı.")
            except Exception as e:
                logger.error(f"Twitter Client başlatılamadı: {e}")
        else:
            logger.warning("Twitter Bearer Token EKSİK! (Env ayarlarını kontrol edin)")

    def get_user_id(self, username: str):
        if not self.client: return None
        try:
            user = self.client.get_user(username=username)
            if user.data:
                return user.data.id
            return None
        except Exception as e:
            logger.error(f"Twitter User ID alınamadı: {e}")
            return None

    def get_recent_tweets(self, limit=5) -> List[Dict]:
        if not self.client: return []
        try:
            user_id = self.get_user_id(self.target_username)
            if not user_id: return []

            response = self.client.get_users_tweets(
                id=user_id,
                max_results=min(limit, 100),
                tweet_fields=['created_at', 'lang', 'public_metrics'],
                expansions=['attachments.media_keys'],
                media_fields=['url', 'variants', 'type', 'preview_image_url']
            )

            if not response.data:
                return []

            media_map = {m.media_key: m for m in response.includes['media']} if response.includes and 'media' in response.includes else {}
            tweets = []
            
            for t in response.data:
                if t.text.startswith("RT @"): continue # RT'leri atla

                media_urls = []
                video_url = None
                
                if t.attachments and 'media_keys' in t.attachments:
                    for mk in t.attachments['media_keys']:
                        media = media_map.get(mk)
                        if not media: continue
                        if media.type == 'photo':
                            media_urls.append(media.url)
                        elif media.type == 'video':
                            variants = media.variants
                            best_video = max(
                                [v for v in variants if v.get('content_type') == 'video/mp4'],
                                key=lambda v: v.get('bit_rate', 0),
                                default=None
                            )
                            if best_video:
                                video_url = best_video['url']

                tweets.append({
                    'id': str(t.id),
                    'text': t.text,
                    'created_at': t.created_at,
                    'media_urls': media_urls,
                    'video_url': video_url,
                    'url': f"https://twitter.com/{self.target_username}/status/{t.id}"
                })
            return sorted(tweets, key=lambda x: x['created_at'])
        except Exception as e:
            logger.error(f"Tweet çekme hatası: {e}")
            return []

# --- REDDIT SERVİSİ ---

class RedditService:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            username=os.getenv("REDDIT_USERNAME"),
            password=os.getenv("REDDIT_PASSWORD"),
            user_agent=os.getenv("REDDIT_USER_AGENT", "script:bf6bot:v2.0"),
            check_for_updates=False
        )
        self.subreddit_name = os.getenv("SUBREDDIT", "BF6_TR")
        self.validate_login()

    def validate_login(self):
        try:
            logger.info(f"Reddit girişi yapıldı: u/{self.reddit.user.me()}")
        except Exception as e:
            logger.error(f"Reddit giriş hatası: {e}")

    def download_file(self, url: str, filename: str) -> bool:
        try:
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code == 200:
                with open(filename, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
                return True
        except Exception as e:
            logger.error(f"İndirme hatası: {e}")
        return False

    def post_tweet(self, tweet: Dict):
        """Otomatik Tweet Paylaşımı"""
        try:
            subreddit = self.reddit.subreddit(self.subreddit_name)
            title = tweet['text'].replace("http", " http").split("http")[0].strip() or "Battlefield Gelişmesi"
            flair_id = os.getenv("FLAIR_HABERLER")

            if tweet.get('video_url'):
                vid_file = f"temp_{tweet['id']}.mp4"
                if self.download_file(tweet['video_url'], vid_file):
                    logger.info(f"Otomatik Video Paylaşılıyor: {title}")
                    subreddit.submit_video(title=title, video_path=vid_file, thumbnail_path=None, flair_id=flair_id)
                    os.remove(vid_file)
                    return True
            
            elif tweet.get('media_urls'):
                # Gallery support for auto tweets is complex in PRAW, simplified to first image
                img_file = f"temp_{tweet['id']}.jpg"
                if self.download_file(tweet['media_urls'][0], img_file):
                    logger.info(f"Otomatik Resim Paylaşılıyor: {title}")
                    subreddit.submit_image(title=title, image_path=img_file, flair_id=flair_id)
                    os.remove(img_file)
                    return True
            else:
                logger.info(f"Otomatik Text Paylaşılıyor: {title}")
                subreddit.submit(title=title, selftext=f"Kaynak: {tweet['url']}", flair_id=flair_id)
                return True
                
        except Exception as e:
            logger.error(f"Reddit otomatik paylaşım hatası: {e}")
            return False

    def post_manual_media(self, title: str, body: str, file_paths: List[str]):
        """Manuel Medya Paylaşımı (Admin Panel)"""
        try:
            subreddit = self.reddit.subreddit(self.subreddit_name)
            flair_id = os.getenv("FLAIR_HABERLER")
            
            if not file_paths:
                # Sadece Metin
                logger.info(f"Manuel Metin Paylaşımı: {title}")
                subreddit.submit(title=title, selftext=body, flair_id=flair_id)
                return True

            file_count = len(file_paths)
            first_file = file_paths[0]
            mime_type, _ = mimetypes.guess_type(first_file)
            
            # VİDEO KONTROLÜ
            if mime_type and mime_type.startswith('video'):
                logger.info(f"Manuel Video Paylaşımı: {title}")
                # PRAW video yükleme
                subreddit.submit_video(
                    title=title, 
                    video_path=first_file, 
                    thumbnail_path=None, 
                    flair_id=flair_id
                )
                return True

            # GALERİ KONTROLÜ (>1 Resim)
            if file_count > 1:
                logger.info(f"Manuel Galeri Paylaşımı ({file_count} resim): {title}")
                images = [{"image_path": p} for p in file_paths]
                subreddit.submit_gallery(title=title, images=images, flair_id=flair_id)
                return True

            # TEK RESİM KONTROLÜ
            if file_count == 1:
                logger.info(f"Manuel Resim Paylaşımı: {title}")
                subreddit.submit_image(title=title, image_path=first_file, flair_id=flair_id)
                return True
                
        except Exception as e:
            logger.error(f"Manuel gönderim hatası (PRAW): {e}")
            raise e # Hatayı yukarı fırlat ki panelde görünebilsin

# --- BOT İŞLEMLERİ ---

db = DatabaseManager()
twitter_svc = TwitterService()
reddit_svc = RedditService()
bot_running = True

def job_check_tweets():
    logger.info("Periyodik tweet kontrolü başladı...")
    tweets = twitter_svc.get_recent_tweets(limit=3)
    count = 0
    for tweet in tweets:
        if not db.is_posted(tweet['id']):
            logger.info(f"Yeni tweet bulundu: {tweet['id']}")
            if reddit_svc.post_tweet(tweet):
                db.mark_as_posted(tweet['id'])
                count += 1
                time.sleep(5)
    if count == 0: logger.info("Yeni tweet yok.")
    else: logger.info(f"{count} tweet paylaşıldı.")

def run_scheduler():
    schedule.every(5).minutes.do(job_check_tweets)
    logger.info("Zamanlayıcı aktif.")
    while bot_running:
        schedule.run_pending()
        time.sleep(1)

# --- WEB & ADMIN PANELİ (FASTAPI) ---

app = FastAPI(title="BF6 Bot Admin")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr" data-bs-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Bot Kontrol Merkezi</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.js"></script>
    <style>
        .log-window { height: 400px; overflow-y: scroll; font-family: 'Consolas', monospace; font-size: 0.85rem; background: #1e1e1e; border: 1px solid #333; }
        .log-INFO { color: #4caf50; }
        .log-WARNING { color: #ff9800; }
        .log-ERROR { color: #f44336; }
    </style>
</head>
<body>
<div id="app" class="container py-4">
    <div class="row align-items-center mb-4">
        <div class="col">
            <h2 class="mb-0"><i class="fas fa-robot text-primary"></i> Bot Kontrol Paneli</h2>
        </div>
        <div class="col-auto">
            <span class="badge" :class="status.running ? 'bg-success' : 'bg-danger'">
                {{ status.running ? 'ÇALIŞIYOR' : 'DURDU' }}
            </span>
        </div>
    </div>

    <ul class="nav nav-tabs mb-3" role="tablist">
        <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#logs">📋 Loglar</a></li>
        <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#manual">🎮 Manuel Gönderi (Medya)</a></li>
    </ul>

    <div class="tab-content">
        <!-- LOGLAR -->
        <div class="tab-pane fade show active" id="logs">
            <div class="log-window p-2 rounded">
                <div v-for="log in logs" :class="getLogClass(log)">{{ log }}</div>
            </div>
            <div class="mt-2 text-end">
                <button @click="fetchLogs" class="btn btn-sm btn-secondary">Yenile</button>
            </div>
        </div>

        <!-- MANUEL GÖNDERİ -->
        <div class="tab-pane fade" id="manual">
            <div class="card bg-dark border-secondary">
                <div class="card-body">
                    <form @submit.prevent="submitForm">
                        <div class="mb-3">
                            <label>Başlık</label>
                            <input v-model="form.title" class="form-control bg-dark text-light" required>
                        </div>
                        <div class="mb-3">
                            <label>Metin (Opsiyonel)</label>
                            <textarea v-model="form.body" class="form-control bg-dark text-light" rows="3"></textarea>
                        </div>
                        <div class="mb-3">
                            <label>Medya (Resim/Video/Galeri)</label>
                            <input type="file" ref="fileInput" class="form-control bg-dark text-light" multiple>
                            <div class="form-text text-muted">Çoklu seçim yaparsanız galeri olarak yüklenir.</div>
                        </div>
                        <button type="submit" class="btn btn-primary" :disabled="loading">
                            <span v-if="loading" class="spinner-border spinner-border-sm"></span>
                            Paylaş
                        </button>
                    </form>
                </div>
            </div>
            
            <hr>
            <div class="d-flex gap-2">
                 <button @click="triggerCheck" class="btn btn-warning w-100">Tweet Kontrolü Tetikle</button>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
    const { createApp } = Vue;
    createApp({
        data() {
            return {
                status: { running: true },
                logs: [],
                form: { title: '', body: '' },
                loading: false,
                timer: null
            }
        },
        methods: {
            async fetchData() {
                try {
                    const s = await fetch('/api/status').then(r => r.json());
                    this.status = s;
                    const l = await fetch('/api/logs').then(r => r.json());
                    this.logs = l.logs.reverse();
                } catch(e) {}
            },
            async fetchLogs() { await this.fetchData(); },
            getLogClass(log) {
                if(log.includes('WARNING')) return 'log-WARNING';
                if(log.includes('ERROR')) return 'log-ERROR';
                return 'log-INFO';
            },
            async submitForm() {
                this.loading = true;
                const formData = new FormData();
                formData.append('title', this.form.title);
                formData.append('body', this.form.body);
                
                const files = this.$refs.fileInput.files;
                for(let i=0; i<files.length; i++) {
                    formData.append('files', files[i]);
                }
                
                try {
                    const res = await fetch('/api/manual-post', { method: 'POST', body: formData });
                    const d = await res.json();
                    if(d.success) {
                        alert('Başarıyla paylaşıldı!');
                        this.form = {title: '', body: ''};
                        this.$refs.fileInput.value = null;
                        this.fetchLogs();
                    } else {
                        alert('Hata: ' + d.error);
                    }
                } catch(e) { alert('Gönderim hatası'); }
                this.loading = false;
            },
            async triggerCheck() {
                await fetch('/api/trigger', {method: 'POST'});
                alert('Tetiklendi, logları kontrol edin.');
                this.fetchLogs();
            }
        },
        mounted() {
            this.fetchData();
            this.timer = setInterval(this.fetchData, 5000);
        },
        unmounted() { clearInterval(this.timer); }
    }).mount('#app');
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_TEMPLATE

@app.get("/api/status")
async def api_status():
    return {"running": bot_running}

@app.get("/api/logs")
async def api_logs():
    return {"logs": list(log_capture_string)}

@app.post("/api/trigger")
async def api_trigger(bg: BackgroundTasks):
    bg.add_task(job_check_tweets)
    return {"ok": True}

@app.post("/api/manual-post")
async def api_manual_post(
    title: str = Form(...),
    body: str = Form(""),
    files: List[UploadFile] = File(None)
):
    """
    Manuel gönderim: Resim, Video veya Galeri destekler.
    Dosyaları geçici olarak kaydeder, Reddit'e gönderir ve siler.
    """
    temp_files = []
    try:
        # 1. Dosyaları sunucuya kaydet
        if files:
            for file in files:
                safe_name = "".join(x for x in file.filename if x.isalnum() or x in "._-")
                temp_path = f"manual_{int(time.time())}_{safe_name}"
                with open(temp_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                temp_files.append(temp_path)
        
        # 2. Reddit'e gönder
        if reddit_svc.post_manual_media(title, body, temp_files):
            return {"success": True}
        else:
            return {"success": False, "error": "Reddit API işlemi reddetti (Loglara bakın)"}

    except Exception as e:
        logger.error(f"Manuel API Hatası: {e}")
        return {"success": False, "error": str(e)}
    
    finally:
        # 3. Temizlik (Her durumda çalışır)
        for f in temp_files:
            try:
                if os.path.exists(f): os.remove(f)
            except Exception as e:
                logger.warning(f"Geçici dosya silinemedi: {f}")

# --- BAŞLANGIÇ ---

start_time = time.time()

if __name__ == "__main__":
    # Başlangıç kontrolleri
    db._init_db()
    
    # Scheduler
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    
    # Web Server
    port = int(os.getenv("PORT", 10000))
    logger.info(f"Admin paneli başlatılıyor: http://0.0.0.0:{port}")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
