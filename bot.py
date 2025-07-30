import os
import time
import logging
import schedule
import requests
import praw
import tweepy
import re
import subprocess
import tempfile
import json
import random
from datetime import datetime, time as dt_time
from dotenv import load_dotenv
from pathlib import Path
from types import SimpleNamespace

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
        """Initialize the bot with API credentials"""
        logger.info("Initializing Twitter to Reddit Bot")
        
        # Twitter API credentials
        self.twitter_bearer_token = os.getenv('TWITTER_BEARER_TOKEN')
        
        # User configurations
        self.users = {
            'user1': {
                'name': 'TheBFWire',
                'user_id': os.getenv('TWITTER_USER_ID'),
                'use_rapidapi': True,
                'rapidapi_key': os.getenv('TWITTER_RAPIDAPI_KEY'),
                'rapidapi_url': os.getenv('RAPIDAPI_TWITTER_API_URL'),
                'rapidapi_host': os.getenv('RAPIDAPI_TWITTER_API_HOST'),
                'filter_retweets_only': False,  # Process original tweets
                'schedule_minutes': None  # Uses default scheduling
            },
            'user2': {
                'name': 'BF6_TR',
                'user_id': os.getenv('TWITTER_USER_ID_2'),
                'use_rapidapi': False,  # Only Twitter API
                'rapidapi_key': None,
                'rapidapi_url': None,
                'rapidapi_host': None,
                'filter_retweets_only': True,  # Only process retweets
                'schedule_minutes': 432  # 7 hours 12 minutes = 432 minutes
            }
        }
        
        # Reddit API credentials
        self.reddit_client_id = os.getenv('REDDIT_CLIENT_ID')
        self.reddit_client_secret = os.getenv('REDDIT_CLIENT_SECRET')
        self.reddit_username = os.getenv('REDDIT_USERNAME')
        self.reddit_password = os.getenv('REDDIT_PASSWORD')
        self.user_agent = os.getenv('USER_AGENT')
        self.subreddit_name = os.getenv('SUBREDDIT_NAME')
        # Default Reddit flair (optional)
        self.flair_default = os.getenv('FLAIR_HABERLER')
        
        # Translation API credentials
        self.translation_api_key = os.getenv('TRANSLATION_API_KEY')
        self.translation_api_url = os.getenv('TRANSLATION_API_URL')
        self.translation_api_host = os.getenv('TRANSLATION_API_HOST')
        
        # Initialize APIs
        self.setup_twitter_api()
        self.setup_reddit_api()
        
        # Track processed tweets for each user
        self.processed_tweets_files = {
            'user1': 'processed_tweets_user1.json',
            'user2': 'processed_tweets_user2.json'
        }
        self.processed_tweets = {
            'user1': self.load_processed_tweets('user1'),
            'user2': self.load_processed_tweets('user2')
        }
        
        logger.info("Bot initialization completed")
        formatted_users = ", ".join([f"{k}: {v['name']}" for k, v in self.users.items()])
        logger.info(f"Configured users: {formatted_users}")
    
    def setup_twitter_api(self):
        """Setup Twitter API client"""
        try:
            self.twitter_api = tweepy.Client(
                bearer_token=self.twitter_bearer_token,
                wait_on_rate_limit=True
            )
            logger.info("Twitter API client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Twitter API: {e}")
    
    def setup_reddit_api(self):
        """Setup Reddit API client"""
        try:
            # Ensure a proper user-agent; Reddit recommends a descriptive format.
            ua = self.user_agent or f"python:x-to-reddit-bot:v1.0 (by /u/{self.reddit_username})"
            
            self.reddit = praw.Reddit(
                client_id=self.reddit_client_id,
                client_secret=self.reddit_client_secret,
                username=self.reddit_username,
                password=self.reddit_password,
                user_agent=ua,
                ratelimit_seconds=60  # Extra safety buffer on top of PRAW's built-in handling
            )
            logger.info("Reddit API client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Reddit API: {e}")
    
    def load_processed_tweets(self, user_key):
        """Load list of already processed tweets for a specific user"""
        try:
            file_path = self.processed_tweets_files[user_key]
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    return set(json.load(f))
        except Exception as e:
            logger.error(f"Error loading processed tweets for {user_key}: {e}")
        return set()
    
    def save_processed_tweets(self, user_key):
        """Save list of processed tweets for a specific user"""
        try:
            file_path = self.processed_tweets_files[user_key]
            with open(file_path, 'w') as f:
                json.dump(list(self.processed_tweets[user_key]), f)
        except Exception as e:
            logger.error(f"Error saving processed tweets for {user_key}: {e}")
    
    def get_recent_tweets(self, user_key):
        """Get recent tweets from the specified user"""
        user_config = self.users[user_key]
        user_id = user_config['user_id']
        user_name = user_config['name']
        
        try:
            logger.debug(f"Fetching tweets for {user_key}: {user_name} (ID: {user_id})")
            
            # Use Twitter API v2 for user2 or as primary for user1
            if not user_config['use_rapidapi'] or user_key == 'user2':
                logger.debug(f"Using Twitter API v2 for {user_key}")
                
                # Configure tweet exclusions based on user requirements
                exclude_params = []
                if user_config['filter_retweets_only']:
                    # For user2: only get retweets, exclude replies
                    exclude_params = ['replies']
                else:
                    # For user1: exclude retweets and replies (original tweets only)
                    exclude_params = ['retweets', 'replies']
                
                tweets = self.twitter_api.get_users_tweets(
                    id=user_id,
                    max_results=10,
                    exclude=exclude_params,
                    tweet_fields=['created_at', 'attachments', 'author_id', 'text', 'referenced_tweets'],
                    media_fields=['media_key', 'type', 'url', 'preview_image_url'],
                    expansions=['attachments.media_keys', 'referenced_tweets.id']
                )
                
                if not tweets.data:
                    logger.info(f"No tweets found for {user_key}: {user_name}")
                    return [], None
                
                # Filter tweets based on user requirements
                filtered_tweets = []
                for tweet in tweets.data:
                    if str(tweet.id) not in self.processed_tweets[user_key]:
                        # For user2, only process retweets
                        if user_config['filter_retweets_only']:
                            if hasattr(tweet, 'referenced_tweets') and tweet.referenced_tweets:
                                for ref_tweet in tweet.referenced_tweets:
                                    if ref_tweet.type == 'retweeted':
                                        filtered_tweets.append(tweet)
                                        break
                        else:
                            # For user1, process original tweets
                            filtered_tweets.append(tweet)
                
                logger.info(f"Found {len(filtered_tweets)} new tweets to process for {user_key}: {user_name}")
                return filtered_tweets, tweets.includes
            
            # Use RapidAPI for user1 if configured
            else:
                logger.debug(f"Using RapidAPI for {user_key}")
                
                headers = {
                    'X-RapidAPI-Key': user_config['rapidapi_key'],
                    'X-RapidAPI-Host': user_config['rapidapi_host']
                }
                
                # Build RapidAPI request URL dynamically in case the base URL needs parameters
                base_url = user_config['rapidapi_url']
                if '{username}' in base_url:
                    rapidapi_url = base_url.format(username=user_name)
                else:
                    # Append query parameters if not already present
                    join_char = '&' if '?' in base_url else '?'
                    rapidapi_url = f"{base_url}{join_char}username={user_name}&limit=20&include_replies=false"
                
                response = requests.get(rapidapi_url, headers=headers)
                logger.debug(f"RapidAPI request URL: {rapidapi_url}")
                
                if response.status_code == 200:
                    data = response.json()

                    # The structure of the "timeline" key can vary (dict or list). Normalize it.
                    timeline = data.get('timeline', {})
                    # Handle multiple possible RapidAPI response structures
                    if isinstance(timeline, list) and timeline and 'tweet_id' in timeline[0]:
                        # New simple list format (each item is a tweet dict)
                        new_tweets = []
                        for item in timeline:
                            tweet_id = item.get('tweet_id') or item.get('id')
                            if tweet_id and str(tweet_id) not in self.processed_tweets[user_key]:
                                # Convert dict to SimpleNamespace for uniform handling downstream
                                new_tweets.append(SimpleNamespace(**{
                                    'id': tweet_id,
                                    'text': item.get('text', ''),
                                    'created_at': item.get('created_at'),
                                    'media': item.get('media', {}),
                                    'author_id': item.get('author', {}).get('rest_id'),
                                    # store entire original entry for later use if needed
                                    '_raw': item
                                }))
                        logger.info(f"RapidAPI (simple): Found {len(new_tweets)} new tweets to process for {user_key}: {user_name}")
                        if new_tweets:
                            return new_tweets, None
                        else:
                            logger.info(f"RapidAPI (simple) returned no new tweets for {user_key}: {user_name}")
                            return [], None
                    elif isinstance(timeline, dict):
                        instructions = timeline.get('instructions', [])
                    elif isinstance(timeline, list):
                        instructions = timeline  # Already a list of instructions
                    else:
                        instructions = []

                    # Process RapidAPI response structure
                    new_tweets = []
                    for instruction in instructions:
                        if instruction.get('type') == 'TimelineAddEntries':
                            for entry in instruction.get('entries', []):
                                if 'tweet-' in entry.get('entryId', ''):
                                    tweet_data = (
                                        entry.get('content', {})
                                            .get('itemContent', {})
                                            .get('tweet_results', {})
                                            .get('result', {})
                                    )
                                    if tweet_data and str(tweet_data.get('rest_id')) not in self.processed_tweets[user_key]:
                                        new_tweets.append(tweet_data)
                    
                    logger.info(f"RapidAPI: Found {len(new_tweets)} new tweets to process for {user_key}: {user_name}")
                    if new_tweets:
                        return new_tweets, None
                    else:
                        # Fallback to Twitter API v2 if RapidAPI returned no new tweets
                        logger.warning(f"RapidAPI returned no new tweets for {user_key}. Falling back to Twitter API.")
                        # Reuse v2 logic
                        exclude_params = []
                        tweets_v2 = self.twitter_api.get_users_tweets(
                            id=user_id,
                            max_results=10,
                            exclude=exclude_params,
                            tweet_fields=['created_at', 'attachments', 'author_id', 'text', 'referenced_tweets'],
                            media_fields=['media_key', 'type', 'url', 'preview_image_url'],
                            expansions=['attachments.media_keys', 'referenced_tweets.id']
                        )
                        if not tweets_v2.data:
                            logger.info(f"Twitter API fallback: No tweets found for {user_key}: {user_name}")
                            return [], None
                        filtered_tweets_fb = [t for t in tweets_v2.data if str(t.id) not in self.processed_tweets[user_key]]
                        logger.info(f"Twitter API fallback: Found {len(filtered_tweets_fb)} new tweets to process for {user_key}: {user_name}")
                        return filtered_tweets_fb, tweets_v2.includes
                else:
                    logger.error(f"RapidAPI request failed for {user_key}: {response.status_code}")
                    return [], None
                    
        except Exception as e:
            logger.error(f"Error fetching tweets for {user_key}: {user_name}: {e}")
            return [], None
    
    def translate_text(self, text):
        """Translate text from English to Turkish"""
        try:
            logger.debug(f"Translating text: {text[:50]}...")
            
            headers = {
                'X-RapidAPI-Key': self.translation_api_key,
                'X-RapidAPI-Host': self.translation_api_host,
                'Content-Type': 'application/json'
            }
            
            payload = {
                'input_text': text,
                'source': 'en',
                'target': 'tr'
            }
            
            response = requests.post(self.translation_api_url, json=payload, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                translated_text = result.get('translatedText', text)
                logger.debug(f"Translation successful: {translated_text[:50]}...")
                return translated_text
            else:
                logger.error(f"Translation API error: {response.status_code} - {response.text}")
                return text
                
        except Exception as e:
            logger.error(f"Error translating text: {e}")
            return text
    
    def clean_title(self, title):
        """Clean title by removing hashtags, vertical bars, and special symbols"""
        # Remove hashtags
        title = re.sub(r'#\w+', '', title)
        
        # Remove vertical bars
        title = re.sub(r'[|]', '', title)
        
        # Remove other special symbols but keep basic punctuation
        title = re.sub(r'[^\w\s.,!?()-]', '', title)
        
        # Clean up multiple spaces
        title = re.sub(r'\s+', ' ', title).strip()
        
        logger.debug(f"Cleaned title: {title}")
        return title
    
    def download_media(self, media_url, media_type):
        """Download media from URL"""
        try:
            logger.debug(f"Downloading {media_type}: {media_url}")
            
            response = requests.get(media_url, stream=True)
            response.raise_for_status()
            
            # Create temporary file
            suffix = '.jpg' if media_type == 'photo' else '.mp4'
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            
            temp_file.close()
            logger.debug(f"Media downloaded to: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
            return None
    
    def process_video_with_ffmpeg(self, input_path):
        """Process video with FFMpeg for Reddit compatibility"""
        try:
            logger.debug(f"Processing video with FFMpeg: {input_path}")
            
            output_path = input_path.replace('.mp4', '_processed.mp4')
            
            # FFMpeg command for Reddit compatibility
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-movflags', '+faststart',
                '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                '-y',  # Overwrite output file
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.debug(f"Video processed successfully: {output_path}")
                return output_path
            else:
                logger.error(f"FFMpeg error: {result.stderr}")
                return input_path  # Return original if processing fails
                
        except Exception as e:
            logger.error(f"Error processing video: {e}")
            return input_path
    
    def post_to_reddit(self, title, media_paths=None, tweet_author=None):
        """Post content to Reddit"""
        try:
            subreddit = self.reddit.subreddit(self.subreddit_name)
            
            # Create description with tweet author's @username
            description = f"@{tweet_author}" if tweet_author else ""
            
            if media_paths:
                # Post with media
                if len(media_paths) == 1:
                    # Single media file
                    submission = subreddit.submit_image(
                        title=title,
                        image_path=media_paths[0],
                        flair_id=self.flair_default
                    )
                    # Add comment with description if we have tweet author
                    if description:
                        submission.reply(description)
                else:
                    # Multiple media files (gallery)
                    media_list = []
                    for path in media_paths:
                        media_list.append({'image_path': path})
                    
                    submission = subreddit.submit_gallery(
                        title=title,
                        images=media_list
                    )
                    # Add comment with description if we have tweet author
                    if description:
                        submission.reply(description)
            else:
                # Text post with description
                submission = subreddit.submit(
                    title=title,
                    selftext=description,
                    flair_id=self.flair_default
                )
            
            logger.info(f"Successfully posted to Reddit: {submission.url}")
            if tweet_author:
                logger.info(f"Included tweet author: @{tweet_author}")
            return submission
            
        except Exception as e:
            logger.error(f"Error posting to Reddit: {e}")
            return None
    
    def process_tweet(self, tweet, user_key, media_includes=None):
        """Process a single tweet and post to Reddit"""
        try:
            user_config = self.users[user_key]
            user_name = user_config['name']
            
            logger.info(f"Processing tweet ID: {tweet.id} for {user_key}: {user_name}")
            
            # Translate tweet text
            translated_text = self.translate_text(tweet.text)
            
            # Clean the translated title
            clean_title = self.clean_title(translated_text)
            
            # Get tweet author username for Reddit description
            tweet_author = user_name  # Use the configured username
            
            # Process media if available
            media_paths = []
            if hasattr(tweet, 'attachments') and tweet.attachments and media_includes:
                media_keys = tweet.attachments.get('media_keys', [])
                
                for media_key in media_keys:
                    # Find media in includes
                    media = next((m for m in media_includes.get('media', []) if m.media_key == media_key), None)
                    
                    if media:
                        if media.type == 'photo':
                            # Download photo
                            media_path = self.download_media(media.url, 'photo')
                            if media_path:
                                media_paths.append(media_path)
                        
                        elif media.type == 'video':
                            # Download and process video
                            media_path = self.download_media(media.url, 'video')
                            if media_path:
                                processed_path = self.process_video_with_ffmpeg(media_path)
                                media_paths.append(processed_path)
            
            # Post to Reddit with tweet author information
            submission = self.post_to_reddit(clean_title, media_paths if media_paths else None, tweet_author)
            
            if submission:
                # Mark tweet as processed for this user
                self.processed_tweets[user_key].add(str(tweet.id))
                self.save_processed_tweets(user_key)
                
                # Clean up temporary files
                for path in media_paths:
                    try:
                        os.unlink(path)
                        logger.debug(f"Cleaned up temporary file: {path}")
                    except Exception as e:
                        logger.error(f"Error cleaning up file {path}: {e}")
                
                logger.info(f"Successfully processed tweet {tweet.id} for {user_key}: {user_name}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error processing tweet {tweet.id} for {user_key}: {e}")
            return False
    
    def check_and_post_tweets(self, user_key):
        """Main function to check for new tweets and post to Reddit for a specific user"""
        user_config = self.users[user_key]
        user_name = user_config['name']
        
        logger.info(f"Checking for new tweets for {user_key}: {user_name}...")
        
        try:
            tweets, includes = self.get_recent_tweets(user_key)
            
            if not tweets:
                logger.info(f"No new tweets to process for {user_key}: {user_name}")
                return
            
            # Select the most recent tweet (highest Snowflake ID assumed newest)
            latest_tweet = max(tweets, key=lambda t: int(t.id))
            
            # Process only the latest tweet
            success = self.process_tweet(latest_tweet, user_key, includes)
            
            # Mark older tweets as processed so they are not reposted later
            for tw in tweets:
                if tw.id != latest_tweet.id:
                    self.processed_tweets[user_key].add(str(tw.id))
            
            # Persist processed tweet IDs
            self.save_processed_tweets(user_key)
            
            if success:
                # Randomized delay (60–300 s) to mimic human posting and avoid spam detection
                delay = random.uniform(60, 300)
                logger.info(f"Sleeping {delay:.1f} seconds before next check to respect Reddit rate limits")
                time.sleep(delay)
                    
        except Exception as e:
            logger.error(f"Error in check_and_post_tweets for {user_key}: {user_name}: {e}")
    
    def is_peak_hours(self):
        """Check if current time is between 12:00-00:00 (peak hours)"""
        current_time = datetime.now().time()
        peak_start = dt_time(12, 0)  # 12:00
        peak_end = dt_time(23, 59)   # 23:59 (before midnight)
        
        return peak_start <= current_time <= peak_end
    
    def run_scheduler(self):
        """Run the bot with scheduled intervals"""
        logger.info("Starting Twitter to Reddit Bot scheduler")
        
        # Schedule for user1 (TheBFWire)
        # Peak hours (12:00-00:00) - every 25 minutes
        schedule.every(25).minutes.do(self.scheduled_check_peak_user1)
        
        # Off-peak hours (00:01-11:59) - one check daily at 05:00
        schedule.every().day.at("05:00").do(self.scheduled_check_offpeak_user1)
        
        # Schedule for user2 (BF6_TR) - every 7 hours 12 minutes (432 minutes)
        schedule.every(432).minutes.do(self.scheduled_check_user2)
        
        logger.info("Scheduler configured:")
        logger.info("- user1: TheBFWire - Peak hours (12:00-00:00): Every 25 minutes")
        logger.info("- user1: TheBFWire - Off-peak hours (00:01-11:59): Daily at 05:00")
        logger.info("- user2: BF6_TR - Every 7 hours 12 minutes (432 minutes)")
        
        # Run initial checks immediately upon startup
        self.scheduled_check_peak_user1()
        self.scheduled_check_offpeak_user1()
        self.scheduled_check_user2()
        
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                time.sleep(60)
    
    def scheduled_check_peak_user1(self):
        """Scheduled check for user1 during peak hours"""
        if self.is_peak_hours():
            logger.info("Peak hours check - running tweet check for user1: TheBFWire")
            self.check_and_post_tweets('user1')
        else:
            logger.debug("Peak hours check skipped for user1 - not in peak hours")
    
    def scheduled_check_offpeak_user1(self):
        """Scheduled check for user1 during off-peak hours"""
        if not self.is_peak_hours():
            logger.info("Off-peak hours check - running tweet check for user1: TheBFWire")
            self.check_and_post_tweets('user1')
        else:
            logger.debug("Off-peak hours check skipped for user1 - in peak hours")
    
    def scheduled_check_user2(self):
        """Scheduled check for user2 (BF6_TR) - every 7h12m"""
        logger.info("Scheduled check - running tweet check for user2: BF6_TR")
        self.check_and_post_tweets('user2')

def main():
    """Main function to start the bot"""
    try:
        bot = TwitterRedditBot()
        bot.run_scheduler()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
