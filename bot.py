import os
import time
import random
import logging
import requests
import praw
import tweepy
from datetime import datetime
from dotenv import load_dotenv
import tempfile
import shutil

"""
BF6 Twitter ➜ Reddit retweet bot

Monitors the BF6_TR account *only for retweets*. When the user retweets a tweet that
contains media (photo or video), the bot:
1. Retrieves the original tweet and its media.
2. Translates the tweet text to Turkish.
3. Posts the media to the configured subreddit with:
   - Title = translated text (truncated to 300 chars)
   - Body = original text, translated text, tweet link, and credit to the original author.
4. Ensures each retweet is processed only once (last_retweet_id_user2.txt).

Anti-ban basics: 5-15 min random delay between Reddit posts.
"""

load_dotenv()

# ────────────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bf6_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────────────────────────

def translate_text(text: str, target_language: str = "tr") -> str:
    """Translate text via RapidAPI (same creds as main bot)."""
    try:
        api_key = os.getenv("TRANSLATION_API_KEY")
        api_url = os.getenv("TRANSLATION_API_URL")
        api_host = os.getenv("TRANSLATION_API_HOST")
        if not all([api_key, api_url, api_host]):
            logger.warning("Translation API credentials missing; returning original text")
            return text

        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": api_host,
            "Content-Type": "application/json",
        }
        payload = {"text": text, "target": target_language, "source": "auto"}
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            translated = resp.json().get("translatedText", text)
            logger.debug("Translated → %s", translated[:80])
            return translated
        logger.error("Translation failed %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Translation error: %s", exc)
    return text  # Fallback to original text


def download_media(url: str) -> str | None:
    """Download media to a temp file and return the local path."""
    try:
        resp = requests.get(url, stream=True, timeout=30)
        if resp.status_code == 200:
            suffix = os.path.splitext(url)[1].split("?")[0] or ".jpg"
            fd, path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as f_out:
                shutil.copyfileobj(resp.raw, f_out)
            return path
        logger.error("Failed to download media: %s", resp.status_code)
    except Exception as exc:
        logger.error("Download error: %s", exc)
    return None


def wait_human(min_s: int = 5 * 60, max_s: int = 15 * 60):
    delay = random.randint(min_s, max_s)
    logger.info("Sleeping %s seconds to mimic human behaviour", delay)
    time.sleep(delay)

# ────────────────────────────────────────────────────────────────────────────────
# Main Bot Class
# ────────────────────────────────────────────────────────────────────────────────

class Bf6RetweetBot:
    """Dedicated bot for BF6_TR retweets."""

    def __init__(self):
        # Twitter
        self.twitter_client = tweepy.Client(
            bearer_token=os.getenv("TWITTER_BEARER_TOKEN"), wait_on_rate_limit=True
        )
        self.user_id = os.getenv("TWITTER_USER_ID_2")  # BF6_TR id
        if not self.user_id:
            raise ValueError("TWITTER_USER_ID_2 missing in environment")

        # Reddit
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            username=os.getenv("REDDIT_USERNAME"),
            password=os.getenv("REDDIT_PASSWORD"),
            user_agent=os.getenv(
                "USER_AGENT",
                "BF6RetweetBot/1.0 (by /u/{})".format(os.getenv("REDDIT_USERNAME", "unknown")),
            ),
        )
        self.subreddit_name = os.getenv("SUBREDDIT_NAME", "BF6_TR")

        self.last_file = "last_retweet_id_user2.txt"
        logger.info("Bot initialized for user2 (BF6_TR)")

    # ────────────────────────────────────────────────────────────────────────
    # Helpers to track already-processed tweets
    # ────────────────────────────────────────────────────────────────────────

    def _get_last_id(self) -> str | None:
        if os.path.exists(self.last_file):
            return open(self.last_file).read().strip() or None
        return None

    def _save_last_id(self, tweet_id: str):
        with open(self.last_file, "w", encoding="utf-8") as fp:
            fp.write(tweet_id)

    # ────────────────────────────────────────────────────────────────────────
    # Core logic
    # ────────────────────────────────────────────────────────────────────────

    def fetch_and_post(self):
        logger.info("Checking for new retweets …")
        last_id = self._get_last_id()

        tweets = self.twitter_client.get_users_tweets(
            id=self.user_id,
            max_results=10,
            exclude=["replies"],
            tweet_fields=["referenced_tweets", "attachments", "text"],
            expansions=["attachments.media_keys", "referenced_tweets.id", "referenced_tweets.id.author_id"],
            media_fields=["url", "preview_image_url", "type"],
            user_fields=["username"],
            since_id=last_id,
        )
        if not tweets.data:
            logger.info("No new tweets")
            return

        includes = tweets.includes or {}
        media_map = {m["media_key"]: m for m in includes.get("media", [])}
        users_map = {u["id"]: u for u in includes.get("users", [])}
        tweets_sorted = sorted(tweets.data, key=lambda t: t.id)

        for retweet in tweets_sorted:
            if not retweet.referenced_tweets:
                continue  # not a retweet
            if retweet.referenced_tweets[0].type != "retweeted":
                continue

            orig_id = retweet.referenced_tweets[0].id
            # Retrieve original tweet full object (if not in includes)
            orig_tweet_resp = self.twitter_client.get_tweet(
                id=orig_id,
                tweet_fields=["text", "attachments", "author_id"],
                expansions=["attachments.media_keys", "author_id"],
                media_fields=["url", "type", "preview_image_url"],
                user_fields=["username"],
            )
            orig = orig_tweet_resp.data
            orig_includes = orig_tweet_resp.includes or {}
            if not orig:
                logger.warning("Original tweet %s not found", orig_id)
                continue

            author = users_map.get(orig.author_id) or orig_includes.get("users", [{}])[0]
            author_username = author.get("username", "unknown")

            media_keys = (orig.attachments or {}).get("media_keys", [])
            media_url = None
            for key in media_keys:
                m = media_map.get(key) or next(
                    (i for i in orig_includes.get("media", []) if i["media_key"] == key),
                    None,
                )
                if m and m["type"] in {"photo", "video"}:
                    media_url = m.get("url") or m.get("preview_image_url")
                    break

            translated = translate_text(orig.text)
            title = (translated[:297] + "…") if len(translated) > 300 else translated

            body_lines = [
                f"Orijinal Tweet: https://twitter.com/{author_username}/status/{orig.id}",
                f"\nKredi: @{author_username}",
                "\n---\n",
                "Orijinal: \n" + orig.text,
                "\n---\n",
                "Çeviri (TR): \n" + translated,
            ]
            body = "\n".join(body_lines)

            subreddit = self.reddit.subreddit(self.subreddit_name)
            try:
                if media_url:
                    path = download_media(media_url)
                    if path:
                        submission = subreddit.submit_image(title=title, image_path=path)
                        os.unlink(path)
                    else:
                        submission = subreddit.submit(title=title, selftext=body)
                else:
                    submission = subreddit.submit(title=title, selftext=body)
                logger.info("Posted to Reddit: %s", submission.url)
                self._save_last_id(str(retweet.id))
                wait_human()  # delay before next possible post
            except praw.exceptions.APIException as api_exc:
                logger.error("Reddit API error: %s", api_exc)
            except Exception as exc:
                logger.error("Unexpected error posting: %s", exc)

    # ────────────────────────────────────────────────────────────────────────


def main():
    bot = Bf6RetweetBot()
    bot.fetch_and_post()


if __name__ == "__main__":
    main()
