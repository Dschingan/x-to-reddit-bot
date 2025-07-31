import os
import time
import logging
import requests
import praw
import re
import json
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, Any

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
        self.target_user_id = "1"  # Twitter user ID 1
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
        """Setup Reddit API client."""
        try:
            self.reddit = praw.Reddit(
                client_id=os.getenv('REDDIT_CLIENT_ID'),
                client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
                username=os.getenv('REDDIT_USERNAME'),
                password=os.getenv('REDDIT_PASSWORD'),
                user_agent=os.getenv('REDDIT_USER_AGENT', 'TwitterRedditBot/1.0')
            )
            logger.info("Reddit API client initialized successfully")
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
    
    def get_latest_tweet(self) -> Optional[Dict[str, Any]]:
        """Fetch the latest tweet from user ID 1 using RapidAPI."""
        try:
            logger.info(f"Fetching latest tweet from user ID: {self.target_user_id}")
            
            headers = {
                'X-RapidAPI-Key': self.twitter_rapidapi_key,
                'X-RapidAPI-Host': self.twitter_rapidapi_host
            }
            
            # Use RapidAPI Twitter service to get user timeline
            params = {
                'screenname': self.target_user_id,
                'count': '1'  # Get only the latest tweet
            }
            
            response = requests.get(
                self.twitter_rapidapi_url,
                headers=headers,
                params=params,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"RapidAPI Twitter error: {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            
            # Check if we got tweets
            if not data or 'timeline' not in data or not data['timeline']:
                logger.warning("No tweets found for user")
                return None
            
            # Get the latest tweet
            latest_tweet = data['timeline'][0]
            tweet_id = str(latest_tweet.get('tweet_id', ''))
            
            # Check if we've already processed this tweet
            last_processed_id = self.get_last_processed_tweet_id()
            if last_processed_id == tweet_id:
                logger.info("Latest tweet already processed")
                return None
            
            # Prepare tweet data
            tweet_data = {
                'id': tweet_id,
                'text': latest_tweet.get('text', ''),
                'created_at': latest_tweet.get('created_at', ''),
                'author_id': self.target_user_id,
                'media': []
            }
            
            # Extract media if available
            if 'media' in latest_tweet and latest_tweet['media']:
                for media in latest_tweet['media']:
                    if media.get('type') in ['photo', 'video']:
                        tweet_data['media'].append({
                            'type': media.get('type'),
                            'url': media.get('media_url_https') or media.get('url'),
                            'preview_url': media.get('media_url_https') or media.get('url')
                        })
            
            logger.info(f"Retrieved tweet: {tweet_data['id']}")
            return tweet_data
            
        except Exception as e:
            logger.error(f"Error fetching latest tweet: {e}")
            return None
    
    def clean_text_for_translation(self, text: str) -> str:
        """Clean tweet text by removing descriptions, symbols, and hashtags."""
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
            
            payload = {
                'text': cleaned_text,
                'source': 'en',
                'target': 'tr'
            }
            
            response = requests.post(
                self.translation_api_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                translated_text = result.get('translatedText', cleaned_text)
                logger.info(f"Translation successful: {len(translated_text)} characters")
                return translated_text
            else:
                logger.error(f"Translation API error: {response.status_code} - {response.text}")
                return cleaned_text
                
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return self.clean_text_for_translation(text)  # Return cleaned original text
    
    def post_to_reddit(self, tweet_data: Dict[str, Any], translated_text: str) -> bool:
        """Post tweet content to Reddit."""
        try:
            subreddit = self.reddit.subreddit(self.subreddit_name)
            
            # Create post title
            title = translated_text[:250] + "..." if len(translated_text) > 250 else translated_text
            if not title.strip():
                title = "Twitter Paylaşımı"
            
            # Create post content
            tweet_url = f"https://twitter.com/i/status/{tweet_data['id']}"
            content = f"**Çeviri:** {translated_text}\n\n**Orijinal Tweet:** {tweet_url}"
            
            # Post to Reddit
            if tweet_data['media']:
                # If there's media, try to post as link (first media item)
                media_url = None
                for media in tweet_data['media']:
                    if media.get('url'):
                        media_url = media['url']
                        break
                    elif media.get('preview_url'):
                        media_url = media['preview_url']
                        break
                
                if media_url:
                    # Post as link with media
                    submission = subreddit.submit(
                        title=title,
                        url=media_url,
                        flair_id=os.getenv('REDDIT_FLAIR_ID')
                    )
                    # Add comment with translation and original link
                    submission.reply(content)
                else:
                    # Post as text if media URL not available
                    submission = subreddit.submit(
                        title=title,
                        selftext=content,
                        flair_id=os.getenv('REDDIT_FLAIR_ID')
                    )
            else:
                # Post as text
                submission = subreddit.submit(
                    title=title,
                    selftext=content,
                    flair_id=os.getenv('REDDIT_FLAIR_ID')
                )
            
            logger.info(f"Successfully posted to Reddit: {submission.url}")
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
