"""YouTube download logic: options, size estimation, single/playlist download."""

import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from .config import (
    COOKIES_FILE, DOWNLOAD_DIR, HAS_FFMPEG, MAX_RETRIES, MIN_VIDEO_BYTES,
    QUALITY_OPTIONS, RETRY_WAIT, SUB_EXTS, VALID_VIDEO_EXTS, VIDEO_EXTS,
    get_fmt,
)
from .errors import Cancelled

LogFn = Callable[[str, str], None]


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


def base_opts(cookies_path: str = None) -> dict:
    """Common yt-dlp options including cookies."""
    cookies_path = COOKIES_FILE if cookies_path is None else cookies_path
    opts: dict = {"quiet": True, "no_warnings": True}
    if cookies_path:
        p = Path(cookies_path)
        if p.exists():
            opts["cookiefile"] = str(p)
    return opts


def build_ydl_opts(output_dir: Path, fmt: str, audio_only: bool = False,
                    progress_hook: Optional[Callable] = None) -> dict:
    """Options for video download only — no subtitles."""
    opts = base_opts()
    opts.update({
        "format":              fmt,
        "format_sort":         ["res", "tbr", "vbr", "vcodec:vp9"],
        "outtmpl":             str(output_dir / "%(title).180s [%(id)s].%(ext)s"),
        "merge_output_format": None,
        "progress_hooks":      [progress_hook] if progress_hook else [],
        "ignoreerrors":        False,
        "retries":             5,
        "fragment_retries":    5,
        # Subtitles disabled here — downloaded separately to avoid 429 failing video
        "writesubtitles":      False,
        "writeautomaticsub":   False,
        "postprocessors":      [],
    })
    if audio_only and HAS_FFMPEG:
        opts["postprocessors"].append({
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        })
    return opts


def build_subtitle_opts(output_dir: Path, langs: list) -> dict:
    """Options for subtitle-only download — always ignoreerrors=True."""
    opts = base_opts()
    opts.update({
        "skip_download":        True,
        "outtmpl":               str(output_dir / "%(title).180s [%(id)s].%(ext)s"),
        "writesubtitles":       True,
        "writeautomaticsub":    True,
        "subtitleslangs":       langs,
        "subtitlesformat":      "best",
        "ignoreerrors":         True,
        "quiet":                True,
        "no_warnings":          True,
        "sleep_interval_subtitles": 2,
    })
    return opts


def build_instagram_opts(output_dir: Path, progress_hook: Optional[Callable] = None) -> dict:
    """yt-dlp options tuned for Instagram reels/posts."""
    from .config import INSTAGRAM_COOKIES_FILE
    opts = base_opts(INSTAGRAM_COOKIES_FILE)
    fmt  = "bv*+ba/b" if HAS_FFMPEG else "best"
    opts.update({
        "format":            fmt,
        "outtmpl":           str(output_dir / "%(uploader)s_%(id)s.%(ext)s"),
        "restrictfilenames": True,
        "progress_hooks":    [progress_hook] if progress_hook else [],
        "ignoreerrors":      False,
        "retries":           5,
        "fragment_retries":  5,
    })
    return opts


# ─────────────────────────────────────────────
#  Size estimation
# ─────────────────────────────────────────────
def get_all_sizes(url: str) -> dict:
    """Estimated size per quality option, in one request. '?' if unknown."""
    from .utils import fmt_size
    default = {k: "?" for k in QUALITY_OPTIONS}
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return default

        formats = info.get("formats", [])
        audio_fmts = [f for f in formats
                      if f.get("acodec") != "none" and f.get("vcodec") == "none"]
        audio_size = 0
        if audio_fmts:
            best_a = max(audio_fmts,
                         key=lambda f: (f.get("filesize") or f.get("filesize_approx") or 0))
            audio_size = best_a.get("filesize") or best_a.get("filesize_approx") or 0

        heights = {"1": 2160, "2": 1080, "3": 720, "4": 480, "5": 360}
        sizes: dict = {}
        for key, max_h in heights.items():
            cands = [f for f in formats
                     if f.get("height") and f.get("height") <= max_h
                     and f.get("vcodec") != "none"]
            if cands:
                best_v = max(cands, key=lambda f: (f.get("height", 0), f.get("tbr", 0)))
                v_size = best_v.get("filesize") or best_v.get("filesize_approx") or 0
                total  = (v_size + audio_size) if HAS_FFMPEG else v_size
                sizes[key] = fmt_size(total) if total else "?"
            else:
                sizes[key] = "?"
        sizes["6"] = fmt_size(audio_size) if audio_size else "?"
        return sizes
    except Exception:
        return default


def get_video_size(video_id: str, choice_key: str) -> int:
    """Estimated bytes for one video at given quality. 0 if unknown."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return 0
        formats = info.get("formats", [])
        audio_fmts = [f for f in formats
                      if f.get("acodec") != "none" and f.get("vcodec") == "none"]
        audio_size = 0
        if audio_fmts:
            best_a = max(audio_fmts,
                         key=lambda f: (f.get("filesize") or f.get("filesize_approx") or 0))
            audio_size = best_a.get("filesize") or best_a.get("filesize_approx") or 0
        if choice_key == "6":
            return audio_size
        max_h = {"1": 2160, "2": 1080, "3": 720, "4": 480, "5": 360}.get(choice_key, 1080)
        cands = [f for f in formats
                 if f.get("height") and f.get("height") <= max_h
                 and f.get("vcodec") != "none"]
        if not cands:
            return 0
        best_v = max(cands, key=lambda f: (f.get("height", 0), f.get("tbr", 0)))
        v_size = best_v.get("filesize") or best_v.get("filesize_approx") or 0
        return (v_size + audio_size) if HAS_FFMPEG else v_size
    except Exception:
        return 0


def get_playlist_total_size(entries: list, choice_key: str,
                             on_progress: Optional[Callable[[int, int, int], None]] = None) -> str:
    """
    Total estimated size for `entries` at `choice_key` quality.
    on_progress(index, count, total_bytes_so_far) fires per video checked.
    """
    from .utils import fmt_size
    total_bytes = 0
    unknown     = 0
    count       = len(entries)
    for i, entry in enumerate(entries, 1):
        vid = entry.get("id", "")
        if vid:
            sz = get_video_size(vid, choice_key)
            if sz:
                total_bytes += sz
            else:
                unknown += 1
        if on_progress:
            on_progress(i, count, total_bytes)
    result = fmt_size(total_bytes) if total_bytes else "?"
    if unknown:
        result += f"  (+{unknown} unknown)"
    return result


# ─────────────────────────────────────────────
#  Cleanup + download-with-retry
# ─────────────────────────────────────────────
def delete_old_versions(directory: Path, video_id: str, log: LogFn = _default_log):
    """Remove old video+subtitle files for this video_id before re-downloading."""
    if not directory.exists():
        return
    tag = f"[{video_id}]"
    for f in list(directory.iterdir()):
        if tag in f.name and f.suffix in VIDEO_EXTS | SUB_EXTS:
            try:
                f.unlink()
                log(f"Removed old: {f.name}", "warn")
            except Exception:
                pass


def download_with_retry(url: str, opts: dict, output_dir: Path,
                         label: str = "", log: LogFn = _default_log,
                         fetch_subtitles_fn: Optional[Callable] = None) -> bool:
    """
    Download `url` with retries. If fetch_subtitles_fn is given, it's
    called as fetch_subtitles_fn(url, output_dir) once the video lands
    (kept as an injected callback so this module doesn't need to import
    subtitles.py — avoids a circular import).
    """
    for attempt in range(1, MAX_RETRIES + 1):
        before = set(output_dir.iterdir()) if output_dir.exists() else set()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            after = set(output_dir.iterdir()) if output_dir.exists() else set()

            def _is_real_video(f: Path) -> bool:
                return (f.suffix.lower() in VALID_VIDEO_EXTS
                        and f.stat().st_size >= MIN_VIDEO_BYTES)

            if fetch_subtitles_fn:
                fetch_subtitles_fn(url, output_dir)
            return True

        except Cancelled:
            raise   # user-requested stop — never retried, let the caller handle it

        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["private", "unavailable", "removed", "copyright"]):
                log("Skipped — video not available.", "error")
                return False

            after = set(output_dir.iterdir()) if output_dir.exists() else set()
            if any(f.suffix.lower() in VALID_VIDEO_EXTS
                   and f.stat().st_size >= MIN_VIDEO_BYTES
                   for f in after - before):
                if fetch_subtitles_fn:
                    fetch_subtitles_fn(url, output_dir)
                return True

            if attempt < MAX_RETRIES:
                log(f"Failed — attempt {attempt}/{MAX_RETRIES} — retrying in {RETRY_WAIT}s...", "warn")
                time.sleep(RETRY_WAIT)
            else:
                log(f"Failed after {MAX_RETRIES} attempts: {label}", "error")
                return False
    return False


# ─────────────────────────────────────────────
#  Single video
# ─────────────────────────────────────────────
def download_single(url: str, quality_key: str, log: LogFn = _default_log,
                     on_video_progress: Optional[Callable] = None,
                     should_stop: Optional[Callable[[], bool]] = None) -> Optional[dict]:
    """Downloads one video to DOWNLOAD_DIR/single. Returns
    {"output_dir": Path, "title": str} on success, None on failure or
    if stopped by the user."""
    from .subtitles import fetch_subtitles

    audio_only = quality_key == "6"
    fmt        = get_fmt(quality_key)
    output_dir = DOWNLOAD_DIR / "single"
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = build_ydl_opts(output_dir, fmt, audio_only, progress_hook=on_video_progress)

    title = url
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            vid_id = info.get("id", "") if info else ""
            title  = info.get("title", url) if info else url
            if vid_id:
                delete_old_versions(output_dir, vid_id, log)
    except Exception:
        pass

    log("Downloading...", "info")
    try:
        ok = download_with_retry(
            url, opts, output_dir, label=url, log=log,
            fetch_subtitles_fn=lambda u, d: fetch_subtitles(u, d, log, should_stop),
        )
    except Cancelled:
        log("Stopped by user.", "warn")
        return None
    if ok:
        log(f"Saved to: {output_dir.resolve()}", "success")
        return {"output_dir": output_dir, "title": title}
    return None


# ─────────────────────────────────────────────
#  Playlist
# ─────────────────────────────────────────────
def read_playlist_info(url: str, log: LogFn = _default_log) -> Optional[dict]:
    """Fetch playlist metadata with retries. None if it couldn't be read."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            opts = base_opts()
            opts.update({"ignoreerrors": True, "extract_flat": True})
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info and info.get("_type") == "playlist":
                return info
        except Exception:
            pass
        if attempt < MAX_RETRIES:
            log(f"Retrying in {RETRY_WAIT}s... ({attempt}/{MAX_RETRIES})", "warn")
            time.sleep(RETRY_WAIT)
    return None


def download_playlist(url: str, quality_key: str, entries: list,
                       playlist_title: str, log: LogFn = _default_log,
                       on_video_progress: Optional[Callable] = None,
                       on_item_start: Optional[Callable[[int, int, str], None]] = None,
                       should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """
    Download every not-yet-completed video in `entries` (from
    read_playlist_info) at `quality_key`. Progress is tracked per
    (video_id, quality_key) so re-running only fetches what's missing.
    If should_stop() returns True (checked between videos — a video
    already in flight is cancelled instead, via on_video_progress
    raising Cancelled), the loop ends early and stopped=True is set.
    Returns a summary dict: output_dir, total, already_done, done, failed, stopped.
    """
    from .progress_store import load_progress, mark_done
    from .subtitles import fetch_subtitles
    from .utils import safe_dir_name

    progress   = load_progress()
    output_dir = DOWNLOAD_DIR / safe_dir_name(playlist_title)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_only = quality_key == "6"
    fmt        = get_fmt(quality_key)

    done_list = progress.get(url, {}).get("done", [])
    remaining = [e for e in entries if f"{e.get('id')}_{quality_key}" not in done_list]

    opts      = build_ydl_opts(output_dir, fmt, audio_only, progress_hook=on_video_progress)
    failed    = []
    done_now  = 0
    stopped   = False

    for idx, entry in enumerate(remaining, 1):
        if should_stop and should_stop():
            log("Stopped by user.", "warn")
            stopped = True
            break

        video_id  = entry.get("id", "")
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        title     = entry.get("title", f"Video {idx}")
        done_key  = f"{video_id}_{quality_key}"

        if on_item_start:
            on_item_start(idx, len(remaining), title)

        delete_old_versions(output_dir, video_id, log)
        try:
            success = download_with_retry(
                video_url, opts, output_dir, label=title, log=log,
                fetch_subtitles_fn=lambda u, d: fetch_subtitles(u, d, log, should_stop),
            )
        except Cancelled:
            log("Stopped by user.", "warn")
            stopped = True
            break
        if success:
            mark_done(progress, url, done_key, title)
            done_now += 1
        else:
            failed.append(title)

    return {
        "output_dir":    output_dir,
        "total":         len(entries),
        "already_done":  len(entries) - len(remaining),
        "done":          done_now,
        "failed":        failed,
        "stopped":       stopped,
    }


def download_instagram_reels(urls: list, log: LogFn = _default_log,
                              on_video_progress: Optional[Callable] = None,
                              should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """Download one or more Instagram Reels. Returns {output_dir, ok, total, failed, stopped}."""
    output_dir = DOWNLOAD_DIR / "instagram"
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = build_instagram_opts(output_dir, progress_hook=on_video_progress)

    ok, failed, stopped = 0, [], False
    for i, url in enumerate(urls, 1):
        if should_stop and should_stop():
            log("Stopped by user.", "warn")
            stopped = True
            break
        log(f"[{i}/{len(urls)}] {url}" if len(urls) > 1 else "Downloading...", "info")
        try:
            if download_with_retry(url, opts, output_dir, label=url, log=log):
                ok += 1
            else:
                failed.append(url)
        except Cancelled:
            log("Stopped by user.", "warn")
            stopped = True
            break

    return {"output_dir": output_dir, "ok": ok, "total": len(urls), "failed": failed, "stopped": stopped}
