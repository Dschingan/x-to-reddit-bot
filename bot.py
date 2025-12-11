import os
import sys
import time
import json
import logging
import sqlite3
import threading
import schedule
import requests
import hashlib
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from collections import deque

# 3rd Party Imports
import praw
import tweepy
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --- KONFİGÜRASYON VE LOGGING ---

# .env yükle
load_dotenv()

# Loglama Ayarları
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[
    logging.FileHandler("bot.log", encoding='utf-8'),
    logging.StreamHandler(sys.stdout)
])
logger = logging.getLogger("BF6Bot")

# Bellekte son logları tutmak için (Admin Paneli için)
log_capture_string = io = deque(maxlen=200)

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
        """Tabloları oluştur"""
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
        self.bearer_token = os.getenv("TWITTER_API_V2_BEARER_TOKEN")
        self.target_username = os.getenv("TWITTER_SCREENNAME", "BF6Media")
        self.client = None
        if self.bearer_token:
            self.client = tweepy.Client(bearer_token=self.bearer_token, wait_on_rate_limit=True)
        else:
            logger.warning("Twitter Bearer Token eksik! Twitter özellikleri çalışmayabilir.")

    def get_user_id(self, username: str):
        if not self.client: return None
        try:
            user = self.client.get_user(username=username)
            return user.data.id
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

            # Medya sözlüğü oluştur
            media_map = {m.media_key: m for m in response.includes['media']} if response.includes and 'media' in response.includes else {}

            tweets = []
            for t in response.data:
                # RT kontrolü (basit metin bazlı, API v2'de referenced_tweets daha iyi ama bu yeterli)
                if t.text.startswith("RT @"):
                    continue

                media_urls = []
                video_url = None
                
                if t.attachments and 'media_keys' in t.attachments:
                    for mk in t.attachments['media_keys']:
                        media = media_map.get(mk)
                        if not media: continue
                        
                        if media.type == 'photo':
                            media_urls.append(media.url)
                        elif media.type == 'video':
                            # En yüksek bitrate'li videoyu bul
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
            
            # Eskiden yeniye sırala
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
        self.subreddit_name = os.getenv("SUBREDDIT", "bf6_tr")
        self.validate_login()

    def validate_login(self):
        try:
            logger.info(f"Reddit girişi yapıldı: u/{self.reddit.user.me()}")
        except Exception as e:
            logger.error(f"Reddit giriş hatası: {e}")

    def download_media(self, url: str, filename: str) -> bool:
        try:
            r = requests.get(url, stream=True, timeout=20)
            if r.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                return True
        except Exception as e:
            logger.error(f"Medya indirme hatası ({url}): {e}")
        return False

    def post_tweet(self, tweet: Dict):
        subreddit = self.reddit.subreddit(self.subreddit_name)
        title = self.clean_title(tweet['text'])
        
        # Flair seçimi (Basit mantık, geliştirilebilir)
        flair_id = None # Gerekirse buraya mantık eklenebilir
        
        try:
            if tweet.get('video_url'):
                # Video Post
                video_filename = f"temp_vid_{tweet['id']}.mp4"
                if self.download_media(tweet['video_url'], video_filename):
                    logger.info(f"Video yükleniyor: {title}")
                    subreddit.submit_video(
                        title=title,
                        video_path=video_filename,
                        thumbnail_path=None,
                        flair_id=flair_id
                    )
                    os.remove(video_filename)
                    return True
            
            elif tweet.get('media_urls'):
                # Resim Post (Gallery değilse tek resim)
                # PRAW gallery desteği biraz karmaşık, basitlik için tek resim veya link
                img_url = tweet['media_urls'][0]
                img_filename = f"temp_img_{tweet['id']}.jpg"
                if self.download_media(img_url, img_filename):
                    logger.info(f"Resim yükleniyor: {title}")
                    subreddit.submit_image(
                        title=title,
                        image_path=img_filename,
                        flair_id=flair_id
                    )
                    os.remove(img_filename)
                    return True
            
            else:
                # Text Post (Link ile)
                logger.info(f"Text post gönderiliyor: {title}")
                body = f"Kaynak: {tweet['url']}"
                subreddit.submit(
                    title=title,
                    selftext=body,
                    flair_id=flair_id
                )
                return True

        except Exception as e:
            logger.error(f"Reddit gönderim hatası: {e}")
            return False

    def clean_title(self, text: str) -> str:
        # Linkleri temizle
        import re
        text = re.sub(r'http\S+', '', text)
        return text.strip() or "Battlefield Gelişmesi"

# --- BOT MANTIĞI ---

db = DatabaseManager()
twitter_svc = TwitterService()
reddit_svc = RedditService()
bot_running = True

def job_check_tweets():
    """Periyodik görev"""
    logger.info("Periyodik tweet kontrolü başladı...")
    tweets = twitter_svc.get_recent_tweets(limit=3)
    
    count = 0
    for tweet in tweets:
        if not db.is_posted(tweet['id']):
            logger.info(f"Yeni tweet bulundu: {tweet['id']}")
            success = reddit_svc.post_tweet(tweet)
            if success:
                db.mark_as_posted(tweet['id'])
                count += 1
                time.sleep(10) # Spam koruması
    
    if count == 0:
        logger.info("Yeni tweet yok.")
    else:
        logger.info(f"{count} yeni tweet paylaşıldı.")

def run_scheduler():
    """Zamanlayıcı döngüsü"""
    schedule.every(10).minutes.do(job_check_tweets)
    # schedule.every().day.at("09:00").do(some_daily_task)
    
    logger.info("Zamanlayıcı başlatıldı.")
    while bot_running:
        schedule.run_pending()
        time.sleep(1)

# --- WEB & ADMIN PANELİ (FASTAPI) ---

app = FastAPI(title="BF6 Bot Admin Panel")

# HTML Template (Tek dosya içinde tutmak için string olarak)
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
        .log-window { height: 400px; overflow-y: scroll; font-family: 'Consolas', monospace; font-size: 0.9rem; background: #1e1e1e; border: 1px solid #333; }
        .log-entry { padding: 2px 5px; border-bottom: 1px solid #2d2d2d; }
        .log-INFO { color: #4caf50; }
        .log-WARNING { color: #ff9800; }
        .log-ERROR { color: #f44336; }
        .status-badge { position: absolute; top: 10px; right: 10px; }
    </style>
</head>
<body>
<div id="app" class="container py-4">
    <div class="row mb-4 align-items-center">
        <div class="col">
            <h1><i class="fas fa-robot text-primary"></i> Bot Kontrol Paneli</h1>
            <p class="text-muted">v2.0 - Gelişmiş Yönetim Arayüzü</p>
        </div>
        <div class="col-auto">
            <span class="badge bg-success p-2" v-if="status.running">ÇALIŞIYOR</span>
            <span class="badge bg-danger p-2" v-else>DURDU</span>
        </div>
    </div>

    <!-- İstatistik Kartları -->
    <div class="row mb-4">
        <div class="col-md-3">
            <div class="card bg-dark border-secondary">
                <div class="card-body text-center">
                    <h5 class="card-title text-muted">Hedef Subreddit</h5>
                    <h3>{{ config.subreddit }}</h3>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-dark border-secondary">
                <div class="card-body text-center">
                    <h5 class="card-title text-muted">Twitter Hesabı</h5>
                    <h3>@{{ config.twitter_user }}</h3>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-dark border-secondary">
                <div class="card-body text-center">
                    <h5 class="card-title text-muted">Toplam Log</h5>
                    <h3>{{ logs.length }}</h3>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-dark border-secondary">
                <div class="card-body text-center">
                    <h5 class="card-title text-muted">Uptime</h5>
                    <h3>{{ uptime }}</h3>
                </div>
            </div>
        </div>
    </div>

    <!-- Sekmeler -->
    <ul class="nav nav-tabs mb-3" id="myTab" role="tablist">
        <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#logs">📋 Canlı Loglar</a></li>
        <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#manual">🎮 Manuel İşlemler</a></li>
        <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#config">⚙️ Ayarlar</a></li>
    </ul>

    <div class="tab-content">
        <!-- Log Sekmesi -->
        <div class="tab-pane fade show active" id="logs">
            <div class="card bg-dark border-secondary">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span>Sistem Kayıtları (Son 200)</span>
                    <button @click="fetchLogs" class="btn btn-sm btn-outline-light"><i class="fas fa-sync"></i> Yenile</button>
                </div>
                <div class="card-body p-0">
                    <div class="log-window p-2" ref="logWindow">
                        <div v-for="log in logs" class="log-entry" :class="getLogClass(log)">
                            {{ log }}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Manuel İşlemler Sekmesi -->
        <div class="tab-pane fade" id="manual">
            <div class="row">
                <div class="col-md-6">
                    <div class="card bg-dark border-secondary mb-3">
                        <div class="card-header">Manuel Gönderi Oluştur</div>
                        <div class="card-body">
                            <form @submit.prevent="submitManualPost">
                                <div class="mb-3">
                                    <label>Başlık</label>
                                    <input v-model="manualPost.title" class="form-control bg-dark text-light border-secondary" required>
                                </div>
                                <div class="mb-3">
                                    <label>Metin / Link</label>
                                    <textarea v-model="manualPost.body" class="form-control bg-dark text-light border-secondary" rows="3"></textarea>
                                </div>
                                <button type="submit" class="btn btn-primary w-100" :disabled="loading">
                                    <span v-if="loading" class="spinner-border spinner-border-sm"></span>
                                    Gönder
                                </button>
                            </form>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card bg-dark border-secondary mb-3">
                        <div class="card-header">Acil Durum Kontrolleri</div>
                        <div class="card-body d-grid gap-2">
                            <button @click="triggerCheck" class="btn btn-success">
                                <i class="fas fa-sync"></i> Tweet Kontrolünü Şimdi Tetikle
                            </button>
                            <button @click="toggleBot" class="btn" :class="status.running ? 'btn-danger' : 'btn-warning'">
                                <i class="fas fa-power-off"></i> Botu {{ status.running ? 'Durdur' : 'Başlat' }}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Ayarlar Sekmesi -->
        <div class="tab-pane fade" id="config">
            <div class="alert alert-info">
                Not: Hassas ayarlar (.env) güvenlik nedeniyle buradan değiştirilemez. Sadece çalışma zamanı ayarları değiştirilebilir.
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
                config: { subreddit: '', twitter_user: '' },
                logs: [],
                manualPost: { title: '', body: '' },
                loading: false,
                uptime: '0s',
                timer: null
            }
        },
        methods: {
            async fetchData() {
                const res = await fetch('/api/status');
                const data = await res.json();
                this.status = data.status;
                this.config = data.config;
                this.uptime = data.uptime;
            },
            async fetchLogs() {
                const res = await fetch('/api/logs');
                const data = await res.json();
                this.logs = data.logs.reverse();
            },
            getLogClass(log) {
                if (log.includes('INFO')) return 'log-INFO';
                if (log.includes('WARNING')) return 'log-WARNING';
                if (log.includes('ERROR')) return 'log-ERROR';
                return '';
            },
            async triggerCheck() {
                if(!confirm('Tweet kontrolü manuel olarak başlatılsın mı?')) return;
                await fetch('/api/trigger', { method: 'POST' });
                this.fetchLogs();
            },
            async toggleBot() {
                const action = this.status.running ? 'stop' : 'start';
                await fetch(`/api/${action}`, { method: 'POST' });
                this.fetchData();
            },
            async submitManualPost() {
                this.loading = true;
                try {
                    const res = await fetch('/api/manual-post', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(this.manualPost)
                    });
                    const result = await res.json();
                    if(result.success) {
                        alert('Gönderi başarıyla paylaşıldı!');
                        this.manualPost = { title: '', body: '' };
                        this.fetchLogs();
                    } else {
                        alert('Hata: ' + result.error);
                    }
                } catch(e) {
                    alert('Bir hata oluştu.');
                }
                this.loading = false;
            }
        },
        mounted() {
            this.fetchData();
            this.fetchLogs();
            this.timer = setInterval(() => {
                this.fetchData();
                this.fetchLogs();
            }, 5000); // 5 saniyede bir güncelle
        },
        unmounted() {
            clearInterval(this.timer);
        }
    }).mount('#app');
</script>
</body>
</html>
"""

# Admin Route'ları

# Basit bir güvenlik için environment variable'dan token kontrolü eklenebilir
# Şu an demo amaçlı açık bırakılmıştır.

@app.get("/", response_class=HTMLResponse)
async def admin_panel(request: Request):
    return HTML_TEMPLATE

@app.get("/api/status")
async def get_status():
    uptime_seconds = int(time.time() - start_time)
    return {
        "status": {"running": bot_running},
        "config": {
            "subreddit": os.getenv("SUBREDDIT"),
            "twitter_user": os.getenv("TWITTER_SCREENNAME")
        },
        "uptime": str(timedelta(seconds=uptime_seconds))
    }

@app.get("/api/logs")
async def get_logs():
    return {"logs": list(log_capture_string)}

@app.post("/api/trigger")
async def trigger_check(background_tasks: BackgroundTasks):
    background_tasks.add_task(job_check_tweets)
    return {"message": "Tetiklendi"}

@app.post("/api/stop")
async def stop_bot():
    global bot_running
    bot_running = False
    logger.warning("Bot durduruldu (Admin Panel).")
    return {"status": "stopped"}

@app.post("/api/start")
async def start_bot(background_tasks: BackgroundTasks):
    global bot_running
    if not bot_running:
        bot_running = True
        logger.info("Bot başlatıldı (Admin Panel).")
        # Thread'i yeniden başlatmak karmaşık olabilir, 
        # bu basit örnekte sadece flag'i açıyoruz ve scheduler döngüsü devam ediyor.
        # Gerçek bir prodüksiyon ortamında thread yönetimi daha sağlam olmalı.
        threading.Thread(target=run_scheduler, daemon=True).start()
    return {"status": "started"}

class ManualPostModel(BaseModel):
    title: str
    body: str

@app.post("/api/manual-post")
async def manual_post(post: ManualPostModel):
    try:
        reddit_svc.reddit.subreddit(reddit_svc.subreddit_name).submit(
            title=post.title,
            selftext=post.body
        )
        logger.info(f"Manuel gönderi paylaşıldı: {post.title}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Manuel gönderi hatası: {e}")
        return {"success": False, "error": str(e)}

# --- BAŞLANGIÇ ---

start_time = time.time()

if __name__ == "__main__":
    # Veritabanını kontrol et
    db._init_db()
    
    # Scheduler'ı arka planda başlat
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    
    # Web sunucusunu başlat
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Admin paneli başlatılıyor: http://0.0.0.0:{port}")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
