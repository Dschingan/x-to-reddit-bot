# TwitterRedditBot - Bot Açıklaması
#
# Amaç:
#   - Belirli bir Twitter kullanıcısının son tweetlerini takip eder.
#   - Tweetlerden retweet veya yanıt (reply) olmayanları seçer.
#   - Tweet metinlerini RapidAPI kullanarak Türkçeye çevirir.
#   - Tweetlerdeki varsa medya içeriklerini indirir, video formatlarını Reddit'e uygun hale getirir.
#   - Çeviri ve medya ile Reddit'te önceden belirlenmiş subreddit'e otomatik olarak gönderi yapar.
#
# Ana İşlevler:
#   1. Ortam Değişkenlerini (.env) okuma:
#       - Twitter API bilgileri (token, user id vs)
#       - Reddit API bilgileri (client id, secret, user/pass, user agent)
#       - RapidAPI çeviri servisi bilgileri (api key, url, host)
#       - Subreddit ismi ve flair ID'leri
#
#   2. Twitter API'den son 5 tweeti çekme:
#       - Tweetlerle birlikte medya (foto, video) bilgilerini alma
#       - Rate limit (kota) kontrolü yapma ve gerekiyorsa bekleme
#
#   3. Tweet temizleme:
#       - Linkler, hashtagler, "|" karakteri ve fazla boşlukları temizleme
#
#   4. Tweet metnini Türkçeye çevirme:
#       - RapidAPI üzerinde belirlenen çeviri servisi kullanılır
#       - JSON yanıtından "translation" alanı kullanılarak çeviri alınır
#
#   5. Retweet ve yanıt tweetleri filtreleme:
#       - Retweet veya reply içerikli tweetler atlanır
#
#   6. Medya işlemleri:
#       - Fotoğraflar indirilir
#       - Videolar en iyi varyantı seçilip indirilir
#       - İndirilen videolar ffmpeg ile Reddit uyumlu hale dönüştürülür
#
#   7. Reddit gönderisi paylaşımı:
#       - İçeriğe göre uygun flair atanır (örneğin haber, sızıntı, tartışma)
#       - Medya sayısına göre tek resim, video, galeri veya metin olarak paylaşılır
#
#   8. Son işlenen tweet ID'sinin takibi:
#       - İşlenen tweetin ID'si dosyada saklanır, tekrar işlenmez
#
#   9. Sürekli çalışma:
#       - Döngü içinde belirli aralıklarla yeni tweetler kontrol edilir ve işlenir
#
#   10. Hata yönetimi ve loglama:
#       - Tüm önemli işlemler ve hata durumları loglanır
#       - API hatalarında ve beklenmeyen durumlarda uygun hata yönetimi yapılır
#
# Kullanım:
#   - Gerekli API anahtarları ve ayarlar .env dosyasına girilir
#   - Python ortamında gerekli paketler (requests, praw, dotenv, vb.) kurulur
#   - Sisteme ffmpeg kurulup PATH'e eklenir
#   - Bot çalıştırılarak otomatik Twitter -> Reddit paylaşımı sağlanır
#

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
        self.user_agent = os.getenv('USER_AGENT')
        self.subreddit_name = os.getenv('SUBREDDIT_NAME')
        
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
        """Twitter'dan son tweet'leri al"""
        url = f"https://api.twitter.com/2/users/{self.twitter_user_id}/tweets"
        params = {
            'max_results': 5,
            'tweet.fields': 'created_at,attachments,in_reply_to_user_id,referenced_tweets',
            'media.fields': 'type,url,variants,preview_image_url',
            'expansions': 'attachments.media_keys'
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
                    media_data = {media['media_key']: media for media in data.get('includes', {}).get('media', [])}
                    
                    for tweet in tweets:
                        if 'attachments' in tweet and 'media_keys' in tweet['attachments']:
                            tweet['media'] = [media_data.get(key) for key in tweet['attachments']['media_keys']]
                    
                    logger.info(f"{len(tweets)} tweet alındı")
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
        # Linkleri ve hashtagleri kaldır
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
            "origin_language": "en",  # Kaynak dil
            "target_language": "tr",  # Hedef dil
            "words_not_to_translate": "",  # İstemediğiniz kelimeler varsa
            "input_text": text
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.translation_api_url,
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                logger.info(f"RapidAPI raw response: {json.dumps(data, ensure_ascii=False)}")

                # Düzeltme: Çeviri 'translation' alanında geliyor.
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
        """Videoyu Reddit için uygun formata dönüştür"""
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
        """En iyi video varyantını seç"""
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
        """Medya dosyalarını işle"""
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
        """Tweet içeriğine göre flair belirle"""
        text_lower = tweet_text.lower()
        if any(word in text_lower for word in ['breaking', 'urgent', 'alert', 'news', 'report']):
            return self.flair_haberler
        elif any(word in text_lower for word in ['leak', 'rumor', 'source', 'insider']):
            return self.flair_sizinti
        else:
            return self.flair_tartisma or self.flair_haberler

    def is_reply_or_retweet(self, tweet: Dict) -> bool:
        """Tweet yanıt ya da retweet ise True döner"""
        # Reply ise
        if tweet.get('in_reply_to_user_id'):
            return True

        # Referenced tweets kontrolü
        referenced = tweet.get('referenced_tweets', [])
        for ref in referenced:
            # Reply veya retweet tipi olabilir
            if ref.get('type') in ['replied_to', 'retweeted']:
                return True
        return False
    
    def post_to_reddit(self, title: str, media_paths: List[str], tweet_text: str) -> bool:
        """Reddit'e gönderi paylaş"""
        try:
            subreddit = self.reddit.subreddit(self.subreddit_name)
            flair_id = self.determine_flair(tweet_text)
            self.reddit.validate_on_submit = True

            if media_paths:
                # Eğer 1 medya varsa tekil post, 2+ medya varsa galeri
                if len(media_paths) == 1:
                    media_entry = media_paths[0]
                    ext = os.path.splitext(media_entry)[1].lower()

                    if ext in ['.mp4', '.mkv', '.avi', '.mov']:
                        # Video dosyasıysa
                        try:
                            submission = subreddit.submit_video(
                                title=title,
                                video_path=media_entry,
                                flair_id=flair_id
                            )
                        except Exception as e:
                            logger.error(f"Video yükleme hatası: {e}, metin olarak denenecek.")
                            submission = subreddit.submit(title, selftext=tweet_text + "\n\n(Video yüklenemedi)", flair_id=flair_id)
                    else:
                        # Resim dosyası
                        submission = subreddit.submit_image(
                            title=title,
                            image_path=media_entry,
                            flair_id=flair_id
                        )
                else:
                    # Galeri gönderisi
                    image_paths = [p for p in media_paths if os.path.splitext(p)[1].lower() in ['.jpg', '.jpeg', '.png', '.gif']]
                    if image_paths:
                        media_gallery = [{'image_path': p} for p in image_paths]
                        submission = subreddit.submit_gallery(
                            title=title,
                            images=media_gallery,
                            flair_id=flair_id
                        )
                    else:
                        submission = subreddit.submit(
                            title=title,
                            selftext=tweet_text,
                            flair_id=flair_id
                        )
            else:
                # Medya yoksa sadece metin gönder
                submission = subreddit.submit(
                    title=title,
                    selftext=tweet_text,
                    flair_id=flair_id
                )

            logger.info(f"Reddit'e gönderildi: {submission.url}")
            return True
        except Exception as e:
            logger.error(f"Reddit paylaşımı başarısız oldu: {e}")
            return False
    
    def cleanup_temp_files(self):
        """Geçici dosyaları temizle"""
        try:
            for f in self.temp_dir.glob('*'):
                f.unlink()
            logger.info("Geçici medya dosyaları temizlendi")
        except Exception as e:
            logger.error(f"Temizlik hatası: {e}")
    
    def create_reddit_title(self, turkish_text: str, original_text: str) -> str:
        """Reddit için başlık oluştur"""
        text_to_use = turkish_text if turkish_text != original_text else original_text

        # Başlık satırı olarak ilk satır veya tüm metin
        if '\n' in text_to_use:
            title = text_to_use.split('\n')[0].strip()
        else:
            title = text_to_use.strip()

        # Başlık kısa ise orijinal metinle genişlet
        if len(title) < 50 and turkish_text != original_text:
            extended = original_text[:100].strip()
            title = f"{title} | {extended}"

        # Başlık uzun ise kes
        if len(title) > 280:
            title = title[:280] + "..."
        return title
    
    def process_tweet(self, tweet: Dict) -> bool:
        """Tek bir tweet'i işler"""
        tweet_id = tweet['id']
        tweet_text = tweet['text']

        # Reply veya retweet tweetleri atla (burada tekrar kontrol opsiyonel)
        if self.is_reply_or_retweet(tweet):
            logger.info(f"Tweet atlandı (cevap veya retweet): {tweet_id}")
            return False

        logger.info(f"Tweet işleniyor: {tweet_id}")

        cleaned_text = self.clean_tweet_text(tweet_text)
        turkish_text = self.translate_to_turkish(cleaned_text)
        media_paths = self.process_media(tweet.get('media', []))

        title = self.create_reddit_title(turkish_text, tweet_text)
        if self.post_to_reddit(title, media_paths, turkish_text):
            self.save_last_tweet_id(tweet_id)
            return True
        
        return False

    def run(self):
        """Ana döngü"""
        logger.info("Bot çalışmaya başladı (RapidAPI çevirisi ile)")

        while True:
            try:
                last_tweet_id = self.read_last_tweet_id()
                tweets = self.get_latest_tweets()

                if not tweets:
                    logger.info("Tweet yok, 60 saniye bekleniyor...")
                    time.sleep(60)
                    continue

                # Yanıt veya retweet olmayan tweetleri filtrele
                non_reply_retweet_tweets = [t for t in tweets if not self.is_reply_or_retweet(t)]

                if not non_reply_retweet_tweets:
                    logger.info("Yeni retweet veya yanıt olmayan tweet yok, 60 saniye bekleniyor...")
                    time.sleep(60)
                    continue

                latest_tweet = non_reply_retweet_tweets[0]

                if last_tweet_id and latest_tweet['id'] == last_tweet_id:
                    logger.info("Yeni tweet yok, 60 saniye bekleniyor...")
                    time.sleep(60)
                    continue
                
                success = self.process_tweet(latest_tweet)

                if success:
                    logger.info("Tweet başarıyla Reddit'te paylaşıldı")
                else:
                    logger.warning("Tweet işlenirken hata oluştu")

                self.cleanup_temp_files()
                time.sleep(300)  # 5 dakika bekle

            except KeyboardInterrupt:
                logger.info("Bot kapatıldı (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Gönderimde beklenmeyen hata: {e}")
                time.sleep(60)

if __name__ == "__main__":
    try:
        bot = TwitterRedditBot()
        bot.run()
    except Exception as e:
        logger.error(f"Bot başlatılamadı: {e}")
        print(f"\nHata oluştu: {e}")
