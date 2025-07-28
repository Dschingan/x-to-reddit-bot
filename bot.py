# ... önceki import ve değişkenler aynı ...

BF6_TR_USER_ID = os.getenv("BF6_TR_USER_ID")  # .env dosyasına ekle

# Bu fonksiyon parametreli: verilen kullanıcı için tweetleri getirir
def get_latest_tweets_with_retry(user_id):
    client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
    while True:
        try:
            tweets = client.get_users_tweets(
                id=user_id,
                max_results=5,
                expansions=[
                    "attachments.media_keys",
                    "referenced_tweets.id",
                    "referenced_tweets.id.attachments.media_keys"
                ],
                tweet_fields=[
                    "attachments", "created_at", "text",
                    "in_reply_to_user_id", "referenced_tweets", "author_id"
                ],
                media_fields=[
                    "url", "type", "variants", "preview_image_url"
                ]
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
    referenced_tweets = {t.id: t for t in tweets.includes.get("tweets", [])}

    return tweets.data, media, referenced_tweets

# USER_ID için mevcut fonksiyonun benzeri:
def parse_tweet_data(tweet, media, referenced_tweets):
    if tweet.in_reply_to_user_id is not None:
        return None  # reply değil sadece

    tweet_info = {
        "id": str(tweet.id),
        "text": tweet.text,
        "media_urls": [],
        "video_url": None,
        "quoted_media_url": None
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

    if tweet.referenced_tweets:
        for ref in tweet.referenced_tweets:
            if ref.type == "quoted":
                quoted = referenced_tweets.get(ref.id)
                if quoted and quoted.attachments and "media_keys" in quoted.attachments:
                    for key in quoted.attachments["media_keys"]:
                        m = media.get(key)
                        if m:
                            if m.type == "photo":
                                tweet_info["quoted_media_url"] = m.url
                                break
                            elif m.type in ["video", "animated_gif"]:
                                variants = m.variants if hasattr(m, "variants") else m["variants"]
                                best = sorted(variants, key=lambda x: x.get("bit_rate", 0), reverse=True)
                                for variant in best:
                                    if "url" in variant:
                                        tweet_info["quoted_media_url"] = variant["url"]
                                        break
    return tweet_info

# BF6_TR kullanıcı için sadece REPOST yani referenced_tweets varsa ve type retweet veya quoted olan tweetleri çek
def get_latest_reposts_for_bf6tr():
    user_id = BF6_TR_USER_ID
    tweets_data, media, referenced_tweets = get_latest_tweets_with_retry(user_id)
    if not tweets_data:
        return None

    for tweet in tweets_data:
        # repost (retweet veya alıntı) olup olmadığını kontrol et
        if tweet.referenced_tweets:
            for ref in tweet.referenced_tweets:
                if ref.type in ["retweeted", "quoted"]:  # retweet ya da quoted tweet var demek
                    # repost tespit edildi, medya kontrolü ve diğer işlemler
                    tweet_info = {
                        "id": str(tweet.id),
                        "text": tweet.text,
                        "media_urls": [],
                        "video_url": None,
                        "quoted_media_url": None
                    }

                    # BF6_TR repostun kendi medya veya quoted medya alalım
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

                    # Eğer quoted medya varsa
                    if tweet.referenced_tweets:
                        for ref2 in tweet.referenced_tweets:
                            if ref2.type == "quoted":
                                quoted = referenced_tweets.get(ref2.id)
                                if quoted and quoted.attachments and "media_keys" in quoted.attachments:
                                    for key in quoted.attachments["media_keys"]:
                                        m = media.get(key)
                                        if m:
                                            if m.type == "photo":
                                                tweet_info["quoted_media_url"] = m.url
                                                break
                                            elif m.type in ["video", "animated_gif"]:
                                                variants = m.variants if hasattr(m, "variants") else m["variants"]
                                                best = sorted(variants, key=lambda x: x.get("bit_rate", 0), reverse=True)
                                                for variant in best:
                                                    if "url" in variant:
                                                        tweet_info["quoted_media_url"] = variant["url"]
                                                        break
                    return tweet_info
    return None

def get_last_tweet_id_for_user(user_id):
    try:
        with open(f"last_tweet_id_{user_id}.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

def save_last_tweet_id_for_user(user_id, tweet_id):
    with open(f"last_tweet_id_{user_id}.txt", "w") as f:
        f.write(str(tweet_id))

def main():
    # 1) Ana kullanıcı (TWITTER_USER_ID) tweetleri (reply olmayan)
    last_id_main = get_last_tweet_id_for_user(TWITTER_USER_ID)
    tweets_data, media, referenced_tweets = get_latest_tweets_with_retry(TWITTER_USER_ID)
    tweet_main = None
    if tweets_data:
        for tw in tweets_data:
            tweet_info = parse_tweet_data(tw, media, referenced_tweets)
            if tweet_info and tweet_info["id"] != last_id_main:
                tweet_main = tweet_info
                break

    if tweet_main:
        print(f"Ana kullanıcı için yeni tweet bulundu: {tweet_main['text']}")
        raw_title = tweet_main["text"]
        cleaned_title = clean_title(raw_title)
        translated_title = translate_to_turkish(cleaned_title)
        media_file = None
        selftext_content = ""

        if tweet_main["video_url"]:
            print("Video indiriliyor...")
            media_file = download_file(tweet_main["video_url"], "video.mp4")
            if media_file:
                print("Video yeniden kodlanıyor...")
                reencode_video("video.mp4", "video_final.mp4")
                media_file = "video_final.mp4"
        elif tweet_main["media_urls"]:
            print("Fotoğraf indiriliyor...")
            media_file = download_file(tweet_main["media_urls"][0], "image.jpg")
        elif tweet_main.get("quoted_media_url"):
            print("Alıntılanan tweet'ten medya indiriliyor...")
            media_file = download_file(tweet_main["quoted_media_url"], "quoted_media.jpg")
            if raw_title.strip():
                selftext_content = translated_title

        print("Reddit'e gönderiliyor...")
        post_to_reddit(title=translated_title, media_path=media_file, selftext=selftext_content)

        save_last_tweet_id_for_user(TWITTER_USER_ID, tweet_main["id"])
    else:
        print("Ana kullanıcı için yeni tweet yok.")

    # 2) BF6_TR kullanıcısı için SADECE repostlar (retweet veya alıntı tweet)
    last_id_bf6 = get_last_tweet_id_for_user(BF6_TR_USER_ID)
    tweet_repost = get_latest_reposts_for_bf6tr()

    if tweet_repost and tweet_repost["id"] != last_id_bf6:
        print(f"BF6_TR kullanıcısı için yeni repost bulundu: {tweet_repost['text']}")
        raw_title = tweet_repost["text"]
        cleaned_title = clean_title(raw_title)
        translated_title = translate_to_turkish(cleaned_title)
        media_file = None
        selftext_content = ""

        if tweet_repost["video_url"]:
            print("Video indiriliyor...")
            media_file = download_file(tweet_repost["video_url"], "bf6_video.mp4")
            if media_file:
                print("Video yeniden kodlanıyor...")
                reencode_video("bf6_video.mp4", "bf6_video_final.mp4")
                media_file = "bf6_video_final.mp4"
        elif tweet_repost["media_urls"]:
            print("Fotoğraf indiriliyor...")
            media_file = download_file(tweet_repost["media_urls"][0], "bf6_image.jpg")
        elif tweet_repost.get("quoted_media_url"):
            print("Alıntılanan tweet'ten medya indiriliyor...")
            media_file = download_file(tweet_repost["quoted_media_url"], "bf6_quoted_media.jpg")
            if raw_title.strip():
                selftext_content = translated_title

        print("Reddit'e gönderiliyor...")
        post_to_reddit(title=translated_title, media_path=media_file, selftext=selftext_content)

        save_last_tweet_id_for_user(BF6_TR_USER_ID, tweet_repost["id"])
    else:
        print("BF6_TR kullanıcısı için yeni repost yok.")

if __name__ == "__main__":
    print("Program başladı.")
    while True:
        main()
        time.sleep(60)  # Döngüde uygun bekleme süresi
