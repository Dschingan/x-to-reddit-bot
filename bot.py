import os
import requests
import tweepy
import praw
import time
import re
from dotenv import load_dotenv
from requests.exceptions import ConnectionError
from urllib3.exceptions import ProtocolError
from http.client import RemoteDisconnected
import openai  # OpenAI import eklendi

load_dotenv()

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_USER_ID = os.getenv("TWITTER_USER_ID")
TWITTER_USER_ID_2 = os.getenv("TWITTER_USER_ID_2")  # BF6_TR için
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
USER_AGENT = os.getenv("USER_AGENT")
SUBREDDIT_NAME = os.getenv("SUBREDDIT_NAME")

FLAIR_ID = "a3c0f742-22de-11f0-9e24-7a8b08eb260a"

# OpenAI API anahtarını ayarla
openai.api_key = os.getenv("OPENAI_API_KEY")

def get_last_tweet_id_for_user(username):
    filename = f"last_tweet_id_{username}.txt"
    try:
        with open(filename, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

def save_last_tweet_id_for_user(username, tweet_id):
    filename = f"last_tweet_id_{username}.txt"
    with open(filename, "w") as f:
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

def get_latest_tweet_for_user(user_id, username):
    client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
    while True:
        try:
            tweets = client.get_users_tweets(
                id=user_id,
                max_results=5,
                expansions="attachments.media_keys,referenced_tweets.id,referenced_tweets.id.author_id",
                tweet_fields=["attachments", "created_at", "text", "in_reply_to_user_id", "referenced_tweets"],
                user_fields=["username"],
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
        except (ConnectionError, ProtocolError, RemoteDisconnected) as e:
            print(f"Bağlantı hatası: {e}. Tekrar deneniyor...")
            continue

    if not tweets.data:
        return None

    media = {m.media_key: m for m in tweets.includes.get("media", [])}
    users = {u.id: u for u in tweets.includes.get("users", [])} if tweets.includes.get("users") else {}

    for tweet in tweets.data:
        is_reply = tweet.in_reply_to_user_id is not None
        is_retweet_or_quote = hasattr(tweet, "referenced_tweets") and tweet.referenced_tweets is not None

        if username == "TheBFWire":
            if is_reply or is_retweet_or_quote:
                continue  # sadece özgün tweetler
        elif username == "BF6_TR":
            if is_reply:
                continue  # yanıt istemiyoruz ama repost olabilir
            if not is_retweet_or_quote:
                continue  # repost (retweet) değilse geç

        credit_username = None
        if username == "BF6_TR" and is_retweet_or_quote:
            ref_author_id = tweet.referenced_tweets[0].author_id if tweet.referenced_tweets else None
            if ref_author_id and ref_author_id in users:
                credit_username = users[ref_author_id].username

        tweet_info = {
            "id": str(tweet.id),
            "text": tweet.text,
            "media_urls": [],
            "video_url": None,
            "credit_username": credit_username
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

    return None

def clean_title(title):
    title = re.sub(r'https://t\.co/\w+', '', title)
    title = re.sub(r'#\w+', '', title)
    title = title.replace('|', '')
    return title.strip()

def translate_to_turkish(text):
    prompt = f"""Translate the following English text to Turkish.
ONLY return the Turkish translation — no quotes, no explanations, no formatting, just plain text.

{text}"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
            n=1,
        )
        translated_text = response['choices'][0]['message']['content'].strip().strip('"')
        return translated_text
    except Exception as e:
        print(f"OpenAI çeviri hatası: {e}")
        return text

def post_to_reddit(title, media_path=None, selftext=""):
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD,
        user_agent=USER_AGENT
    )

    subreddit = reddit.subreddit(SUBREDDIT_NAME)

    if media_path:
        if media_path.lower().endswith(".mp4"):
            subreddit.submit_video(
                title=title,
                video_path=media_path,
                flair_id=FLAIR_ID,
                description=selftext
            )
        else:
            subreddit.submit_image(
                title=title,
                image_path=media_path,
                flair_id=FLAIR_ID,
                description=selftext
            )
    else:
        subreddit.submit(
            title=title,
            selftext=selftext,
            flair_id=FLAIR_ID
        )

def main():
    user_map = {
        "TheBFWire": TWITTER_USER_ID,
        "BF6_TR": TWITTER_USER_ID_2
    }

    for username, user_id in user_map.items():
        print(f"\n--- {username} kullanıcısı kontrol ediliyor ---")

        last_id = get_last_tweet_id_for_user(username)
        tweet = get_latest_tweet_for_user(user_id, username)

        if not tweet:
            print(f"{username} için uygun tweet bulunamadı.")
            continue

        if last_id and tweet["id"] == last_id:
            print(f"{username} için yeni tweet yok.")
            continue

        print(f"{username} için yeni tweet bulundu: {tweet['text']}")

        raw_title = tweet["text"]
        cleaned_title = clean_title(raw_title)
        translated_title = translate_to_turkish(cleaned_title)
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

        selftext = ""
        if username == "BF6_TR" and tweet.get("credit_username"):
            selftext = f"Retweet sahibine kredi: @{tweet['credit_username']}"

        print("Reddit'e gönderiliyor...")
        post_to_reddit(title=translated_title, media_path=media_file, selftext=selftext)

        save_last_tweet_id_for_user(username, tweet["id"])
        print(f"{username} için işlem tamamlandı.")

if __name__ == "__main__":
    print("Program başladı.")
    while True:
        main()
