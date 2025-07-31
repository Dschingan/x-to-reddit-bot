import os
import requests
import tweepy
import praw
import time
import re
from dotenv import load_dotenv

load_dotenv()

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_USER_ID = os.getenv("TWITTER_USER_ID")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
USER_AGENT = os.getenv("USER_AGENT")
SUBREDDIT_NAME = os.getenv("SUBREDDIT_NAME")

FLAIR_ID = "a3c0f742-22de-11f0-9e24-7a8b08eb260a"
LAST_TWEET_FILE = "last_tweet_id.txt"

def get_last_tweet_id():
    if os.path.exists(LAST_TWEET_FILE):
        with open(LAST_TWEET_FILE, "r") as f:
            return f.read().strip()
    return None

def save_last_tweet_id(tweet_id):
    with open(LAST_TWEET_FILE, "w") as f:
        f.write(str(tweet_id))

def download_file(url, filename):
    r = requests.get(url, stream=True)
    if r.status_code == 200:
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
        return filename
    return None

def reencode_video(input_path, output_path):
    os.system(f'ffmpeg -y -i "{input_path}" -c:v libx264 -crf 23 -preset fast -c:a aac -b:a 128k "{output_path}"')

def get_latest_tweet_with_retry():
    client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
    while True:
        try:
            tweets = client.get_users_tweets(
                id=TWITTER_USER_ID,
                max_results=5,
                expansions="attachments.media_keys",
                tweet_fields=["attachments", "created_at", "text"],
                media_fields=["url", "type", "variants", "preview_image_url"]
            )
            break
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get("x-rate-limit-reset", 0))
            wait_seconds = max(reset_time - int(time.time()), 60)
            for remaining in range(wait_seconds, 0, -1):
                print(f"\rRate limit aşıldı. {remaining} saniye bekleniyor...   ", end="")
                time.sleep(1)
            print()
    if not tweets.data:
        return None

    tweet = tweets.data[0]
    media = {m.media_key: m for m in tweets.includes.get("media", [])}

    tweet_info = {
        "id": str(tweet.id),
        "text": tweet.text,
        "media_urls": [],
        "video_url": None
    }

    if tweet.attachments and "media_keys" in tweet.attachments:
        for key in tweet.attachments["media_keys"]:
            m = media.get(key)
            if m:
                if m.type == "photo":
                    tweet_info["media_urls"].append(m.url)
                elif m.type in ["video", "animated_gif"]:
                    variants = m.variants if hasattr(m, "variants") else m["variants"]
                    best = sorted(variants, key=lambda x: x.get("bit_rate", 0), reverse=True)
                    for variant in best:
                        if "url" in variant:
                            tweet_info["video_url"] = variant["url"]
                            break
    return tweet_info

def clean_title(title):
    # Tweet içindeki https://t.co/... linklerini tamamen kaldır
    return re.sub(r'https://t\.co/\S+', '', title).strip()

def post_to_reddit(title, media_path=None):
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=USER_AGENT,  # Reddit uyarısı için
        ratelimit_seconds=600  # Reddit API kuralına uygun: 10 dakika bekle
    )

    subreddit = reddit.subreddit(SUBREDDIT_NAME)
    submission = None

    if media_path:
        if media_path.lower().endswith(".mp4"):
            submission = subreddit.submit_video(
                title=title,
                video_path=media_path,
                flair_id=FLAIR_ID
            )
        else:
            submission = subreddit.submit_image(
                title=title,
                image_path=media_path,
                flair_id=FLAIR_ID
            )
    else:
        submission = subreddit.submit(
            title=title,
            selftext="",
            flair_id=FLAIR_ID
        )

TRANSLATION_API_URL = os.getenv("TRANSLATION_API_URL")
TRANSLATION_API_KEY = os.getenv("TRANSLATION_API_KEY")
TRANSLATION_API_HOST = os.getenv("TRANSLATION_API_HOST")

def translate_en_to_tr(text: str) -> str:
    try:
        headers = {
            "content-type": "application/json",
            "X-RapidAPI-Key": TRANSLATION_API_KEY,
            "X-RapidAPI-Host": TRANSLATION_API_HOST,
        }
        data = {
            "origin_language": "en",
            "target_language": "tr",
            "input_text": text,
        }
        response = requests.post(TRANSLATION_API_URL, json=data, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get("translation") or result.get("translatedText") or "[Çeviri yok]"
    except Exception as e:
        return f"[Çeviri Hatası: {e}]"

def main():
    print("Program başladı.")
    while True:
        last_id = get_last_tweet_id()
        tweet = get_latest_tweet_with_retry()

        if not tweet:
            print("Tweet bulunamadı. 60 sn sonra tekrar denenecek.")
            time.sleep(60)
            continue

        # RT (retweet) kontrolü
        if tweet["text"].strip().startswith("RT @"):
            print("Bu tweet bir retweet, atlanıyor.")
            time.sleep(10)
            continue

        # Eğer tweet objesinde retweet'i belirten başka bir alan varsa (ör. referenced_tweets)
        if "referenced_tweets" in tweet and tweet["referenced_tweets"]:
            for ref in tweet["referenced_tweets"]:
                if ref.get("type") == "retweeted":
                    print("Bu tweet bir retweet (referenced_tweets), atlanıyor.")
                    time.sleep(10)
                    break
            else:
                pass
            continue

    if tweet["id"] == last_id:
        print("Yeni tweet yok.")
        return

    print(f"Yeni tweet bulundu: {tweet['text']}")

    raw_title = tweet["text"]
    title = clean_title(raw_title)
    translated_title = translate_en_to_tr(title)
    media_file = None

    if tweet["video_url"]:
        print("Video indiriliyor...")
        media_file = download_file(tweet["video_url"], "video.mp4")
        if media_file:
            print("Video yeniden kodlanıyor...")
            reencode_video("video.mp4", "video_final.mp4")
            media_file = "video_final.mp4"

    elif tweet["media_urls"]:
        print("Fotoğraf indiriliyor...")
        media_file = download_file(tweet["media_urls"][0], "image.jpg")

    print("Reddit'e gönderiliyor...")
    post_to_reddit(title=translated_title, media_path=media_file)

    save_last_tweet_id(tweet["id"])
    print("İşlem tamamlandı.")

if __name__ == "__main__":
    main()
