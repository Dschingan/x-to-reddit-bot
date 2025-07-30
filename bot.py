import os
import time
import json
import requests
import praw
from datetime import datetime
import subprocess
from pathlib import Path
import re
from dotenv import load_dotenv
import logging
from typing import Optional, Dict, Any, List
import random
import platform
from prawcore.exceptions import TooManyRequests, ServerError, RequestException

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# .env dosyasını yükle
load_dotenv()

class TwitterRedditBot:
    def __init__(self):
        # Environment variables
        self.twitter_bearer_token = os.getenv('TWITTER_BEARER_TOKEN')
        self.twitter_username = os.getenv('TWITTER_USERNAME')
        self.twitter_user_id = os.getenv('TWITTER_USER_ID')
        
        # Reddit API bilgileri
        self.reddit_client_id = os.getenv('REDDIT_CLIENT_ID')
        self.reddit_client_secret = os.getenv('REDDIT_CLIENT_SECRET')
        self.reddit_username = os.getenv('REDDIT_USERNAME')
        self.reddit_password = os.getenv('REDDIT_PASSWORD')
        
        # Gelişmiş User Agent - Reddit'in banlamasını önlemek için
        custom_user_agent = os.getenv('USER_AGENT')
        if not custom_user_agent or custom_user_agent.strip() == '':
            # Eğer .env'de user agent yoksa, otomatik oluştur
            python_version = platform.python_version()
            system_info = platform.system()
            custom_user_agent = f"TwitterRedditBot/1.0 (by /u/{self.reddit_username}; Python/{python_version}; {system_info})"
        
        self.user_agent = custom_user_agent
        self.subreddit_name = os.getenv('SUBREDDIT_NAME')
        
        # Anti-ban ayarları
        self.min_delay = 300  # Minimum 5 dakika bekleme
        self.max_delay = 900  # Maximum 15 dakika bekleme
        self.rate_limit_delay = 3600  # Rate limit durumunda 1 saat bekle
        self.max_retries = 3  # Maksimum yeniden deneme sayısı
        self.last_post_time = 0  # Son post zamanı
        
        # Flair ID'leri
        self.flair_haberler = os.getenv('FLAIR_HABERLER')
        self.flair_tartisma = os.getenv('FLAIR_TARTISMA')
        self.flair_sizinti = os.getenv('FLAIR_SIZINTI')
        
        # RapidAPI Çeviri API bilgileri
        self.translation_api_key = os.getenv('TRANSLATION_API_KEY')
        self.translation_api_url = os.getenv('TRANSLATION_API_URL')
        self.translation_api_host = os.getenv('TRANSLATION_API_HOST')
        
        # Dosya yolları
        self.last_tweet_file = 'last_tweet_id.txt'
        self.temp_dir = Path('temp_media')
        self.temp_dir.mkdir(exist_ok=True)
        
        # Twitter API başlıkları
        self.twitter_headers = {
            'Authorization': f'Bearer {self.twitter_bearer_token}',
            'Content-Type': 'application/json'
        }
        
        # Reddit istemcisini başlat
        self._init_reddit()
        
        # Çeviri sistemini test et
        self._test_translation()
        
        logger.info("Bot başlatıldı")
    
    def _init_reddit(self):
        """Reddit API istemcisini başlat"""
        try:
            self.reddit = praw.Reddit(
                client_id=self.reddit_client_id,
                client_secret=self.reddit_client_secret,
                username=self.reddit_username,
                password=self.reddit_password,
                user_agent=self.user_agent
            )
            logger.info("Reddit API bağlantısı başarılı")
        except Exception as e:
            logger.error(f"Reddit API bağlantı hatası: {e}")
            raise
    
    def _test_translation(self):
        """Çeviri sistemini test et"""
        test_text = "Hello world"
        result = self.translate_to_turkish(test_text)
        logger.info(f"Çeviri testi (RapidAPI): '{test_text}' -> '{result}'")
        
        if result == test_text:
            logger.warning("NOT: RapidAPI çevirisinde sorun olabilir, orijinal metin döndürüldü.")
    
    def _wait_random_delay(self):
        """Reddit banlanmasını önlemek için rastgele bekleme"""
        delay = random.randint(self.min_delay, self.max_delay)
        logger.info(f"Anti-ban rastgele bekleme: {delay} saniye ({delay//60} dakika {delay%60} saniye)")
        time.sleep(delay)
    
    def _check_rate_limit(self):
        """Son post zamanından itibaren minimum bekleme süresini kontrol et"""
        current_time = time.time()
        time_since_last_post = current_time - self.last_post_time
        
        if time_since_last_post < self.min_delay:
            wait_time = self.min_delay - time_since_last_post
            logger.info(f"Rate limit koruması: {wait_time:.0f} saniye daha bekleniyor")
            time.sleep(wait_time)
    
    def _handle_reddit_errors(self, func, *args, **kwargs):
        """Reddit API hatalarını yönet ve yeniden dene"""
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except TooManyRequests as e:
                logger.warning(f"Reddit rate limit! {self.rate_limit_delay} saniye bekleniyor... (Deneme {attempt + 1}/{self.max_retries})")
                time.sleep(self.rate_limit_delay)
            except (ServerError, RequestException) as e:
                wait_time = (2 ** attempt) * 60  # Exponential backoff
                logger.warning(f"Reddit sunucu hatası: {e}. {wait_time} saniye bekleniyor... (Deneme {attempt + 1}/{self.max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"Reddit API hatası (Deneme {attempt + 1}/{self.max_retries}): {e}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(60 * (attempt + 1))
        
        return None
    
    def read_last_tweet_id(self) -> Optional[str]:
        """Son işlenen tweet ID'sini oku"""
        try:
            if os.path.exists(self.last_tweet_file):
                with open(self.last_tweet_file, 'r', encoding='utf-8') as f:
                    tweet_id = f.read().strip()
                    logger.info(f"Son tweet ID okundu: {tweet_id}")
                    return tweet_id
        except Exception as e:
            logger.error(f"Tweet ID okuma hatası: {e}")
        return None
    
    def save_last_tweet_id(self, tweet_id: str):
        """Son işlenen tweet ID'sini kaydet"""
        try:
            with open(self.last_tweet_file, 'w', encoding='utf-8') as f:
                f.write(tweet_id)
            logger.info(f"Tweet ID kaydedildi: {tweet_id}")
        except Exception as e:
            logger.error(f"Tweet ID kaydetme hatası: {e}")
    
    def handle_rate_limit(self, response):
        """Twitter API rate limit yönetimi"""
        if response.status_code == 429:
            reset_time = int(response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = reset_time - current_time + 1
            if wait_time > 0:
                logger.warning(f"Rate limit aşıldı. {wait_time} saniye bekleniyor...")
                for i in range(wait_time, 0, -1):
                    print(f"\rKalan süre: {i} saniye", end="", flush=True)
                    time.sleep(1)
                print("\nBekleme tamamlandı.")
            return True
        return False

    def get_latest_tweets(self) -> List[Dict[Any, Any]]:
        """
        Twitter'dan son 5 tweeti alır.
        Alıntı tweetler de expansions ile ve includes ile beraber gelir.
        """
        url = f"https://api.twitter.com/2/users/{self.twitter_user_id}/tweets"
        params = {
            'max_results': 5,
            'tweet.fields': 'created_at,attachments,in_reply_to_user_id,referenced_tweets',
            'media.fields': 'type,url,variants,preview_image_url,media_key',
            'expansions': 'attachments.media_keys,referenced_tweets.id'  # Alıntı tweet ID'leri için
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=self.twitter_headers, params=params, timeout=30)

                if self.handle_rate_limit(response):
                    continue

                if response.status_code == 200:
                    data = response.json()
                    tweets = data.get('data', [])
                    includes = data.get('includes', {})
                    media_data = {media['media_key']: media for media in includes.get('media', [])}
                    included_tweets = {tweet['id']: tweet for tweet in includes.get('tweets', [])}

                    # Ana tweetlerin medya ataması
                    for tweet in tweets:
                        if 'attachments' in tweet and 'media_keys' in tweet['attachments']:
                            tweet['media'] = [media_data.get(k) for k in tweet['attachments']['media_keys']]

                    # Alıntı tweetlerin (quoted tweets) medya ataması
                    for tweet in tweets:
                        # Alıntı tweet varsa alıntılanan tweet nesnesini ata
                        referenced = tweet.get('referenced_tweets', [])
                        for ref in referenced:
                            if ref.get('type') == 'quoted':
                                quoted_id = ref.get('id')
                                quoted_tweet = included_tweets.get(quoted_id)
                                if quoted_tweet:
                                    # Alıntı tweetin medyasını ata
                                    if 'attachments' in quoted_tweet and 'media_keys' in quoted_tweet['attachments']:
                                        quoted_tweet['media'] = [media_data.get(k) for k in quoted_tweet['attachments']['media_keys']]
                                    tweet['quoted_tweet'] = quoted_tweet
                                break  # Birden çok quoted varsa sadece birinciyi alıyoruz

                    logger.info(f"{len(tweets)} tweet ve alıntıları alındı")
                    return tweets
                else:
                    logger.error(f"Twitter API hatası: {response.status_code} - {response.text}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Bağlantı hatası (deneme {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))

        return []

    def clean_tweet_text(self, text: str) -> str:
        """Tweet metnini temizle"""
        text = re.sub(r'http[s]?://\S+', '', text)
        text = re.sub(r'#\w+', '', text)
        text = re.sub(r'\|', '', text)
        text = ' '.join(text.split())
        return text.strip()
    
    def translate_to_turkish(self, text: str) -> str:
        """Metni Türkçeye çevir (RapidAPI Translation API kullanılır)"""
        headers = {
            "x-rapidapi-key": self.translation_api_key,
            "x-rapidapi-host": self.translation_api_host,
            "Content-Type": "application/json"
        }
        payload = {
            "origin_language": "en",
            "target_language": "tr",
            "words_not_to_translate": "",
            "input_text": text
        }
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(self.translation_api_url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()
                logger.info(f"RapidAPI raw response: {json.dumps(data, ensure_ascii=False)}")
                translated_text = data.get('translation', text)
                logger.info(f"Çeviri sonucu: '{translated_text}'")
                return translated_text
            except requests.exceptions.RequestException as e:
                logger.error(f"RapidAPI hatası (deneme {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        logger.warning("RapidAPI çevirisi başarısız oldu, orijinal metin kullanılacak.")
        return text
    
    def download_media(self, media_url: str, filename: str) -> Optional[str]:
        """Medya dosyasını indir"""
        try:
            response = requests.get(media_url, timeout=30)
            if response.status_code == 200:
                filepath = self.temp_dir / filename
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                logger.info(f"Medya indirildi: {filename}")
                return str(filepath)
            else:
                logger.error(f"Medya indirme başarısız ({response.status_code}): {media_url}")
        except Exception as e:
            logger.error(f"Medya indirme hatası: {e}")
        return None

    def convert_video_for_reddit(self, input_path: str) -> Optional[str]:
        output_path = str(input_path).replace('.mp4', '_reddit.mp4')
        try:
            cmd = [
                'ffmpeg', '-i', input_path,
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-preset', 'medium',
                '-crf', '23',
                '-maxrate', '25M',
                '-bufsize', '50M',
                '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                '-movflags', '+faststart',
                '-y',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info(f"Video dönüştürüldü: {output_path}")
                return output_path
            else:
                logger.error(f"Video dönüştürme hatası: {result.stderr}")
        except Exception as e:
            logger.error(f"Video dönüştürme hatası: {e}")
        return None

    def get_best_video_variant(self, media_info: Dict) -> Optional[str]:
        if media_info.get('type') not in ['video', 'animated_gif']:
            return None
        variants = media_info.get('variants', [])
        if not variants:
            return None
        best_variant = max(
            [v for v in variants if v.get('content_type') == 'video/mp4'],
            key=lambda x: x.get('bit_rate', 0),
            default=None
        )
        return best_variant.get('url') if best_variant else None

    def process_media(self, media_list: List[Dict]) -> List[str]:
        processed_media = []
        for i, media in enumerate(media_list):
            if not media:
                continue
            media_type = media.get('type')
            if media_type == 'photo':
                media_url = media.get('url')
                if media_url:
                    filename = f"photo_{i}.jpg"
                    filepath = self.download_media(media_url, filename)
                    if filepath:
                        processed_media.append(filepath)
            elif media_type in ['video', 'animated_gif']:
                video_url = self.get_best_video_variant(media)
                if video_url:
                    filename = f"video_{i}.mp4"
                    filepath = self.download_media(video_url, filename)
                    if filepath:
                        converted_path = self.convert_video_for_reddit(filepath)
                        if converted_path:
                            processed_media.append(converted_path)
                        else:
                            processed_media.append(filepath)
        return processed_media

    def determine_flair(self, tweet_text: str) -> Optional[str]:
        text_lower = tweet_text.lower()
        if any(word in text_lower for word in ['breaking', 'urgent', 'alert', 'news', 'report']):
            return self.flair_haberler
        elif any(word in text_lower for word in ['leak', 'rumor', 'source', 'insider']):
            return self.flair_sizinti
        else:
            return self.flair_tartisma or self.flair_haberler

    def is_reply_or_retweet(self, tweet: Dict) -> bool:
        if tweet.get('in_reply_to_user_id'):
            return True
        referenced = tweet.get('referenced_tweets', [])
        for ref in referenced:
            if ref.get('type') in ['replied_to', 'retweeted']:
                return True
        return False

    def post_to_reddit(self, title: str, media_paths: List[str], tweet_text: str) -> bool:
        # Rate limit kontrolü
        self._check_rate_limit()
        
        def _submit_to_reddit():
            subreddit = self.reddit.subreddit(self.subreddit_name)
            
            # Flair belirleme
            flair_id = self.determine_flair(tweet_text)
            
            if media_paths:
                # Medya türlerini ayır
                image_paths = []
                video_paths = []
                
                for media_path in media_paths:
                    if Path(media_path).exists():
                        ext = Path(media_path).suffix.lower()
                        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                            image_paths.append(media_path)
                        elif ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                            video_paths.append(media_path)
                
                # Video varsa öncelikle video yükle (Reddit tek video destekler)
                if video_paths:
                    video_path = video_paths[0]  # İlk videoyu al
                    logger.info(f"Video yükleniyor: {video_path}")
                    
                    try:
                        submission = subreddit.submit_video(
                            title=title,
                            video_path=video_path,
                            flair_id=flair_id
                        )
                        
                        logger.info(f"Reddit'te video ile paylaşıldı: {submission.url}")
                        return True
                        
                    except Exception as video_error:
                        logger.error(f"Video yükleme hatası: {video_error}")
                        # Video yüklenemezse metin olarak paylaş
                        logger.info("Video yüklenemedi, metin olarak paylaşılıyor")
                
                # Sadece resim varsa gallery olarak yükle
                elif image_paths:
                    media_dict_list = [{'image_path': img_path} for img_path in image_paths]
                    
                    if len(image_paths) == 1:
                        # Tek resim varsa submit_image kullan
                        submission = subreddit.submit_image(
                            title=title,
                            image_path=image_paths[0],
                            flair_id=flair_id
                        )
                    else:
                        # Çoklu resim varsa gallery kullan
                        submission = subreddit.submit_gallery(
                            title=title,
                            images=media_dict_list,
                            flair_id=flair_id
                        )
                    

                    
                    logger.info(f"Reddit'te resim ile paylaşıldı: {submission.url}")
                    return True
                
                else:
                    logger.warning("Desteklenen medya dosyası bulunamadı, sadece metin paylaşılıyor")
            
            # Medya yoksa veya medya yüklenemezse sadece metin paylaş
            submission = subreddit.submit(
                title=title,
                selftext=tweet_text,
                flair_id=flair_id
            )
            
            logger.info(f"Reddit'te metin olarak paylaşıldı: {submission.url}")
            return True
        
        try:
            # Anti-ban error handling ile Reddit'e gönder
            result = self._handle_reddit_errors(_submit_to_reddit)
            if result:
                # Başarılı post sonrası zamanı kaydet
                self.last_post_time = time.time()
                logger.info("Reddit post başarılı - anti-ban timer güncellendi")
                return True
            else:
                logger.error("Reddit paylaşımı tüm denemeler sonrası başarısız oldu")
                return False
                
        except Exception as e:
            logger.error(f"Reddit paylaşımı kritik hata: {e}")
            return False

    def cleanup_temp_files(self):
        try:
            for f in self.temp_dir.glob('*'):
                f.unlink()
            logger.info("Geçici medya dosyaları temizlendi")
        except Exception as e:
            logger.error(f"Temizlik hatası: {e}")

    def create_reddit_title(self, turkish_text: str, original_text: str) -> str:
        """Reddit için başlık oluştur"""
        title = turkish_text.strip()
        if '\n' in title:
            title = title.split('\n')[0].strip()
        if len(title) > 280:
            title = title[:280] + "..."
        return title

    def process_tweet(self, tweet: Dict) -> bool:
        tweet_id = tweet['id']
        tweet_text = tweet['text']

        if self.is_reply_or_retweet(tweet):
            logger.info(f"Tweet atlandı (cevap veya retweet): {tweet_id}")
            return False

        logger.info(f"Tweet işleniyor: {tweet_id}")

        cleaned_text = self.clean_tweet_text(tweet_text)
        turkish_text = self.translate_to_turkish(cleaned_text)

        # Medya işle: ana tweetin medyası
        main_media = self.process_media(tweet.get('media', []))

        # Alıntı tweet varsa onun medyasını da indir
        quoted_media = []
        quoted_tweet = tweet.get('quoted_tweet')
        if quoted_tweet:
            quoted_media = self.process_media(quoted_tweet.get('media', []))

            # Alıntı tweet metnini de çevirip mesaj içeriğine ekleyebiliriz
            quoted_text = quoted_tweet.get('text', '')
            cleaned_quoted_text = self.clean_tweet_text(quoted_text)
            translated_quoted_text = self.translate_to_turkish(cleaned_quoted_text)
            # Alıntı metni varsa, tweet_text sonuna ekle (veya istediğiniz formatta)
            turkish_text += "\n\nAlıntı Tweet:\n" + translated_quoted_text

        # Ana tweet + alıntı tweet medyalarını birleştir
        all_media = main_media + quoted_media

        title = self.create_reddit_title(turkish_text, turkish_text)

        if self.post_to_reddit(title, all_media, turkish_text):
            self.save_last_tweet_id(tweet_id)
            return True

        return False

    def run(self):
        logger.info("Bot çalışmaya başladı (RapidAPI çevirisi ile) - Anti-ban önlemleri aktif")
        logger.info(f"User Agent: {self.user_agent}")
        logger.info(f"Rastgele bekleme aralığı: {self.min_delay//60}-{self.max_delay//60} dakika")

        while True:
            try:
                last_tweet_id = self.read_last_tweet_id()
                tweets = self.get_latest_tweets()

                if not tweets:
                    logger.info("Tweet yok, kısa bekleme...")
                    time.sleep(random.randint(30, 90))  # 30-90 saniye rastgele
                    continue

                non_reply_retweet_tweets = [t for t in tweets if not self.is_reply_or_retweet(t)]

                if not non_reply_retweet_tweets:
                    logger.info("Yeni retweet veya yanıt olmayan tweet yok, kısa bekleme...")
                    time.sleep(random.randint(30, 90))  # 30-90 saniye rastgele
                    continue

                latest_tweet = non_reply_retweet_tweets[0]

                if last_tweet_id and latest_tweet['id'] == last_tweet_id:
                    logger.info("Yeni tweet yok, kısa bekleme...")
                    time.sleep(random.randint(30, 90))  # 30-90 saniye rastgele
                    continue

                success = self.process_tweet(latest_tweet)

                if success:
                    logger.info("Tweet başarıyla Reddit'te paylaşıldı")
                    # Başarılı post sonrası anti-ban rastgele bekleme
                    self._wait_random_delay()
                else:
                    logger.warning("Tweet işlenirken hata oluştu")
                    # Hata durumunda daha kısa bekleme
                    time.sleep(random.randint(60, 180))

                self.cleanup_temp_files()

            except KeyboardInterrupt:
                logger.info("Bot kapatıldı (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Gönderimde beklenmeyen hata: {e}")
                # Hata durumunda exponential backoff
                error_delay = random.randint(120, 300)  # 2-5 dakika
                logger.info(f"Hata sonrası {error_delay} saniye bekleniyor...")
                time.sleep(error_delay)


if __name__ == "__main__":
    try:
        bot = TwitterRedditBot()
        bot.run()
    except Exception as e:
        logger.error(f"Bot başlatılamadı: {e}")
        print(f"\nHata oluştu: {e}")
