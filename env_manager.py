import os
from dotenv import load_dotenv, set_key

ENV_FILE = '.env'

def load_env():
    """Mevcut .env dosyasını yükle"""
    load_dotenv(ENV_FILE)

def get_env(key, default=None):
    """Belirtilen anahtarın değerini al"""
    return os.getenv(key, default)

def set_env(key, value):
    """Belirtilen anahtarın değerini ayarla ve dosyaya yaz"""
    set_key(ENV_FILE, key, str(value))
    load_dotenv(ENV_FILE)

def get_all_env():
    """Tüm .env değerlerini sözlük olarak döndür"""
    load_env()
    return {
        'TWITTER_QUERY': get_env('TWITTER_QUERY', ''),
        'REDDIT_CLIENT_ID': get_env('REDDIT_CLIENT_ID', ''),
        'REDDIT_CLIENT_SECRET': get_env('REDDIT_CLIENT_SECRET', ''),
        'REDDIT_USERNAME': get_env('REDDIT_USERNAME', ''),
        'REDDIT_PASSWORD': get_env('REDDIT_PASSWORD', ''),
        'TARGET_SUBREDDIT': get_env('TARGET_SUBREDDIT', ''),
        'MAX_TWEETS': get_env('MAX_TWEETS', '100'),
        'UPDATE_INTERVAL': get_env('UPDATE_INTERVAL', '3600')
    }
