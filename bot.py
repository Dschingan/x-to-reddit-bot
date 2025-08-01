from dotenv import load_dotenv
import os
import time
import requests
import praw
import re

load_dotenv()

# Ayarlar
SUBREDDIT = "bf6_tr"

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT = "script:twitter-post-bot:v1.0 (by /u/BF6_HBR)"

RAPIDAPI_TWITTER_KEY = os.getenv("RAPIDAPI_KEY")  # Twitter API rapid key
RAPIDAPI_TRANSLATE_KEY = os.getenv("RAPIDAPI_KEY")  # Aynı key veya farklı olabilir

TWITTER_SCREENNAME = "TheBFWire"
TWITTER_REST_ID = "1939708158051500032"

# Reddit bağlantısı - API kurallarına uygun konfigürasyon
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    username=REDDIT_USERNAME,
    password=REDDIT_PASSWORD,
    user_agent=REDDIT_USER_AGENT,
    ratelimit_seconds=300  # 5 dakikaya kadar otomatik bekle
)

def clean_tweet_text(text):
    """
    Tweet metnini temizler: URL'leri, hashtagleri ve "|" sembolünü çıkarır
    """
    if not text:
        return ""
    
    # URL'leri temizle (http://, https://, www. ile başlayanlar ve t.co linkler)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r't\.co/\S+', '', text)
    
    # Hashtagleri temizle (#kelime formatında)
    text = re.sub(r'#\w+', '', text)
    
    # "|" sembolünü temizle
    text = text.replace('|', '')
    
    # Fazla boşlukları temizle ve başındaki/sonundaki boşlukları kaldır
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
        # Correct path: {},result,timeline,instructions,1:,entries:,0:,content:,itemContent:,tweet_results:,result:,legacy:,extended_entities:,media:,0:,media_url_https
        result = data.get("result", {})
        timeline = result.get("timeline", {})
        instructions = timeline.get("instructions", [])
        
        if len(instructions) < 2:
            print("[HATA] instructions listesi yetersiz (en az 2 eleman gerekli).")
            return []

        # instructions[1] kullan (index 1)
        entries = instructions[1].get("entries", [])
        if not entries:
            print("[HATA] entries bulunamadı.")
            return []

        for entry in entries:
            entry_id = entry.get("entryId", "")
            # Tweet id ile eşleşme kontrolü: entryId "tweet-<tweet_id>" formatında
            if not entry_id.endswith(tweet_id):
                continue

            print(f"[+] Tweet bulundu: {entry_id}")
            
            # Doğru path'i takip et
            content = entry.get("content", {})
            itemContent = content.get("itemContent", {})
            tweet_results = itemContent.get("tweet_results", {})
            result_tweet = tweet_results.get("result", {})
            legacy = result_tweet.get("legacy", {})
            extended_entities = legacy.get("extended_entities", {})
            media_list = extended_entities.get("media", [])

            print(f"[+] {len(media_list)} medya bulundu")
            
            for media in media_list:
                media_type = media.get("type", "")

                if media_type == "video":
                    # Video için video_info.variants'tan en yüksek kaliteyi al
                    video_info = media.get("video_info", {})
                    variants = video_info.get("variants", [])
                    
                    # En yüksek bitrate'li .mp4 dosyasını bul
                    best_video = None
                    highest_bitrate = 0
                    
                    for variant in variants:
                        content_type = variant.get("content_type", "")
                        if content_type == "video/mp4":
                            bitrate = variant.get("bitrate", 0)
                            if bitrate > highest_bitrate:
                                highest_bitrate = bitrate
                                best_video = variant
                    
                    if best_video:
                        video_url = best_video.get("url")
                        if video_url:
                            print(f"[+] Video URL'si (bitrate: {highest_bitrate}): {video_url}")
                            media_urls.append(video_url)
                    else:
                        print("[UYARI] Video için uygun variant bulunamadı")
                        
                elif media_type in ["photo", "animated_gif"]:
                    # Fotoğraf ve GIF için media_url_https kullan
                    media_url = media.get("media_url_https")
                    if media_url:
                        print(f"[+] {media_type.title()} URL'si: {media_url}")
                        media_urls.append(media_url)
                else:
                    print(f"[UYARI] Bilinmeyen medya türü: {media_type}")

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

def submit_post(title, media_files):
    subreddit = reddit.subreddit(SUBREDDIT)
    if media_files:
        media_path = media_files[0]
        ext = os.path.splitext(media_path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".gif"]:
            print(f"[+] Görsel gönderiliyor: {media_path}")
            subreddit.submit_image(title=title, image_path=media_path)
        elif ext in [".mp4", ".mov", ".webm"]:
            print(f"[+] Video gönderiliyor: {media_path}")
            subreddit.submit_video(title=title, video_path=media_path)
        else:
            print("[!] Desteklenmeyen medya türü, sadece başlık gönderiliyor.")
            subreddit.submit(title=title, selftext="")
    else:
        print("[+] Medya yok, sadece başlık gönderiliyor.")
        subreddit.submit(title=title, selftext="")

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
                
                # Tweet metnini temizle
                cleaned_text = clean_tweet_text(text)
                print(f"[+] Temizlenmiş Tweet: {cleaned_text}")
                
                # Temizlenmiş metni çevir
                translated = translate_text(cleaned_text)
                print(f"[+] Çeviri: {translated}")

                # Medyayı user-tweets API ile çek
                media_urls = get_media_urls_from_user_tweets(tweet_id)
                media_files = []
                for i, media_url in enumerate(media_urls):
                    ext = os.path.splitext(media_url)[1].split("?")[0]
                    filename = f"temp_media_{i}{ext}"
                    path = download_media(media_url, filename)
                    if path:
                        media_files.append(path)

                submit_post(translated, media_files)
                posted_tweet_ids.add(tweet_id)

                # Medya dosyalarını temizle
                for fpath in media_files:
                    if os.path.exists(fpath):
                        os.remove(fpath)

        print("⏳ 2 saat bekleniyor..")
        time.sleep(7200)  # 2 saat = 7200 saniye

if __name__ == "__main__":
    main_loop()
