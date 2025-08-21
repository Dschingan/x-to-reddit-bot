import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

# bot.py’den ihtiyacımız olan fonksiyonlar
from bot import (
    get_latest_tweets_with_retweet_check,
    clean_tweet_text,
    get_media_urls_from_tweet_data,
    download_multiple_images,
    download_media,
    convert_video_to_reddit_format,
    smart_split_title,
    select_flair_with_ai,
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

def is_image_url(u: str) -> bool:
    if not u:
        return False
    l = u.lower()
    return any(x in l for x in [".jpg", ".jpeg", ".png", ".webp", ".gif", "pbs.twimg.com/media", "format=jpg", "format=png", "name=large"])

def is_video_url(u: str) -> bool:
    if not u:
        return False
    l = u.lower()
    return (".mp4" in l) or ("video.twimg.com" in l) or ("format=mp4" in l)

def main():
    ap = argparse.ArgumentParser(description="Dry-run test: Reddit'e göndermeden tüm akışı dene")
    ap.add_argument("--count", type=int, default=2, help="Kaç tweet işlensin (varsayılan 2)")
    ap.add_argument("--convert-video", action="store_true", help="İndirilen videoyu Reddit uyumlu formata dönüştür")
    args = ap.parse_args()

    print("[TEST] Tweetler çekiliyor...")
    tweets = get_latest_tweets_with_retweet_check(count=args.count)
    if not tweets:
        print("[TEST] Tweet bulunamadı veya çekilemedi.")
        sys.exit(0)

    for idx, tw in enumerate(tweets, start=1):
        print("\n" + "=" * 70)
        print(f"[TEST] Tweet {idx}/{len(tweets)}")
        tid = str(tw.get("id") or tw.get("tweet_id") or "")
        text_raw = tw.get("text", "") or ""
        text_clean = clean_tweet_text(text_raw)
        url = tw.get("url") or (f"https://x.com/i/web/status/{tid}" if tid else "")

        # Başlık ve AI flair
        title_base = text_clean if text_clean else ("BF6 Haber" if url else "BF6")
        title, remainder = smart_split_title(title_base, max_len=300)
        flair_id = select_flair_with_ai(title, original_tweet_text=text_raw)

        print(f"[TEST] Tweet ID: {tid}")
        print(f"[TEST] URL: {url}")
        print(f"[TEST] Başlık: {title}")
        if remainder:
            print(f"[TEST] Kalan metin: {remainder[:120]}...")
        print(f"[TEST] AI Flair ID: {flair_id}")

        # Medya URL’leri
        media_urls = get_media_urls_from_tweet_data(tw)
        print(f"[TEST] Medya URL sayısı: {len(media_urls)}")

        # Medyayı indir
        image_urls = [u for u in media_urls if is_image_url(u)]
        video_urls = [u for u in media_urls if is_video_url(u)]

        downloaded_files = []

        # Çoklu resim indir
        if image_urls:
            print(f"[TEST] {len(image_urls)} resim indiriliyor...")
            downloaded_images = download_multiple_images(image_urls, tid or "noid")
            downloaded_files.extend(downloaded_images)

        # Videolar indir
        for v_idx, vurl in enumerate(video_urls, start=1):
            vname = f"video_{tid}_{v_idx}.mp4" if tid else f"video_{v_idx}.mp4"
            vpath = str(DOWNLOAD_DIR / vname)
            print(f"[TEST] Video indiriliyor: {vurl}")
            vfile = download_media(vurl, vpath)
            if vfile:
                downloaded_files.append(vfile)
                if args.convert_video:
                    out_path = str(DOWNLOAD_DIR / f"video_{tid}_{v_idx}_reddit.mp4")
                    print(f"[TEST] Video dönüştürülüyor: {vfile} -> {out_path}")
                    converted = convert_video_to_reddit_format(vfile, out_path)
                    if converted:
                        print(f"[TEST] Dönüştürme başarılı: {converted}")
                    else:
                        print("[TEST] Dönüştürme başarısız")

        # Özet
        images = [f for f in downloaded_files if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))]
        videos = [f for f in downloaded_files if f.lower().endswith(".mp4")]
        print(f"[TEST] İndirilenler -> Resim: {len(images)}, Video: {len(videos)}")
        for f in downloaded_files:
            print(f" - {f}")

        print("[TEST] Reddit gönderimi ATLANDI (dry-run).")

    print("\n[TEST] Dry-run bitti. Hata yoksa prod’a geçebilirsiniz.")

if __name__ == "__main__":
    main()
