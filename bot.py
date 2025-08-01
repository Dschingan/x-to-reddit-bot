from dotenv import load_dotenv
import os
import time
import requests
import praw
import re
import subprocess
import json

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

reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    username=REDDIT_USERNAME,
    password=REDDIT_PASSWORD,
    user_agent=REDDIT_USER_AGENT,
    ratelimit_seconds=300
)

def clean_tweet_text(text):
    if not text:
        return ""
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
        r = requests.get(media_url, stream=True)
        if r.status_code == 200:
            with open(filename, "wb") as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return filename
        else:
            print(f"[HATA] Medya indirilemedi: {media_url}")
            return None
    except Exception as e:
        print(f"[HATA] Medya indirirken: {e}")
        return None

def convert_video_to_reddit_format(input_path, output_path):
    try:
        # Reddit video gereksinimleri için optimize edilmiş ayarlar
        command = [
            "ffmpeg",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "medium",  # Daha iyi kalite için
            "-crf", "20",  # Daha düşük CRF değeri
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",  # Standart ses örnekleme oranı
            "-movflags", "+faststart",
            "-max_muxing_queue_size", "1024",  # Buffer boyutu artırma
            "-y",  # Dosya üzerine yazma
            output_path
        ]
        print(f"[+] Video dönüştürülüyor: {input_path} -> {output_path}")
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        
        # Dosyanın başarıyla oluşturulduğunu kontrol et
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"[+] Video başarıyla dönüştürüldü. Boyut: {os.path.getsize(output_path)} bytes")
            return output_path
        else:
            print("[HATA] Dönüştürülen video dosyası bulunamadı veya boş")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"[HATA] ffmpeg dönüştürmede hata: {e}")
        if e.stderr:
            print(f"[HATA] ffmpeg stderr: {e.stderr}")
        return None
    except Exception as e:
        print(f"[HATA] Video dönüştürme genel hatası: {e}")
        return None

def submit_post(title, media_files):
    subreddit = reddit.subreddit(SUBREDDIT)
    if media_files:
        media_path = media_files[0]
        
        # Dosya varlığını ve boyutunu kontrol et
        if not os.path.exists(media_path):
            print(f"[HATA] Medya dosyası bulunamadı: {media_path}")
            return False
            
        file_size = os.path.getsize(media_path)
        if file_size == 0:
            print(f"[HATA] Medya dosyası boş: {media_path}")
            return False
            
        # Reddit video boyut limiti (1GB)
        max_size = 1024 * 1024 * 1024  # 1GB
        if file_size > max_size:
            print(f"[HATA] Dosya çok büyük ({file_size} bytes). Reddit limiti: {max_size} bytes")
            return False
            
        print(f"[+] Medya dosyası hazır: {media_path} ({file_size} bytes)")
        
        ext = os.path.splitext(media_path)[1].lower()
        
        try:
            if ext in [".jpg", ".jpeg", ".png", ".gif"]:
                print(f"[+] Görsel gönderiliyor: {media_path}")
                submission = subreddit.submit_image(title=title, image_path=media_path)
                print(f"[+] Görsel başarıyla gönderildi: {submission.url}")
                return True
                
            elif ext in [".mp4", ".mov", ".webm"]:
                print(f"[+] Video gönderiliyor: {media_path}")
                
                # Video dosyasının geçerli olduğunu kontrol et
                try:
                    # ffprobe ile video bilgilerini al
                    probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", media_path]
                    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
                    video_info = json.loads(probe_result.stdout)
                    
                    # Video süresini kontrol et (Reddit max 15 dakika)
                    duration = float(video_info['format']['duration'])
                    if duration > 900:  # 15 dakika
                        print(f"[HATA] Video çok uzun ({duration:.1f}s). Reddit limiti: 900s")
                        return False
                        
                    print(f"[+] Video geçerli - Süre: {duration:.1f}s, Boyut: {file_size} bytes")
                    
                except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
                    print(f"[UYARI] Video doğrulama başarısız: {e}. Yine de yüklemeyi deniyorum...")
                
                # Reddit'e video yükle
                submission = subreddit.submit_video(title=title, video_path=media_path)
                print(f"[+] Video başarıyla gönderildi: {submission.url}")
                return True
                
            else:
                print("[!] Desteklenmeyen medya türü, sadece başlık gönderiliyor.")
                submission = subreddit.submit(title=title, selftext="")
                print(f"[+] Başlık gönderildi: {submission.url}")
                return True
                
        except Exception as e:
            print(f"[HATA] Reddit'e gönderim başarısız: {e}")
            
            # WebSocketException özel durumu
            if "WebSocketException" in str(e):
                print("[!] WebSocket hatası - Video dosyası sorunlu olabilir")
                print("[!] Post yine de oluşturulmuş olabilir, Reddit'i kontrol edin")
                
                # Temp dosyaları temizle
                try:
                    if os.path.exists(media_path) and "temp_media" in media_path:
                        os.remove(media_path)
                        print(f"[+] Geçici dosya temizlendi: {media_path}")
                except:
                    pass
                    
            return False
            
    else:
        try:
            print("[+] Medya yok, sadece başlık gönderiliyor.")
            submission = subreddit.submit(title=title, selftext="")
            print(f"[+] Başlık gönderildi: {submission.url}")
            return True
        except Exception as e:
            print(f"[HATA] Başlık gönderimi başarısız: {e}")
            return False

def main_loop():
    posted_tweet_ids = set()
    while True:
        print("[+] Tweet kontrol ediliyor...")
        try:
            tweet = get_latest_tweet()
        except Exception as e:
            print("[HATA] Tweet alınamadı:", e)
            tweet = None

        if not tweet:
            print("[HATA] Tweet bulunamadı.")
        else:
            tweet_id = tweet.get("tweet_id")
            if tweet_id in posted_tweet_ids:
                print("[!] Yeni tweet yok.")
            else:
                text = tweet.get("text", "")
                print(f"[+] Orijinal Tweet: {text}")
                cleaned_text = clean_tweet_text(text)
                print(f"[+] Temizlenmiş Tweet: {cleaned_text}")
                translated = translate_text(cleaned_text)
                print(f"[+] Çeviri: {translated}")
                media_urls = get_media_urls_from_user_tweets(tweet_id)
                media_files = []
                for i, media_url in enumerate(media_urls):
                    ext = os.path.splitext(media_url)[1].split("?")[0]
                    filename = f"temp_media_{i}{ext}"
                    path = download_media(media_url, filename)
                    if path and ext == ".mp4":
                        converted = f"converted_{filename}"
                        converted_path = convert_video_to_reddit_format(filename, converted)
                        if converted_path:
                            media_files.append(converted_path)
                        if os.path.exists(filename):
                            os.remove(filename)
                    elif path:
                        media_files.append(path)

                submit_post(translated, media_files)
                posted_tweet_ids.add(tweet_id)

                for fpath in media_files:
                    if os.path.exists(fpath):
                        os.remove(fpath)

        print("\u23f3 2 saat bekleniyor..")
        time.sleep(7200)

if __name__ == "__main__":
    main_loop()
