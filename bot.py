import os
import time
import logging
import requests
import praw
import re
import json
import tempfile
import shutil
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, Any
from urllib.parse import urlparse

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
        """Initialize the Twitter to Reddit bot with API credentials."""
        self.setup_twitter_rapidapi()
        self.setup_reddit_api()
        self.setup_translation_api()
        self.target_user_id = os.getenv('TWITTER_USER_ID', '1939708158051500032')  # Twitter user ID from .env
        self.target_username = os.getenv('TWITTER_USERNAME', 'TheBFWire')  # Twitter username from .env
        self.subreddit_name = "bf6_tr"
        self.last_tweet_file = "last_tweet_id_user1.json"
        
    def setup_twitter_rapidapi(self):
        """Setup Twitter RapidAPI client."""
        try:
            self.twitter_rapidapi_key = os.getenv('TWITTER_RAPIDAPI_KEY')
            self.twitter_rapidapi_url = os.getenv('RAPIDAPI_TWITTER_API_URL')
            self.twitter_rapidapi_host = os.getenv('RAPIDAPI_TWITTER_API_HOST')
            
            if not all([self.twitter_rapidapi_key, self.twitter_rapidapi_url, self.twitter_rapidapi_host]):
                raise ValueError("Twitter RapidAPI credentials not found")
            
            logger.info("Twitter RapidAPI client configured successfully")
        except Exception as e:
            logger.error(f"Failed to configure Twitter RapidAPI: {e}")
            raise
    
    def setup_reddit_api(self):
        """Setup Reddit API client with OAuth2 script authentication."""
        try:
            # OAuth2 Script App Authentication
            self.reddit = praw.Reddit(
                client_id=os.getenv('REDDIT_CLIENT_ID'),
                client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
                username=os.getenv('REDDIT_USERNAME'),
                password=os.getenv('REDDIT_PASSWORD'),
                user_agent=os.getenv('REDDIT_USER_AGENT', 'script:twitter-reddit-bot:v1.0 (by /u/BF6_HBRT)'),
                ratelimit_seconds=600  # Allow PRAW to wait up to 10 minutes for rate limits
            )
            
            # Test the connection and log user info
            user = self.reddit.user.me()
            logger.info(f"Reddit API client initialized successfully for user: {user.name}")
            logger.info(f"Using OAuth2 authentication with User-Agent: {self.reddit.config.user_agent}")
            
            # Initialize rate limiting tracking
            self.last_request_time = 0
            self.requests_this_minute = 0
            self.minute_start_time = time.time()
            
        except Exception as e:
            logger.error(f"Failed to initialize Reddit API: {e}")
            raise
    
    def setup_translation_api(self):
        """Setup translation API configuration."""
        self.translation_api_url = os.getenv('TRANSLATION_API_URL')
        self.translation_api_key = os.getenv('TRANSLATION_API_KEY')
        self.translation_api_host = os.getenv('TRANSLATION_API_HOST')
        
        if not all([self.translation_api_url, self.translation_api_key, self.translation_api_host]):
            raise ValueError("Translation API credentials not found")
        
        logger.info("Translation API configured successfully")
    
    def get_last_processed_tweet_id(self) -> Optional[str]:
        """Get the last processed tweet ID from file."""
        try:
            if os.path.exists(self.last_tweet_file):
                with open(self.last_tweet_file, 'r') as f:
                    data = json.load(f)
                    return data.get('last_tweet_id')
        except Exception as e:
            logger.warning(f"Could not read last tweet ID: {e}")
        return None
    
    def save_last_processed_tweet_id(self, tweet_id: str):
        """Save the last processed tweet ID to file."""
        try:
            data = {
                'last_tweet_id': tweet_id,
                'timestamp': datetime.now().isoformat()
            }
            with open(self.last_tweet_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved last processed tweet ID: {tweet_id}")
        except Exception as e:
            logger.error(f"Could not save last tweet ID: {e}")
    
    def check_rate_limit(self):
        """Monitor Reddit API rate limiting to comply with 60 requests/minute limit."""
        current_time = time.time()
        
        # Reset counter if a new minute has started
        if current_time - self.minute_start_time >= 60:
            self.requests_this_minute = 0
            self.minute_start_time = current_time
        
        # Check if we're approaching the limit
        if self.requests_this_minute >= 55:  # Leave buffer of 5 requests
            wait_time = 60 - (current_time - self.minute_start_time)
            if wait_time > 0:
                logger.warning(f"Rate limit approaching. Waiting {wait_time:.1f} seconds...")
                time.sleep(wait_time)
                self.requests_this_minute = 0
                self.minute_start_time = time.time()
        
        self.requests_this_minute += 1
        logger.debug(f"Reddit API requests this minute: {self.requests_this_minute}/60")
    
    def get_latest_tweet(self) -> Optional[Dict[str, Any]]:
        """Fetch the latest tweet from user ID 1 using RapidAPI."""
        try:
            logger.info(f"Fetching latest tweet from user: {self.target_username} (ID: {self.target_user_id})")
            
            headers = {
                'X-RapidAPI-Key': self.twitter_rapidapi_key,
                'X-RapidAPI-Host': self.twitter_rapidapi_host
            }
            
            # Use RapidAPI Twitter service to get user timeline
            # Try different parameter formats based on the API
            # First try with username (screenname)
            params = {
                'screenname': self.target_username,
                'count': 1
            }
            
            logger.info(f"Making request to: {self.twitter_rapidapi_url}")
            logger.info(f"Headers: {headers}")
            logger.info(f"Params: {params}")
            
            
            response = requests.get(
                self.twitter_rapidapi_url,
                headers=headers,
                params=params,
                timeout=30
            )
            
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response headers: {dict(response.headers)}")
            logger.info(f"Response text (first 500 chars): {response.text[:500]}")
            
            if response.status_code != 200:
                logger.error(f"RapidAPI Twitter error: {response.status_code} - {response.text}")
                return None
            
            # Check if response is empty
            if not response.text.strip():
                logger.error("Empty response from RapidAPI")
                return None
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response content: {response.text}")
                return None
            
            logger.info(f"Parsed data structure: {type(data)}")
            if isinstance(data, dict):
                logger.info(f"Data keys: {list(data.keys())}")
            
            # Handle different response formats from RapidAPI
            tweets_data = None
            if isinstance(data, list) and data:
                tweets_data = data
            elif isinstance(data, dict):
                # Try different possible keys
                for key in ['timeline', 'tweets', 'data', 'results']:
                    if key in data and data[key]:
                        tweets_data = data[key]
                        break
                
                # If no tweets found in expected keys, check if data itself is the tweet
                if not tweets_data and 'text' in data:
                    tweets_data = [data]
            
            if not tweets_data:
                logger.warning("No tweets found in response")
                logger.info(f"Full response: {data}")
                return None
            
            # Get the latest tweet
            latest_tweet = tweets_data[0] if isinstance(tweets_data, list) else tweets_data
            
            # Extract tweet ID - try different possible field names
            tweet_id = None
            for id_field in ['tweet_id', 'id', 'id_str', 'tweetId']:
                if id_field in latest_tweet:
                    tweet_id = str(latest_tweet[id_field])
                    break
            
            if not tweet_id:
                logger.error("Could not find tweet ID in response")
                logger.info(f"Tweet data: {latest_tweet}")
                return None
            
            # Check if we've already processed this tweet
            last_processed_id = self.get_last_processed_tweet_id()
            if last_processed_id == tweet_id:
                logger.info("Latest tweet already processed")
                return None
            
            # Extract tweet text - try different possible field names
            tweet_text = ''
            for text_field in ['text', 'full_text', 'tweet_text', 'content']:
                if text_field in latest_tweet:
                    tweet_text = latest_tweet[text_field]
                    break
            
            # Prepare tweet data
            tweet_data = {
                'id': tweet_id,
                'text': tweet_text,
                'created_at': latest_tweet.get('created_at', ''),
                'author_id': self.target_user_id,
                'media': []
            }
            
            # Extract media if available - try different possible field names
            media_sources = []
            for media_field in ['media', 'entities', 'extended_entities']:
                if media_field in latest_tweet:
                    if media_field == 'entities' and 'media' in latest_tweet[media_field]:
                        media_sources = latest_tweet[media_field]['media']
                    elif media_field == 'extended_entities' and 'media' in latest_tweet[media_field]:
                        media_sources = latest_tweet[media_field]['media']
                    elif media_field == 'media':
                        media_sources = latest_tweet[media_field]
                    break
            
            if media_sources:
                for media in media_sources:
                    # Skip if media is not a dictionary
                    if not isinstance(media, dict):
                        continue
                    
                    if media.get('type') in ['photo', 'video']:
                        media_url = media.get('media_url_https') or media.get('media_url') or media.get('url')
                        if media_url:
                            tweet_data['media'].append({
                                'type': media.get('type'),
                                'url': media_url,
                                'preview_url': media_url
                            })
            
            logger.info(f"Successfully retrieved tweet: {tweet_data['id']}")
            logger.info(f"Tweet text: {tweet_data['text'][:100]}...")
            logger.info(f"Media count: {len(tweet_data['media'])}")
            
            return tweet_data
            
        except Exception as e:
            logger.error(f"Error fetching latest tweet: {e}")
            logger.exception("Full exception details:")
            return None
    
    def clean_text_for_translation(self, text: str) -> str:
        """Clean tweet text by removing descriptions, symbols, hashtags, and RT."""
        # Remove RT at the beginning
        text = re.sub(r'^RT\s*@?\w*:?\s*', '', text)
        
        # Remove hashtags
        text = re.sub(r'#\w+', '', text)
        
        # Remove mentions
        text = re.sub(r'@\w+', '', text)
        
        # Remove URLs
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
        
        # Remove extra symbols and emojis (keep basic punctuation)
        text = re.sub(r'[^\w\s.,!?;:()\-"\']', '', text)
        
        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def translate_text(self, text: str) -> str:
        """Translate text using RapidAPI translation service."""
        try:
            # Clean text before translation
            cleaned_text = self.clean_text_for_translation(text)
            
            if not cleaned_text.strip():
                logger.warning("No text to translate after cleaning")
                return text  # Return original if nothing left after cleaning
            
            headers = {
                'X-RapidAPI-Key': self.translation_api_key,
                'X-RapidAPI-Host': self.translation_api_host,
                'Content-Type': 'application/json'
            }
            
            # Correct payload format for translateai.p.rapidapi.com
            payload = {
                'input_text': cleaned_text,  # API expects 'input_text' not 'text'
                'source_language': 'en',     # Use language codes
                'target_language': 'tr'      # Use language codes
            }
            
            response = requests.post(
                self.translation_api_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            logger.info(f"Translation API response status: {response.status_code}")
            logger.info(f"Translation API response: {response.text[:500]}")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Full translation response: {result}")
                
                # For translateai.p.rapidapi.com, the response format is:
                # {"translation": "translated content", "message": "Success", ...}
                translated_text = result.get('translation') or result.get('translatedText') or result.get('translated_text') or result.get('text') or cleaned_text
                
                if translated_text and translated_text != cleaned_text:
                    logger.info(f"Translation successful: {len(translated_text)} characters")
                    logger.info(f"Original: {cleaned_text}")
                    logger.info(f"Translated: {translated_text}")
                    return translated_text
                else:
                    logger.warning(f"Translation API returned same text or empty result. Response: {result}")
                    return cleaned_text
            else:
                logger.error(f"Translation API error: {response.status_code} - {response.text}")
                # If translation fails, still return cleaned text (without RT, hashtags, etc.)
                logger.info(f"Using cleaned original text: {cleaned_text}")
                return cleaned_text
                
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return self.clean_text_for_translation(text)  # Return cleaned original text
    
    def download_media(self, media_url: str) -> Optional[str]:
        """Download media file from URL and return local file path."""
        try:
            # Parse URL to get file extension
            parsed_url = urlparse(media_url)
            path = parsed_url.path
            
            # Get file extension, default to .jpg if not found
            if '.' in path:
                ext = path.split('.')[-1].lower()
                # Ensure it's a valid image/video extension
                if ext not in ['jpg', 'jpeg', 'png', 'gif', 'mp4', 'webm', 'mov']:
                    ext = 'jpg'
            else:
                ext = 'jpg'
            
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}')
            temp_file.close()
            
            # Download the media
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(media_url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            # Save to temporary file
            with open(temp_file.name, 'wb') as f:
                shutil.copyfileobj(response.raw, f)
            
            logger.info(f"Downloaded media to: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Failed to download media from {media_url}: {e}")
            return None
    
    def post_to_reddit(self, tweet_data: Dict[str, Any], translated_text: str) -> bool:
        """Post tweet content to Reddit."""
        try:
            # Check rate limit before making API request
            self.check_rate_limit()
            
            # Get subreddit
            subreddit = self.reddit.subreddit(self.subreddit_name)
            
            # Create post title - only translated text, no extra content
            title = translated_text[:250] + "..." if len(translated_text) > 250 else translated_text
            if not title.strip():
                title = "Twitter Paylaşımı"
            
            # No description content - user wants empty description
            content = ""
            
            # Post to Reddit
            if tweet_data['media']:
                # If there's media, download and upload it
                media_url = None
                for media in tweet_data['media']:
                    if media.get('url'):
                        media_url = media['url']
                        break
                    elif media.get('preview_url'):
                        media_url = media['preview_url']
                        break
                
                if media_url:
                    # Download media file
                    local_media_path = self.download_media(media_url)
                    
                    if local_media_path:
                        try:
                            # Post as image/video upload
                            submission = subreddit.submit_image(
                                title=title,
                                image_path=local_media_path,
                                flair_id=os.getenv('REDDIT_FLAIR_ID')
                            )
                            logger.info(f"Successfully uploaded media to Reddit: {submission.url}")
                        except Exception as upload_error:
                            logger.error(f"Failed to upload media, posting as text instead: {upload_error}")
                            # Fallback to text post if media upload fails
                            submission = subreddit.submit(
                                title=title,
                                selftext=content,  # Empty content
                                flair_id=os.getenv('REDDIT_FLAIR_ID')
                            )
                        finally:
                            # Clean up temporary file
                            try:
                                os.unlink(local_media_path)
                                logger.info(f"Cleaned up temporary file: {local_media_path}")
                            except Exception as cleanup_error:
                                logger.warning(f"Failed to clean up temporary file: {cleanup_error}")
                    else:
                        # If download failed, post as text
                        submission = subreddit.submit(
                            title=title,
                            selftext=content,  # Empty content
                            flair_id=os.getenv('REDDIT_FLAIR_ID')
                        )
                else:
                    # Post as text with empty content
                    submission = subreddit.submit(
                        title=title,
                        selftext=content,  # Empty content
                        flair_id=os.getenv('REDDIT_FLAIR_ID')
                    )
            else:
                # Post as text with empty content
                submission = subreddit.submit(
                    title=title,
                    selftext=content,  # Empty content
                    flair_id=os.getenv('REDDIT_FLAIR_ID')
                )
            
            logger.info(f"Successfully posted to Reddit: {submission.url}")
            logger.info(f"Post title: {title}")
            logger.info(f"Post content: Empty (as requested)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to post to Reddit: {e}")
            return False
    
    def process_latest_tweet(self) -> bool:
        """Process the latest tweet from user ID 1."""
        try:
            # Get latest tweet
            tweet_data = self.get_latest_tweet()
            if not tweet_data:
                logger.info("No new tweet to process")
                return False
            
            logger.info(f"Processing tweet: {tweet_data['id']}")
            
            # Translate tweet text
            translated_text = self.translate_text(tweet_data['text'])
            
            # Post to Reddit
            success = self.post_to_reddit(tweet_data, translated_text)
            
            if success:
                # Save processed tweet ID
                self.save_last_processed_tweet_id(tweet_data['id'])
                logger.info(f"Successfully processed tweet: {tweet_data['id']}")
                return True
            else:
                logger.error(f"Failed to process tweet: {tweet_data['id']}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing tweet: {e}")
            return False
    
    def run_infinite_loop(self):
        """Run the bot in an infinite loop, checking every 4 hours."""
        logger.info("Starting Twitter to Reddit bot - infinite loop mode")
        logger.info(f"Target user ID: {self.target_user_id}")
        logger.info(f"Target subreddit: {self.subreddit_name}")
        logger.info("Checking every 4 hours (14400 seconds)")
        
        # Process immediately on startup
        logger.info("Processing initial tweet...")
        self.process_latest_tweet()
        
        # Main loop
        while True:
            try:
                logger.info("Waiting 4 hours until next check...")
                time.sleep(14400)  # 4 hours = 14400 seconds
                
                logger.info("Starting tweet check cycle")
                self.process_latest_tweet()
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                logger.info("Continuing after error...")
                time.sleep(300)  # Wait 5 minutes before retrying

def main():
    """Main function to run the bot."""
    try:
        bot = TwitterRedditBot()
        bot.run_infinite_loop()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        return 1
    return 0

if __name__ == "__main__":
    exit(main())
