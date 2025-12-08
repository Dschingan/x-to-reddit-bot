import snscrape.modules.twitter as sntwitter

def scrape_tweets(query, max_results=100):
    """Snscrape kullanarak tweet'leri scrape et"""
    tweets = []
    try:
        for tweet in sntwitter.TwitterSearchScraper(query).get_items():
            if len(tweets) >= max_results:
                break
            tweets.append({
                'id': tweet.id,
                'content': tweet.content,
                'author': tweet.author.username,
                'created_at': tweet.date,
                'likes': tweet.likeCount,
                'retweets': tweet.retweetCount
            })
        return tweets
    except Exception as e:
        print(f"Scraping hatası: {e}")
        return []
