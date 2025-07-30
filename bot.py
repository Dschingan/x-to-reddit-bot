import os
import time
import json
import random
import logging
import requests
import praw
from datetime import datetime, timedelta
from dotenv import load_dotenv
import tweepy
from urllib.parse import urlparse
import tempfile
import shutil

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TwitterRedditBot:
    def __init__(self):
        # Twitter API setup
        self.twitter_bearer_token = os.getenv('TWITTER_BEARER_TOKEN')
        self.twitter_user_id = os.getenv('TWITTER_USER_ID')  # user1: TheBFWire
        self.twitter_username = os.getenv('TWITTER_USERNAME')
        
        # Reddit API setup
        self.reddit = praw.Reddit(
            client_id=os.getenv('REDDIT_CLIENT_ID'),
            client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
            username=os.getenv('REDDIT_USERNAME'),
            password=os.getenv('REDDIT_PASSWORD'),
            user_agent=os.getenv('USER_AGENT', 'TwitterRedditBot/1.0 (by /u/Glass-Fun5555; Python/3.9; Windows)')
        )
        
        self.subreddit_name = os.getenv('SUBREDDIT_NAME', 'BF6_TR')
        self.flair_haberler = os.getenv('FLAIR_HABERLER')
        
        # Translation API setup
        self.translation_api_key = os.getenv('TRANSLATION_API_KEY')
        self.translation_api_url = os.getenv('TRANSLATION_API_URL')
        self.translation_api_host = os.getenv('TRANSLATION_API_HOST')
        
        # Twitter API client
        self.twitter_client = tweepy.Client(
            bearer_token=self.twitter_bearer_token,
            wait_on_rate_limit=True
        )
        
        # File to store last tweet ID
        self.last_tweet_file = 'last_tweet_id.txt'
        
        # Anti-ban settings
        self.min_delay_between_posts = 300  # 5 minutes minimum
        self.max_delay_between_posts = 900  # 15 minutes maximum
        self.last_post_time = 0
        
        logger.info("TwitterRedditBot initialized successfully")
    
    def get_last_tweet_id(self):
        """Get the last processed tweet ID from file"""
        try:
            if os.path.exists(self.last_tweet_file):
                with open(self.last_tweet_file, 'r') as f:
                    tweet_id = f.read().strip()
                    return tweet_id if tweet_id else None
            return None
        except Exception as e:
            logger.error(f"Error reading last tweet ID: {e}")
            return None
    
    def save_last_tweet_id(self, tweet_id):
        """Save the last processed tweet ID to file"""
        try:
            with open(self.last_tweet_file, 'w') as f:
                f.write(str(tweet_id))
            logger.info(f"Saved last tweet ID: {tweet_id}")
        except Exception as e:
            logger.error(f"Error saving last tweet ID: {e}")
    
    def get_latest_tweet_with_media(self):
        """Fetch the latest tweet from user1 that contains media"""
        try:
            logger.info(f"Fetching latest tweet from user {self.twitter_username} ({self.twitter_user_id})")
            
            # Get user's tweets with media
            tweets = self.twitter_client.get_users_tweets(
                id=self.twitter_user_id,
                max_results=10,
                tweet_fields=['created_at', 'public_metrics', 'attachments'],
                media_fields=['url', 'preview_image_url', 'type'],
                expansions=['attachments.media_keys']
            )
            
            if not tweets.data:
                logger.warning("No tweets found")
                return None
            
            last_tweet_id = self.get_last_tweet_id()
            
            # Find the latest tweet with media that hasn't been processed
            for tweet in tweets.data:
                # Skip if this tweet was already processed
                if last_tweet_id and str(tweet.id) == last_tweet_id:
                    logger.info(f"Tweet {tweet.id} already processed, skipping")
                    continue
                
                # Check if tweet has media attachments
                if hasattr(tweet, 'attachments') and tweet.attachments:
                    media_keys = tweet.attachments.get('media_keys', [])
                    if media_keys and tweets.includes and 'media' in tweets.includes:
                        # Find media objects
                        media_objects = []
                        for media in tweets.includes['media']:
                            if media.media_key in media_keys:
                                media_objects.append(media)
                        
                        if media_objects:
                            logger.info(f"Found tweet with media: {tweet.id}")
                            return {
                                'tweet': tweet,
                                'media': media_objects
                            }
            
            logger.info("No new tweets with media found")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching tweets: {e}")
            return None
    
    def translate_text(self, text, target_language='tr'):
        """Translate text using RapidAPI translation service"""
        try:
            headers = {
                'X-RapidAPI-Key': self.translation_api_key,
                'X-RapidAPI-Host': self.translation_api_host,
                'Content-Type': 'application/json'
            }
            
            payload = {
                'text': text,
                'target': target_language,
                'source': 'auto'
            }
            
            response = requests.post(self.translation_api_url, json=payload, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                translated_text = result.get('translatedText', text)
                logger.info(f"Translation successful: {text[:50]}... -> {translated_text[:50]}...")
                return translated_text
            else:
                logger.error(f"Translation failed: {response.status_code} - {response.text}")
                return text  # Return original text if translation fails
                
        except Exception as e:
            logger.error(f"Error during translation: {e}")
            return text  # Return original text if translation fails
    
    def download_media(self, media_url):
        """Download media file to temporary location"""
        try:
            response = requests.get(media_url, stream=True)
            if response.status_code == 200:
                # Create temporary file
                temp_file = tempfile.NamedTemporaryFile(delete=False)
                
                # Copy content to temp file
                shutil.copyfileobj(response.raw, temp_file)
                temp_file.close()
                
                logger.info(f"Downloaded media to: {temp_file.name}")
                return temp_file.name
            else:
                logger.error(f"Failed to download media: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
            return None
    
    def _wait_random_delay(self, min_seconds=30, max_seconds=90):
        """Wait for a random delay to mimic human behavior"""
        delay = random.randint(min_seconds, max_seconds)
        logger.info(f"Waiting {delay} seconds for anti-ban delay...")
        time.sleep(delay)
    
    def _check_rate_limit(self):
        """Ensure minimum time between posts to avoid rate limiting"""
        current_time = time.time()
        time_since_last_post = current_time - self.last_post_time
        
        if time_since_last_post < self.min_delay_between_posts:
            wait_time = self.min_delay_between_posts - time_since_last_post
            logger.info(f"Rate limiting: waiting {wait_time:.0f} seconds before posting")
            time.sleep(wait_time)
    
    def _handle_reddit_errors(self, func, *args, **kwargs):
        """Handle Reddit API errors with retry mechanism"""
        max_retries = 3
        base_delay = 60  # 1 minute
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except praw.exceptions.TooManyRequests:
                wait_time = 3600  # 1 hour for rate limit
                logger.warning(f"Reddit rate limit hit. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
            except (praw.exceptions.ServerError, praw.exceptions.RequestException) as e:
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Reddit error (attempt {attempt + 1}): {e}. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Reddit error after {max_retries} attempts: {e}")
                    raise
            except Exception as e:
                logger.error(f"Unexpected Reddit error: {e}")
                raise
    
    def post_to_reddit(self, tweet_data):
        """Post tweet content and media to Reddit"""
        try:
            tweet = tweet_data['tweet']
            media_objects = tweet_data['media']
            
            # Translate tweet text
            original_text = tweet.text
            translated_text = self.translate_text(original_text)
            
            # Create post title and content
            title = f"@{self.twitter_username}: {translated_text[:100]}{'...' if len(translated_text) > 100 else ''}"
            
            # Create post content with original and translated text
            post_content = f"**Orijinal Tweet (@{self.twitter_username}):**\n{original_text}\n\n"
            post_content += f"**Çeviri:**\n{translated_text}\n\n"
            post_content += f"**Tweet Linki:** https://twitter.com/{self.twitter_username}/status/{tweet.id}"
            
            # Check rate limiting
            self._check_rate_limit()
            
            # Random delay before posting
            self._wait_random_delay(5, 15)
            
            subreddit = self.reddit.subreddit(self.subreddit_name)
            
            # Post with media if available
            if media_objects:
                # Download first media file
                media_obj = media_objects[0]
                if hasattr(media_obj, 'url'):
                    media_path = self.download_media(media_obj.url)
                    if media_path:
                        try:
                            # Submit image post with text
                            submission = self._handle_reddit_errors(
                                subreddit.submit_image,
                                title=title,
                                image_path=media_path,
                                flair_id=self.flair_haberler
                            )
                            
                            # Add comment with detailed content
                            self._wait_random_delay(5, 15)
                            self._handle_reddit_errors(
                                submission.reply,
                                post_content
                            )
                            
                            # Clean up temp file
                            os.unlink(media_path)
                            
                        except Exception as e:
                            # Clean up temp file on error
                            if media_path and os.path.exists(media_path):
                                os.unlink(media_path)
                            raise e
                    else:
                        # Fallback to text post if media download fails
                        submission = self._handle_reddit_errors(
                            subreddit.submit,
                            title=title,
                            selftext=post_content,
                            flair_id=self.flair_haberler
                        )
                else:
                    # Fallback to text post if no media URL
                    submission = self._handle_reddit_errors(
                        subreddit.submit,
                        title=title,
                        selftext=post_content,
                        flair_id=self.flair_haberler
                    )
            else:
                # Text-only post
                submission = self._handle_reddit_errors(
                    subreddit.submit,
                    title=title,
                    selftext=post_content,
                    flair_id=self.flair_haberler
                )
            
            # Update last post time
            self.last_post_time = time.time()
            
            logger.info(f"Successfully posted to Reddit: {submission.url}")
            return submission
            
        except Exception as e:
            logger.error(f"Error posting to Reddit: {e}")
            return None
    
    def run_once(self):
        """Run one iteration of the bot"""
        logger.info("Starting bot iteration...")
        
        # Get latest tweet with media
        tweet_data = self.get_latest_tweet_with_media()
        
        if not tweet_data:
            logger.info("No new tweets with media to process")
            return False
        
        # Post to Reddit
        submission = self.post_to_reddit(tweet_data)
        
        if submission:
            # Save the tweet ID to avoid reposting
            self.save_last_tweet_id(tweet_data['tweet'].id)
            logger.info(f"Successfully processed tweet {tweet_data['tweet'].id}")
            return True
        else:
            logger.error("Failed to post to Reddit")
            return False
    
    def run_continuous(self, interval_hours=5):
        """Run the bot continuously with specified interval"""
        logger.info(f"Starting continuous bot with {interval_hours} hour intervals")
        
        # Run immediately on first start
        logger.info("Running initial iteration...")
        self.run_once()
        
        # Then run every interval_hours
        interval_seconds = interval_hours * 3600
        
        while True:
            try:
                logger.info(f"Waiting {interval_hours} hours until next iteration...")
                time.sleep(interval_seconds)
                
                logger.info("Starting scheduled iteration...")
                self.run_once()
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                logger.info("Continuing after error...")
                time.sleep(300)  # Wait 5 minutes before retrying

def main():
    """Main function to run the bot"""
    try:
        bot = TwitterRedditBot()
        
        # Run continuously with 5-hour intervals
        bot.run_continuous(interval_hours=5)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
