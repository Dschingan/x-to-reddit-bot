import os
import json
import time
import base64
import asyncio
import aiofiles
import aiohttp
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT")
SUBREDDIT_NAME = os.getenv("SUBREDDIT_NAME")
TWITTER_RAPIDAPI_KEY = os.getenv("TWITTER_RAPIDAPI_KEY")
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME")

POSTED_TWEETS_FILE = Path("./postedTweets.json")
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB

REDDIT_OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE_URL = "https://oauth.reddit.com"


async def sleep(ms):
    await asyncio.sleep(ms / 1000)


async def load_posted_tweets():
    if not POSTED_TWEETS_FILE.exists():
        return set()
    try:
        async with aiofiles.open(POSTED_TWEETS_FILE, "r", encoding="utf-8") as f:
            data = await f.read()
        return set(json.loads(data))
    except Exception as e:
        print(f"Gönderilen tweet dosyası okunamadı: {e}")
        return set()


async def save_posted_tweet(tweet_id, posted_set):
    try:
        posted_set.add(tweet_id)
        async with aiofiles.open(POSTED_TWEETS_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps(list(posted_set), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Gönderilen tweet dosyasına yazılamadı: {e}")


async def get_reddit_access_token_password_grant(session):
    basic_auth = base64.b64encode(f"{REDDIT_CLIENT_ID}:{REDDIT_CLIENT_SECRET}".encode()).decode()
    data = {
        "grant_type": "password",
        "username": REDDIT_USERNAME,
        "password": REDDIT_PASSWORD,
    }
    headers = {
        "Authorization": f"Basic {basic_auth}",
        "User-Agent": REDDIT_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with session.post(REDDIT_OAUTH_TOKEN_URL, data=data, headers=headers) as resp:
        resp.raise_for_status()
        json_resp = await resp.json()
        print("Password grant token alındı:", "EVET" if json_resp.get("access_token") else "HAYIR")
        return json_resp.get("access_token")


async def get_reddit_access_token_installed_client(session):
    basic_auth = base64.b64encode(f"{REDDIT_CLIENT_ID}:".encode()).decode()
    data = {
        "grant_type": "installed_client",
        "device_id": "DO_NOT_TRACK_THIS_DEVICE",
    }
    headers = {
        "Authorization": f"Basic {basic_auth}",
        "User-Agent": REDDIT_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with session.post(REDDIT_OAUTH_TOKEN_URL, data=data, headers=headers) as resp:
        resp.raise_for_status()
        json_resp = await resp.json()
        print("Installed client grant token alındı:", "EVET" if json_resp.get("access_token") else "HAYIR")
        return json_resp.get("access_token")


async def get_latest_tweet_with_video(session, screen_name, posted_set):
    url = "https://twitter-api45.p.rapidapi.com/timeline.php"
    headers = {
        "x-rapidapi-key": TWITTER_RAPIDAPI_KEY,
        "x-rapidapi-host": "twitter-api45.p.rapidapi.com",
    }
    params = {"screenname": screen_name}

    async with session.get(url, headers=headers, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
        print("Twitter API response data:", json.dumps(data, indent=2, ensure_ascii=False))

        timeline = data.get("timeline", [])
        for tweet in timeline:
            if tweet.get("retweeted_tweet") or tweet.get("quoted_tweet") or tweet.get("in_reply_to_status_id_str"):
                continue
            media = tweet.get("media", {})
            if not media:
                continue
            tweet_id = tweet.get("tweet_id")
            if tweet_id in posted_set:
                continue
            video_media = None
            if "video" in media and len(media["video"]) > 0:
                video_media = media["video"][0]
            if not video_media:
                continue
            variants = video_media.get("variants", [])
            if not variants:
                continue
            mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
            if not mp4s:
                continue
            best_video = max(mp4s, key=lambda v: v.get("bitrate", 0))
            return {"tweet": tweet, "videoUrl": best_video.get("url")}
        return None


async def download_video(session, url, filepath):
    async with session.get(url) as resp:
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            while True:
                chunk = await resp.content.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)


async def reencode_video(input_path, output_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-vf",
        "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg hatası: {stderr.decode()}")
    print(f"Video yeniden kodlandı: {output_path}")


async def check_file_size(filepath):
    return os.path.getsize(filepath)


async def get_upload_info(session, access_token, video_file_path, max_retries=3):
    file_size = os.path.getsize(video_file_path)
    file_name = os.path.basename(video_file_path)
    url = f"{REDDIT_API_BASE_URL}/api/media/asset.json"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": REDDIT_USER_AGENT,
        "Content-Type": "application/json",
    }

    payload = {
        "filepath": file_name,
        "mimetype": "video/mp4",
        "fileSize": file_size,
    }

    for attempt in range(1, max_retries + 1):
        try:
            print(f"Upload info denemesi {attempt}/{max_retries}...")
            async with session.post(url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                print("Upload info alındı:", data)
                return data
        except aiohttp.ClientResponseError as e:
            if e.status == 500 and attempt < max_retries:
                print("500 hatası alındı, 3 saniye bekleyip tekrar deneniyor...")
                await asyncio.sleep(3)
                continue
            else:
                raise RuntimeError(f"Reddit upload info alma hatası: {e}")
        except Exception as e:
            raise RuntimeError(f"Reddit upload info alma hatası: {e}")


async def upload_video_to_s3(session, upload_data, video_file_path):
    action = upload_data["args"]["action"]
    fields = upload_data["args"]["fields"]

    form = aiohttp.FormData()
    for k, v in fields.items():
        form.add_field(k, v)
    with open(video_file_path, "rb") as f:
        form.add_field("file", f, filename=os.path.basename(video_file_path), content_type="video/mp4")

        async with session.post(action, data=form) as resp:
            if resp.status != 204:
                text = await resp.text()
                raise RuntimeError(f"Video upload başarısız, status: {resp.status}, response: {text}")


async def submit_video_post(session, access_token, subreddit, title, asset_id):
    url = f"{REDDIT_API_BASE_URL}/api/submit"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": REDDIT_USER_AGENT,
        "Content-Type": "application/json",
    }
    payload = {
        "sr": subreddit,
        "kind": "video",
        "title": title,
        "resubmit": True,
        "api_type": "json",
        "media_asset_id": asset_id,
    }
    async with session.post(url, json=payload, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
        errors = data.get("json", {}).get("errors", [])
        if errors:
            raise RuntimeError(f"Reddit gönderme hatası: {errors}")
        return data.get("json", {}).get("data", {})


async def clean_up_file(filepath):
    try:
        os.remove(filepath)
    except Exception as e:
        print(f"Dosya silme hatası: {e}")


async def run_cycle():
    print("Başlıyor...")
    posted_set = await load_posted_tweets()

    async with aiohttp.ClientSession() as session:
        try:
            try:
                access_token = await get_reddit_access_token_password_grant(session)
            except Exception:
                print("Password grant ile token alınamadı, installed client denenecek...")
                access_token = await get_reddit_access_token_installed_client(session)

            tweet_with_video = await get_latest_tweet_with_video(session, TWITTER_USERNAME, posted_set)

            if not tweet_with_video:
                print("Video içeren uygun yeni tweet bulunamadı.")
                return

            raw_video_path = "./temp_video_raw.mp4"
            reencoded_video_path = "./temp_video.mp4"

            print("Video indiriliyor...")
            await download_video(session, tweet_with_video["videoUrl"], raw_video_path)

            print("Video yeniden kodlanıyor...")
            await reencode_video(raw_video_path, reencoded_video_path)

            await clean_up_file(raw_video_path)  # Ham videoyu sil

            size = await check_file_size(reencoded_video_path)
            if size > MAX_VIDEO_SIZE:
                print("Video dosyası çok büyük, atlanıyor.")
                await clean_up_file(reencoded_video_path)
                return

            print("Reddit video upload bilgisi alınıyor...")
            upload_info = await get_upload_info(session, access_token, reencoded_video_path)

            print("Video S3'e yükleniyor...")
            await upload_video_to_s3(session, upload_info, reencoded_video_path)

            print("Reddit gönderisi oluşturuluyor...")
            post_result = await submit_video_post(
                session,
                access_token,
                SUBREDDIT_NAME,
                tweet_with_video["tweet"]["text"],
                upload_info["asset"]["asset_id"],
            )

            print("Reddit gönderisi başarılı:", post_result)

            await save_posted_tweet(tweet_with_video["tweet"]["tweet_id"], posted_set)

            await clean_up_file(reencoded_video_path)

        except Exception as e:
            print("Hata:", e)


async def main_loop():
    while True:
        try:
            await run_cycle()
        except Exception as e:
            print("Ana döngüde hata yakalandı, devam ediyor:", e)
        print("2 saat bekleniyor...")
        await asyncio.sleep(7200)  # 2 saat


if __name__ == "__main__":
    asyncio.run(main_loop())
