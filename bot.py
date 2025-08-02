from dotenv import load_dotenv
import os
import time
import requests
import praw
import re
import subprocess
import json
import sys
import asyncio
from pathlib import Path

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
REDDIT_USER_AGENT = "script:twitter-post-bot:v1.0 (by /u/BF6_HBR)"

RAPIDAPI_TWITTER_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_TRANSLATE_KEY = os.getenv("RAPIDAPI_KEY")

TWITTER_SCREENNAME = "TheBFWire"
TWITTER_REST_ID = "1939708158051500032"

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
    text = re.sub(r'^RT @TheBFWire:\s*', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r't\.co/\S+', '', text)
    text = re.sub(r'#\w+', '', text)
    text = text.replace('|', '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_latest_tweet():
    url = "https://twitter-api45.p.rapidapi.com/timeline.php"
    headers = {
        "x-rapidapi-key": RAPIDAPI_TWITTER_KEY,
        "x-rapidapi-host": "twitter-api45.p.rapidapi.com"
    }
    params = {
        "screenname": TWITTER_SCREENNAME,
        "rest_id": TWITTER_REST_ID
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    timeline = data.get("timeline")
    if not timeline:
        return None
    return timeline[0]

def get_media_urls_from_user_tweets(tweet_id):
    url = "https://twitter241.p.rapidapi.com/user-tweets"
    headers = {
        "x-rapidapi-key": RAPIDAPI_TWITTER_KEY,
        "x-rapidapi-host": "twitter241.p.rapidapi.com"
    }
    params = {
        "user": TWITTER_REST_ID,
        "count": "20"
    }
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    data = r.json()

    media_urls = []

    try:
        result = data.get("result", {})
        timeline = result.get("timeline", {})
        instructions = timeline.get("instructions", [])

        if len(instructions) < 2:
            print("[HATA] instructions listesi yetersiz (en az 2 eleman gerekli).")
            return []

        entries = instructions[1].get("entries", [])
        if not entries:
            print("[HATA] entries bulunamadı.")
            return []

        for entry in entries:
            entry_id = entry.get("entryId", "")
            if not entry_id.endswith(tweet_id):
                continue

            print(f"[+] Tweet bulundu: {entry_id}")

            content = entry.get("content", {})
            itemContent = content.get("itemContent", {})
            tweet_results = itemContent.get("tweet_results", {})
            result_tweet = tweet_results.get("result", {})
            legacy = result_tweet.get("legacy", {})
            extended_entities = legacy.get("extended_entities", {})
            media_list = extended_entities.get("media", [])

            print(f"[+] {len(media_list)} medya bulundu")

            for media in media_list:
                media_type = media.get("type")

                if media_type == "photo":
                    media_url = media.get("media_url_https")
                    if media_url:
                        print(f"[+] Fotoğraf URL'si: {media_url}")
                        media_urls.append(media_url)

                elif media_type in ["video", "animated_gif"]:
                    video_info = media.get("video_info", {})
                    variants = video_info.get("variants", [])
                    best_variant = None
                    max_bitrate = -1
                    for variant in variants:
                        url = variant.get("url")
                        bitrate = variant.get("bitrate", 0)
                        if url and bitrate > max_bitrate:
                            best_variant = url
                            max_bitrate = bitrate
                    if best_variant:
                        print(f"[+] Video URL'si: {best_variant}")
                        media_urls.append(best_variant)

    except Exception as e:
        print(f"[HATA] Media parse edilirken hata: {e}")
        import traceback
        traceback.print_exc()
        return []

    print(f"[+] Toplam {len(media_urls)} medya URL'si bulundu")
    return media_urls

def translate_text(text):
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
    resp = requests.post(translate_url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    try:
        translated = data['translated_json']['product']['productDesc']
        return translated
    except Exception as e:
        print("Çeviri alınamadı:", e)
        print("Raw response:", data)
        return text

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
        
        # DAHA UYUMLU FFmpeg komutu - Reddit'in kabul edeceği format
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-c:v", "libx264",
            "-profile:v", "main",  # baseline yerine main (daha iyi uyumluluk)
            "-level", "4.0",  # Daha yüksek level
            "-preset", "medium",  # slow yerine medium (daha hızlı)
            "-crf", "23",  # 20 yerine 23 (daha küçük dosya)
            "-maxrate", "5M",  # 8M yerine 5M (daha güvenli)
            "-bufsize", "10M",
            "-g", "60",  # 30 yerine 60 (daha verimli)
            "-keyint_min", "60",
            "-sc_threshold", "0",
            "-c:a", "aac",
            "-b:a", "128k",  # 96k yerine 128k (standart)
            "-ar", "48000",  # 44100 yerine 48000 (standart)
            "-ac", "2",
            "-movflags", "+faststart",  # rtphint kaldırıldı
            "-pix_fmt", "yuv420p",
            "-vf", "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2,fps=30",  # Daha güvenli scaling
            "-r", "30",
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts",  # igndts kaldırıldı
            "-map_metadata", "-1",
            "-threads", "4",  # CPU kullanımını sınırla
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
                redditwarp_client.p.submission.create.video(
                    sr=subreddit_name,
                    title=title,
                    link=video_lease.location,
                    thumbnail=thumb_lease.location
                )
            else:
                # Sadece video ile post (thumbnail olmadan)
                # RedditWarp dokümantasyonuna göre thumbnail gerekli, bu durumda hata verebilir
                redditwarp_client.p.submission.create.video(
                    sr=subreddit_name,
                    title=title,
                    link=video_lease.location,
                    thumbnail=video_lease.location  # Thumbnail yerine video location kullan
                )
            
            # If we reach here without exception, the submission was successful
            print("[+] RedditWarp video submission başarılı!")
            print("[+] Video submission başarılı")
            print("[+] URL: https://reddit.com/r/{}/comments/{}".format(subreddit_name, "id"))
                
            # Video processing bekle
            print("[+] Video processing için 30 saniye bekleniyor...")
            time.sleep(30)
            
            return True
                
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

def upload_video_via_reddit_api(title, media_path, subreddit_name):
    """Video yükleme - önce RedditWarp, sonra PRAW fallback"""
    
    # Önce RedditWarp dene
    if redditwarp_client:
        print("[+] RedditWarp yöntemi deneniyor...")
        if upload_video_via_redditwarp(title, media_path, subreddit_name):
            return True
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
            return True
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

def submit_post(title, media_files):
    """Geliştirilmiş post gönderme fonksiyonu"""
    subreddit = reddit.subreddit(SUBREDDIT)
    
    if not media_files:
        # Medya yoksa sadece text post
        try:
            print("[+] Medya yok, text post gönderiliyor.")
            submission = subreddit.submit(title=title, selftext="")
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
            submission = subreddit.submit_image(title=title, image_path=media_path)
            print(f"[+] Resim başarıyla gönderildi: {submission.url}")
            return True
            
        elif ext in [".mp4", ".mov", ".webm"]:
            # Video yükleme
            print(f"[+] Video gönderiliyor: {media_path}")
            
            # Önce dosya boyutunu kontrol et (Reddit için güvenli limit)
            max_video_size = 512 * 1024 * 1024  # 512MB
            if file_size > max_video_size:
                print(f"[HATA] Video çok büyük ({file_size} bytes). Limit: {max_video_size} bytes")
                # Büyük video için text post gönder
                submission = subreddit.submit(title=title + " [Video çok büyük - Twitter linkini kontrol edin]", selftext="")
                print(f"[+] Text post gönderildi: {submission.url}")
                return True
            
            # Video upload denemesi
            success = upload_video_via_reddit_api(title, media_path, SUBREDDIT)
            
            if success:
                print("[+] Video başarıyla yüklendi!")
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
                    submission = subreddit.submit(title=title + " [Video yüklenemedi - Twitter linkini kontrol edin]", selftext="")
                    print(f"[+] Alternatif text post gönderildi: {submission.url}")
                    return True
                
        else:
            print(f"[!] Desteklenmeyen dosya türü: {ext}")
            submission = subreddit.submit(title=title, selftext="")
            print(f"[+] Text post gönderildi: {submission.url}")
            return True
            
    except Exception as e:
        print(f"[HATA] Post gönderimi başarısız: {e}")
        
        # Hata durumunda bile text post göndermeyi dene
        try:
            print("[!] Hata sonrası text post deneniyor...")
            submission = subreddit.submit(title=title + " [Medya yüklenemedi]", selftext="")
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

def main_loop():
    posted_tweet_ids = set()
    
    print("[+] Reddit Bot başlatılıyor...")
    print(f"[+] Subreddit: r/{SUBREDDIT}")
    print(f"[+] Twitter: @{TWITTER_SCREENNAME}")
    
    while True:
        try:
            print("\n" + "="*50)
            print(f"[+] Tweet kontrol ediliyor... ({time.strftime('%Y-%m-%d %H:%M:%S')})")
            
            tweet = get_latest_tweet()
            
            if not tweet:
                print("[!] Tweet bulunamadı.")
            else:
                tweet_id = tweet.get("tweet_id")
                if tweet_id in posted_tweet_ids:
                    print("[!] Yeni tweet yok.")
                else:
                    print(f"[+] Yeni tweet bulundu: {tweet_id}")
                    
                    # Tweet işleme
                    text = tweet.get("text", "")
                    print(f"[+] Orijinal Tweet: {text[:100]}{'...' if len(text) > 100 else ''}")
                    
                    cleaned_text = clean_tweet_text(text)
                    print(f"[+] Temizlenmiş Tweet: {cleaned_text[:100]}{'...' if len(cleaned_text) > 100 else ''}")
                    
                    translated = translate_text(cleaned_text)
                    print(f"[+] Çeviri: {translated[:100]}{'...' if len(translated) > 100 else ''}")
                    
                    # Medya işleme
                    print("[+] Medya URL'leri alınıyor...")
                    media_urls = get_media_urls_from_user_tweets(tweet_id)
                    media_files = []
                    
                    for i, media_url in enumerate(media_urls):
                        try:
                            ext = os.path.splitext(media_url)[1].split("?")[0]
                            if not ext:
                                ext = ".jpg"  # Default extension
                            filename = f"temp_media_{tweet_id}_{i}{ext}"
                            
                            print(f"[+] Medya indiriliyor ({i+1}/{len(media_urls)}): {media_url[:50]}...")
                            path = download_media(media_url, filename)
                            
                            if path:
                                if ext.lower() == ".mp4":
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
                                    # Resim dosyası
                                    media_files.append(path)
                                    print(f"[+] Medya hazır: {path}")
                            else:
                                print(f"[!] Medya indirilemedi: {media_url}")
                                
                        except Exception as media_e:
                            print(f"[HATA] Medya işleme hatası: {media_e}")
                    
                    print(f"[+] Toplam {len(media_files)} medya dosyası hazır")
                    
                    # Post gönderme
                    print("[+] Reddit'e post gönderiliyor...")
                    success = submit_post(translated, media_files)
                    
                    if success:
                        posted_tweet_ids.add(tweet_id)
                        print(f"[+] Tweet başarıyla işlendi: {tweet_id}")
                    else:
                        print(f"[HATA] Tweet işlenemedi: {tweet_id}")
                    
                    # Geçici dosyaları temizle
                    for fpath in media_files:
                        try:
                            if os.path.exists(fpath):
                                os.remove(fpath)
                                print(f"[+] Geçici dosya silindi: {fpath}")
                        except Exception as cleanup_e:
                            print(f"[UYARI] Dosya silinirken hata: {cleanup_e}")
                            
        except Exception as loop_e:
            print(f"[HATA] Ana döngü hatası: {loop_e}")
            import traceback
            traceback.print_exc()
        
        print(f"\n[+] Sonraki kontrol: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + 7200))}")
        print("⏳ 2 saat bekleniyor...")
        time.sleep(7200)  # 2 saat

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\n[!] Bot durduruldu (Ctrl+C)")
    except Exception as e:
        print(f"\n[HATA] Kritik hata: {e}")
        import traceback
        traceback.print_exc()
