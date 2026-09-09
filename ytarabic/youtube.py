"""YouTube download logic: options, size estimation, single/playlist download."""

import re
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


def _quality_label(quality_key: str) -> str:
    return QUALITY_OPTIONS.get(quality_key, (quality_key,))[0]


_FORMAT_CODE_RE = re.compile(r"\.f\d+$")


def _find_video_file(directory: Path, video_id: str) -> Optional[Path]:
    """Locate the final, merged video file for video_id in directory.

    Excludes yt-dlp's per-format intermediate files (e.g. "Title [id].f617.mp4"
    — the video-only stream before it's merged with audio). Those match the
    same [id]+extension check as the real output, so without this a leftover
    fragment from an earlier interrupted download could get mistaken for the
    finished file and reported as "done" with no audio track.
    """
    if not directory.exists():
        return None
    tag = f"[{video_id}]"
    for f in directory.iterdir():
        if tag in f.name and f.suffix.lower() in VALID_VIDEO_EXTS and not _FORMAT_CODE_RE.search(f.stem):
            return f
    return None


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
def _format_bytes(f: dict, duration: float) -> tuple:
    """
    (bytes, is_exact) for one format. YouTube frequently omits filesize
    for high-bitrate DASH streams (seen even on 1080p VP9) even though
    tbr (bitrate) is still reported — in that case estimate from
    tbr * duration instead of treating the format as sizeless.
    """
    size = f.get("filesize") or f.get("filesize_approx") or 0
    if size:
        return size, True
    tbr = f.get("tbr")
    if tbr and duration:
        return int(tbr * 1000 / 8 * duration), False
    return 0, False


def get_all_sizes(url: str) -> dict:
    """Estimated size per quality option, in one request. '?' if unknown,
    prefixed with '~' when estimated from bitrate rather than a reported filesize."""
    from .utils import fmt_size
    default = {k: "?" for k in QUALITY_OPTIONS}
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return default

        duration = info.get("duration") or 0
        formats  = info.get("formats", [])
        audio_fmts = [f for f in formats
                      if f.get("acodec") != "none" and f.get("vcodec") == "none"]
        audio_size, audio_exact = 0, True
        if audio_fmts:
            best_a = max(audio_fmts, key=lambda f: _format_bytes(f, duration)[0])
            audio_size, audio_exact = _format_bytes(best_a, duration)

        heights = {"1": 2160, "2": 1080, "3": 720, "4": 480, "5": 360}
        sizes: dict = {}
        for key, max_h in heights.items():
            cands = [f for f in formats
                     if f.get("height") and f.get("height") <= max_h
                     and f.get("vcodec") != "none"]
            if cands:
                best_v = max(cands, key=lambda f: (f.get("height", 0), f.get("tbr", 0)))
                v_size, v_exact = _format_bytes(best_v, duration)
                if v_size:
                    total = (v_size + audio_size) if HAS_FFMPEG else v_size
                    prefix = "" if (v_exact and audio_exact) else "~"
                    sizes[key] = prefix + fmt_size(total)
                else:
                    sizes[key] = "?"
            else:
                sizes[key] = "?"
        sizes["6"] = ("" if audio_exact else "~") + fmt_size(audio_size) if audio_size else "?"
        return sizes
    except Exception:
        return default


def get_video_size(video_id: str, choice_key: str) -> int:
    """Estimated bytes for one video at given quality (bitrate-based
    estimate if YouTube didn't report a filesize). 0 if unknown."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return 0
        duration = info.get("duration") or 0
        formats  = info.get("formats", [])
        audio_fmts = [f for f in formats
                      if f.get("acodec") != "none" and f.get("vcodec") == "none"]
        audio_size = 0
        if audio_fmts:
            best_a = max(audio_fmts, key=lambda f: _format_bytes(f, duration)[0])
            audio_size = _format_bytes(best_a, duration)[0]
        if choice_key == "6":
            return audio_size
        max_h = {"1": 2160, "2": 1080, "3": 720, "4": 480, "5": 360}.get(choice_key, 1080)
        cands = [f for f in formats
                 if f.get("height") and f.get("height") <= max_h
                 and f.get("vcodec") != "none"]
        if not cands:
            return 0
        best_v = max(cands, key=lambda f: (f.get("height", 0), f.get("tbr", 0)))
        v_size = _format_bytes(best_v, duration)[0]
        if not v_size:
            return 0   # unknown video size — don't silently return audio-only size
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
    """Remove old video+subtitle files for this video_id before re-downloading
    from scratch. Do NOT call this when resuming the same in-progress
    download — it would delete the partial file yt-dlp could otherwise
    continue via HTTP range requests."""
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
                     should_stop: Optional[Callable[[], bool]] = None,
                     is_resume: bool = False) -> dict:
    """
    Downloads one video to DOWNLOAD_DIR/single. Always returns a dict —
    {"success": bool, "cancelled": bool, "output_dir": Path|None, "title": str}
    — so callers (e.g. history logging) have the real title even on
    failure/cancellation, not just on success.

    Tracked as "pending" (progress_store) from the moment it starts until
    it succeeds, so it shows up in Resume if stopped or interrupted.
    is_resume=True skips the old-file cleanup so yt-dlp can continue a
    partially-downloaded file instead of restarting from 0.
    """
    from .progress_store import (
        clear_single_pending, find_completed_video, mark_single_pending, mark_video_done,
    )
    from .subtitles import fetch_subtitles

    audio_only = quality_key == "6"
    fmt        = get_fmt(quality_key)
    q_label    = _quality_label(quality_key)
    output_dir = DOWNLOAD_DIR / "single"
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = build_ydl_opts(output_dir, fmt, audio_only, progress_hook=on_video_progress)

    title, vid_id = url, ""
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            vid_id = info.get("id", "") if info else ""
            title  = info.get("title", url) if info else url
    except Exception:
        pass

    if vid_id:
        existing = find_completed_video(vid_id, quality_key)
        if existing:
            log(f"Already have \"{title}\" at {q_label} — skipping.", "success")
            return {"success": True, "cancelled": False, "output_dir": Path(existing).parent, "title": title}

    if not is_resume and vid_id:
        delete_old_versions(output_dir, vid_id, log)

    mark_single_pending(url, quality_key, title)

    log(f"Downloading ({q_label})...", "info")
    try:
        ok = download_with_retry(
            url, opts, output_dir, label=url, log=log,
            fetch_subtitles_fn=lambda u, d: fetch_subtitles(u, d, log, should_stop),
        )
    except Cancelled:
        log("Stopped by user.", "warn")
        return {"success": False, "cancelled": True, "output_dir": None, "title": title}

    if ok:
        clear_single_pending(url)
        log(f"Saved to: {output_dir.resolve()}  ({q_label})", "success")
        video_file = _find_video_file(output_dir, vid_id) if vid_id else None
        if vid_id and video_file:
            mark_video_done(vid_id, quality_key, title, str(video_file))
        return {"success": True, "cancelled": False, "output_dir": output_dir, "title": title}
    return {"success": False, "cancelled": False, "output_dir": None, "title": title}


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
                       should_stop: Optional[Callable[[], bool]] = None,
                       is_resume: bool = False) -> dict:
    """
    Download every not-yet-completed video in `entries` (from
    read_playlist_info) at `quality_key`. Progress is tracked per
    (video_id, quality_key) so re-running only fetches what's missing.
    If should_stop() returns True (checked between videos — a video
    already in flight is cancelled instead, via on_video_progress
    raising Cancelled), the loop ends early and stopped=True is set.
    is_resume=True skips the old-file cleanup for every item in this
    run, so a video that was mid-download when previously stopped can
    have its partial file continued instead of restarted from 0 — a
    no-op for items with no partial file, so it's always safe to set.
    Returns a summary dict: output_dir, total, already_done, done, failed, stopped.
    """
    from .progress_store import find_completed_video, load_progress, mark_done, mark_video_done
    from .subtitles import fetch_subtitles
    from .utils import safe_dir_name

    progress   = load_progress()
    output_dir = DOWNLOAD_DIR / safe_dir_name(playlist_title)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_only = quality_key == "6"
    fmt        = get_fmt(quality_key)
    q_label    = _quality_label(quality_key)

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

        # Already downloaded at this exact quality — standalone or in
        # another playlist — no need to fetch it again over the network.
        existing = find_completed_video(video_id, quality_key) if video_id else None
        if existing:
            log(f"Already have \"{title}\" at {q_label} (in {Path(existing).parent}) — skipping.", "success")
            mark_done(progress, url, done_key, title)
            done_now += 1
            continue

        if not is_resume:
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
            video_file = _find_video_file(output_dir, video_id) if video_id else None
            if video_id and video_file:
                mark_video_done(video_id, quality_key, title, str(video_file))
        else:
            failed.append(title)

    return {
        "output_dir":    output_dir,
        "total":         len(entries),
        "already_done":  len(entries) - len(remaining),
        "done":          done_now,
        "failed":        failed,
        "stopped":       stopped,
        "quality_label": q_label,
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
