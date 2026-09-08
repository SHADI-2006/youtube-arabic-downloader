"""Twitter/X thread + image extraction."""

import re
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from .config import DOWNLOAD_DIR
from .youtube import base_opts

LogFn = Callable[[str, str], None]


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


def _collect_images(e: dict) -> list:
    """
    Twitter images appear in `formats` (older yt-dlp) or `thumbnails`
    (newer yt-dlp). Collect from both and deduplicate.
    """
    IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}
    seen, imgs = set(), []

    def _add(u: str):
        key = u.split("?")[0]
        if key not in seen and u:
            seen.add(key)
            imgs.append(u)

    for fmt in (e.get("formats") or []):
        ext = (fmt.get("ext") or "").lower()
        fu  = fmt.get("url", "")
        if ext in IMAGE_EXTS and fu:
            _add(fu)

    for thumb in (e.get("thumbnails") or []):
        fu  = thumb.get("url", "")
        ext = fu.split(".")[-1].split("?")[0].lower()
        if ext in IMAGE_EXTS and fu:
            _add(fu)
        elif fu and ("twimg.com" in fu or "pbs.twimg" in fu):
            _add(fu)

    return imgs


def extract_tweet(url: str, log: LogFn = _default_log) -> Optional[Path]:
    """
    Extract tweet/thread text + download images automatically.
    Videos are downloaded separately (the regular video-download path).
    Returns the output folder, or None on failure.
    """
    url = url.replace("x.com/", "twitter.com/")
    log("Fetching tweet info...", "info")

    ydl_opts = {**base_opts(), "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err = str(e)
        log(f"Error: {err}", "error")
        if any(k in err.lower() for k in ("login", "auth", "cookie", "sign in")):
            log("Twitter/X requires its own cookies — export them while logged "
                "into twitter.com and set COOKIES_FILE.", "warn")
        return None
    if not info:
        log("Could not fetch tweet info.", "error")
        return None

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        log(f"Thread — {len(entries)} tweets", "success")
    else:
        entries = [info]
    if not entries:
        log("No content found.", "error")
        return None

    def _parse_entry(e: dict) -> dict:
        if not e.get("description") and not e.get("thumbnails") and e.get("url"):
            try:
                with yt_dlp.YoutubeDL({**ydl_opts, "quiet": True}) as y:
                    fetched = y.extract_info(e["url"], download=False)
                    if fetched:
                        e = fetched
            except Exception:
                pass

        text = (e.get("description") or e.get("title") or "").strip()
        title_raw = (e.get("title") or "").strip()
        if title_raw and text.startswith(title_raw):
            text = text[len(title_raw):].lstrip("\n ").strip()

        return {
            "text":     text,
            "author":   (e.get("uploader_id") or e.get("uploader") or "unknown").lstrip("@"),
            "date":     e.get("upload_date") or "",
            "likes":    e.get("like_count") or 0,
            "retweets": e.get("repost_count") or 0,
            "replies":  e.get("comment_count") or 0,
            "images":   _collect_images(e),
            "has_video": any(
                (f.get("vcodec") or "") not in ("none", "", None)
                and (f.get("ext") or "") not in ("jpg", "jpeg", "png", "webp")
                for f in (e.get("formats") or [])
            ),
        }

    tweets = []
    for entry in entries:
        td = _parse_entry(entry)
        if td["text"] or td["images"]:
            tweets.append(td)
    if not tweets:
        log("No content found.", "error")
        return None

    first       = tweets[0]
    author      = first["author"]
    raw_date    = first["date"]
    upload_date = (f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                   if len(raw_date) == 8 else raw_date or "Unknown")
    is_thread   = len(tweets) > 1

    safe_author = re.sub(r'[\\/:*?"<>|]', "_", author)[:40]
    out_dir     = DOWNLOAD_DIR / f"tweet_{upload_date}_{safe_author}"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_images = sum(len(t["images"]) for t in tweets)
    img_count = 0
    if total_images:
        log(f"Downloading {total_images} image(s)...", "info")
        for ti, t in enumerate(tweets, 1):
            for ii, img_url in enumerate(t["images"], 1):
                ext      = img_url.split(".")[-1].split("?")[0] or "jpg"
                prefix   = f"tweet{ti}_" if is_thread else ""
                img_path = out_dir / f"{prefix}img{ii}.{ext}"
                try:
                    req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        img_path.write_bytes(resp.read())
                    img_count += 1
                except Exception as e:
                    log(f"Image {ii} failed: {e}", "warn")
        log(f"{img_count}/{total_images} images saved", "success")

    tweet_lines = []
    for i, t in enumerate(tweets, 1):
        if is_thread:
            tweet_lines += [f"\n{'─'*50}", f"▶ Tweet {i}/{len(tweets)}", f"{'─'*50}"]
        if t["text"]:
            tweet_lines.append(t["text"])
        meta = []
        if t["likes"]:    meta.append(f"♥ {t['likes']:,}")
        if t["retweets"]: meta.append(f"🔁 {t['retweets']:,}")
        if t["replies"]:  meta.append(f"💬 {t['replies']:,}")
        if meta:
            tweet_lines.append("  " + "  ".join(meta))
        if t["images"]:
            tweet_lines.append(f"  [📷 {len(t['images'])} image(s) saved in folder]")
        if t["has_video"]:
            tweet_lines.append("  [🎥 video — download it separately]")

    full_text  = "\n".join(tweet_lines)
    word_count = len(full_text.split())
    header = (
        f"=== TWITTER / X {'THREAD' if is_thread else 'TWEET'} ===\n"
        f"Author  : @{author}\n"
        f"Date    : {upload_date}\n"
        f"Type    : {'Thread (' + str(len(tweets)) + ' tweets)' if is_thread else 'Single tweet'}\n"
        f"Images  : {total_images}\n"
        f"URL     : {url}\n"
        f"Words   : {word_count:,}\n"
        f"Folder  : {out_dir}\n"
        f"==========================\n\n"
    )
    (out_dir / "transcript.txt").write_text(header + full_text, encoding="utf-8")

    log(f"Done — saved to {out_dir}  (transcript.txt, {word_count:,} words, {total_images} image(s))",
        "success")
    return out_dir
