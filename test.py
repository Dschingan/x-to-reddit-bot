import os
from dotenv import load_dotenv
import praw

# .env dosyasını yükle
load_dotenv()

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
USER_AGENT = os.getenv("USER_AGENT")
SUBREDDIT_NAME = os.getenv("SUBREDDIT_NAME")  # .env içinde yoksa elle gir

# Reddit API'ye bağlan
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    username=REDDIT_USERNAME,
    password=REDDIT_PASSWORD,
    user_agent=USER_AGENT
)

# Subreddit’i al
subreddit = reddit.subreddit(SUBREDDIT_NAME)

# Flair’ları listele
print(f"r/{SUBREDDIT_NAME} subreddit'indeki kullanılabilir flair'lar:\n")
for flair in subreddit.flair.link_templates:
    flair_text = flair.get("text", "")
    flair_id = flair.get("id", "")
    print(f"Flair: {flair_text}  →  ID: {flair_id}")
