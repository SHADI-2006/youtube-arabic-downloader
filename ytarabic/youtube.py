"""YouTube download logic: options, link preview, size estimation,
single/playlist download."""

import gc
import re
import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from . import settings
from .config import (
    AUDIO_EXTS, AUDIO_ONLY_KEY, COOKIES_FILE, DOWNLOAD_DIR, HAS_FFMPEG, MAX_RETRIES,
    MIN_VIDEO_BYTES, QUALITY_HEIGHT, QUALITY_OPTIONS, RETRY_WAIT, SUB_EXTS,
    VALID_VIDEO_EXTS, VIDEO_EXTS, get_fmt, quality_label,
)
from .errors import Cancelled
from .utils import (
    classify_url, extract_playlist_id, extract_youtube_id, normalize_playlist_url,
    normalize_youtube_url,
)

LogFn = Callable[[str, str], None]


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


def _quality_label(quality_key: str) -> str:
    return quality_label(quality_key)


_FORMAT_CODE_RE = re.compile(r"\.f\d+(?:-\d+)?$")
_TEMP_STEM_RE   = re.compile(r"\.(?:temp|embedding)$")
_ANSI_RE        = re.compile(r"\x1b\[[0-9;]*m")


def _is_intermediate(f: Path) -> bool:
    return bool(_FORMAT_CODE_RE.search(f.stem) or _TEMP_STEM_RE.search(f.stem))


def _find_media_file(directory: Path, video_id: str, audio_only: bool = False) -> Optional[Path]:
    """Locate the final, merged video (or audio-only) file for video_id in
    directory.

    Excludes yt-dlp's per-format intermediate files (e.g. "Title [id].f617.mp4"
    — the video-only stream before it's merged with audio). Those match the
    same [id]+extension check as the real output, so without this a leftover
    fragment from an earlier interrupted download could get mistaken for the
    finished file and reported as "done" with no audio track.
    """
    if not directory.exists():
        return None
    tag = f"[{video_id}]"
    exts = AUDIO_EXTS if audio_only else VALID_VIDEO_EXTS
    for f in directory.iterdir():
        if tag in f.name and f.suffix.lower() in exts and not _is_intermediate(f):
            return f
    return None


# Kept under its old name — callers outside this module used it.
def _find_video_file(directory: Path, video_id: str) -> Optional[Path]:
    return _find_media_file(directory, video_id)


def clean_error(e: Exception) -> str:
    """yt-dlp's exception text without colour codes / the "ERROR: [youtube] id:" prefix."""
    msg = _ANSI_RE.sub("", str(e)).strip()
    msg = re.sub(r"^ERROR:\s*", "", msg)
    msg = re.sub(r"^\[[^\]]+\]\s*[^:\s]+:\s*", "", msg)
    return msg.splitlines()[0][:300] if msg else "Unknown error"


def _rate_limit_opts() -> dict:
    mb = settings.get("rate_limit_mb")
    return {"ratelimit": int(mb * 1024 * 1024)} if mb and mb > 0 else {}


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
        **_rate_limit_opts(),
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
        **_rate_limit_opts(),
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


def _estimate(info: dict, choice_key: str) -> tuple:
    """(bytes, is_exact) for `info` downloaded at choice_key. (0, False)
    if unknown — never silently the audio-only size for a video quality."""
    duration = info.get("duration") or 0
    formats  = info.get("formats") or []
    audio_fmts = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
    audio_size, audio_exact = 0, True
    if audio_fmts:
        best_a = max(audio_fmts, key=lambda f: _format_bytes(f, duration)[0])
        audio_size, audio_exact = _format_bytes(best_a, duration)
    if choice_key == AUDIO_ONLY_KEY:
        return audio_size, audio_exact

    max_h = QUALITY_HEIGHT.get(choice_key, 1080)
    cands = [f for f in formats
             if f.get("height") and f.get("height") <= max_h and f.get("vcodec") != "none"
             # the download's format string excludes AV1 when merging
             and not (HAS_FFMPEG and str(f.get("vcodec") or "").startswith("av01"))]
    if not cands:
        return 0, False
    best_v = max(cands, key=lambda f: (f.get("height", 0), f.get("tbr") or 0))
    v_size, v_exact = _format_bytes(best_v, duration)
    if not v_size:
        return 0, False
    # A muxed format (video+audio in one stream) already includes the audio
    has_own_audio = best_v.get("acodec") not in (None, "none")
    total = v_size if (has_own_audio or not HAS_FFMPEG) else v_size + audio_size
    return total, v_exact and (audio_exact or has_own_audio)


def sizes_from_info(info: dict) -> dict:
    """Estimated size per quality option from an already-extracted info
    dict. '?' if unknown, prefixed with '~' when estimated from bitrate
    rather than a reported filesize."""
    from .utils import fmt_size
    sizes = {}
    for key in QUALITY_OPTIONS:
        size, exact = _estimate(info, key)
        sizes[key] = (("" if exact else "~") + fmt_size(size)) if size else "?"
    return sizes


def get_all_sizes(url: str) -> dict:
    """sizes_from_info for a URL, in one request."""
    default = {k: "?" for k in QUALITY_OPTIONS}
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        return sizes_from_info(info) if info else default
    except Exception:
        return default


def get_video_size(video_id: str, choice_key: str) -> int:
    """Estimated bytes for one video at given quality (bitrate-based
    estimate if YouTube didn't report a filesize). 0 if unknown."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        return _estimate(info, choice_key)[0] if info else 0
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
#  Link preview — everything the Download tab shows for a pasted URL
# ─────────────────────────────────────────────
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _yt_thumb(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def probe(url: str) -> dict:
    """
    One request's worth of info about a pasted link: what it is (video /
    playlist / Instagram / X), title, channel, duration, thumbnail, size
    per quality, and whether an Arabic subtitle exists on YouTube (human
    or YouTube-translated) or will have to be machine-translated.

    A watch?v=…&list=… link previews the video (with playlist_id set, so
    the UI can offer the whole playlist instead); a /playlist link
    previews the playlist with its full video list for picking items.
    """
    from .subtitles import arabic_langs_from_info

    url = (url or "").strip()
    kind = classify_url(url)
    if kind == "instagram":
        return {"ok": True, "type": "instagram", "kind": kind, "url": url}

    vid, pid = extract_youtube_id(url), extract_playlist_id(url)
    opts = {**base_opts(), "skip_download": True, "extract_flat": "in_playlist"}
    target = url
    if kind == "youtube" and vid:
        target = normalize_youtube_url(url)
        opts["noplaylist"] = True
    elif kind == "youtube" and pid:
        target = normalize_playlist_url(url)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
    except Exception as e:
        return {"ok": False, "kind": kind, "error": clean_error(e)}
    if not info:
        return {"ok": False, "kind": kind, "error": "Nothing found at this link."}

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if kind != "youtube":
            # e.g. an X post with several videos — downloads as one item
            return {"ok": True, "type": "video", "kind": kind, "url": target,
                    "title": info.get("title") or target, "channel": info.get("uploader"),
                    "count": len(entries), "sizes": {}, "subtitles_supported": False}
        videos = [e for e in entries if _YT_ID_RE.match(str(e.get("id") or ""))]
        if entries and not videos:
            return {"ok": False, "kind": kind, "error":
                    "This is a channel page, not a playlist — open the channel's "
                    "\"Videos\" tab and paste that link instead."}
        items = [{"id": e["id"], "title": e.get("title") or e["id"],
                  "duration": e.get("duration")} for e in videos]
        return {
            "ok": True, "type": "playlist", "kind": kind,
            "url": normalize_playlist_url(target) if pid else target,
            "id": info.get("id"),
            "title": info.get("title") or "playlist",
            "channel": info.get("channel") or info.get("uploader"),
            "count": len(items),
            "duration": sum(i["duration"] or 0 for i in items),
            "thumbnail": _yt_thumb(items[0]["id"]) if items else None,
            "entries": items,
        }

    manual, auto = arabic_langs_from_info(info)
    subs  = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    video_id = info.get("id")
    return {
        "ok": True, "type": "video", "kind": kind,
        "url": target,
        "id": video_id,
        "title": info.get("title") or target,
        "channel": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration"),
        "thumbnail": (_yt_thumb(video_id) if kind == "youtube" and video_id else info.get("thumbnail")),
        "view_count": info.get("view_count"),
        "upload_date": info.get("upload_date"),
        "is_live": bool(info.get("is_live")),
        "sizes": sizes_from_info(info),
        "arabic": {"manual": manual, "auto": auto},
        "english": any(k.startswith("en") for k in subs) or any(k.startswith("en") for k in autos),
        "chapters": len(info.get("chapters") or []),
        "playlist_id": pid if (kind == "youtube" and vid) else None,
        "subtitles_supported": kind == "youtube",
    }


# ─────────────────────────────────────────────
#  Cleanup + download-with-retry
# ─────────────────────────────────────────────
def delete_old_versions(directory: Path, video_id: str, log: LogFn = _default_log,
                        audio_only: bool = False):
    """Remove old video+subtitle files for this video_id before re-downloading
    from scratch. Do NOT call this when resuming the same in-progress
    download — it would delete the partial file yt-dlp could otherwise
    continue via HTTP range requests.
    An audio-only download only replaces an older audio-only file — it
    must never delete the video (and its subtitles) you already have."""
    if not directory.exists():
        return
    tag = f"[{video_id}]"
    exts = AUDIO_EXTS if audio_only else VIDEO_EXTS | SUB_EXTS
    for f in list(directory.iterdir()):
        if tag in f.name and f.suffix.lower() in exts:
            try:
                f.unlink()
                log(f"Removed old: {f.name}", "warn")
            except Exception:
                pass


def _wait(seconds: float, should_stop: Optional[Callable[[], bool]]):
    """Sleep between retries, but let Stop through right away instead of
    after the full wait."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if should_stop and should_stop():
            raise Cancelled("stop requested")
        time.sleep(min(0.5, max(0.0, end - time.monotonic())))


def download_with_retry(url: str, opts: dict, output_dir: Path,
                         label: str = "", log: LogFn = _default_log,
                         fetch_subtitles_fn: Optional[Callable] = None,
                         should_stop: Optional[Callable[[], bool]] = None) -> bool:
    """
    Download `url` with retries. If fetch_subtitles_fn is given, it's
    called as fetch_subtitles_fn(url, output_dir) once the video lands
    (kept as an injected callback so this module doesn't need to import
    subtitles.py — avoids a circular import).

    A Stop (Cancelled raised from the progress hook) propagates — but
    only after the half-written file is released. yt-dlp doesn't close
    its output file when a hook aborts the download; the open handle
    survives in the exception's traceback until the garbage collector
    happens to run, and on Windows an open file can't be renamed — so
    Resume then failed with "[WinError 32] being used by another process"
    on every retry.
    """
    try:
        return _download_with_retry(url, opts, output_dir, label, log, fetch_subtitles_fn, should_stop)
    except Cancelled:
        pass
    # Outside the except block, so the exception's traceback is already
    # dropped and collecting it actually closes the file.
    gc.collect()
    raise Cancelled("stop requested")


def _download_with_retry(url, opts, output_dir, label, log, fetch_subtitles_fn, should_stop) -> bool:
    def _is_finished_media(f: Path) -> bool:
        return (f.suffix.lower() in (VALID_VIDEO_EXTS | AUDIO_EXTS)
                and not _is_intermediate(f)
                and f.exists() and f.stat().st_size >= MIN_VIDEO_BYTES)

    for attempt in range(1, MAX_RETRIES + 1):
        before = set(output_dir.iterdir()) if output_dir.exists() else set()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if fetch_subtitles_fn:
                fetch_subtitles_fn(url, output_dir)
            return True

        except Cancelled:
            raise   # user-requested stop — never retried, let the caller handle it

        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["private", "unavailable", "removed", "copyright"]):
                log(f"Skipped — video not available ({clean_error(e)}).", "error")
                return False

            # A post-processing hiccup after the file itself landed fine
            after = set(output_dir.iterdir()) if output_dir.exists() else set()
            if any(_is_finished_media(f) for f in after - before):
                if fetch_subtitles_fn:
                    fetch_subtitles_fn(url, output_dir)
                return True

            if attempt < MAX_RETRIES:
                log(f"Failed ({clean_error(e)}) — attempt {attempt}/{MAX_RETRIES} — "
                    f"retrying in {RETRY_WAIT}s...", "warn")
                _wait(RETRY_WAIT, should_stop)
            else:
                log(f"Failed after {MAX_RETRIES} attempts: {label} ({clean_error(e)})", "error")
                return False
    return False


def embed_downloaded_subtitles(media_file: Path, log: LogFn = _default_log) -> bool:
    """Mux this video's Arabic (and English, if present) subtitle into
    the video file itself."""
    from .library import subtitles_for
    from .media import embed_subtitles
    from .subtitles import is_arabic_subtitle, sub_lang

    subs = subtitles_for(media_file)
    arabic = [s for s in subs if is_arabic_subtitle(s)][:1]
    english = [s for s in subs if (sub_lang(s) or "").lower().startswith("en")][:1]
    tracks = [(s, "ar") for s in arabic] + [(s, "en") for s in english]
    if not tracks:
        log("No subtitles to embed.", "warn")
        return False
    return embed_subtitles(media_file, tracks, log)


# ─────────────────────────────────────────────
#  Single video
# ─────────────────────────────────────────────
def download_single(url: str, quality_key: str, log: LogFn = _default_log,
                     on_video_progress: Optional[Callable] = None,
                     should_stop: Optional[Callable[[], bool]] = None,
                     is_resume: bool = False,
                     subtitle_mode: Optional[str] = None,
                     embed: Optional[bool] = None,
                     on_info: Optional[Callable[[str], None]] = None) -> dict:
    """
    Downloads one video to DOWNLOAD_DIR/single. Always returns a dict —
    {"success": bool, "cancelled": bool, "output_dir": Path|None,
     "title": str, "path": Path|None} — so callers (e.g. history logging)
    have the real title even on failure/cancellation, not just on success.

    Tracked as "pending" (progress_store) from the moment it starts until
    it succeeds, so it shows up in Resume if stopped or interrupted.
    is_resume=True skips the old-file cleanup so yt-dlp can continue a
    partially-downloaded file instead of restarting from 0.
    subtitle_mode / embed default to the user's settings. on_info(title)
    fires once the video's title is known.
    """
    from .progress_store import (
        clear_single_pending, find_completed_video, load_pending, mark_single_pending,
        mark_video_done,
    )
    from .subtitles import fetch_subtitles

    if is_resume:   # continue with the options the download was started with
        saved = load_pending().get(url, {})
        subtitle_mode = subtitle_mode or saved.get("subtitle_mode")
        embed = saved.get("embed") if embed is None else embed
    requested_mode, requested_embed = subtitle_mode, embed
    embed = settings.get("embed_subtitles") if embed is None else embed
    audio_only = quality_key == AUDIO_ONLY_KEY
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
    except Exception as e:
        log(f"Couldn't read video info: {clean_error(e)}", "warn")
    if on_info and title != url:
        on_info(title)

    if vid_id:
        existing = find_completed_video(vid_id, quality_key)
        if existing:
            log(f"Already have \"{title}\" at {q_label} — skipping.", "success")
            return {"success": True, "cancelled": False, "output_dir": Path(existing).parent,
                    "title": title, "path": Path(existing)}

    if not is_resume and vid_id:
        delete_old_versions(output_dir, vid_id, log, audio_only)

    mark_single_pending(url, quality_key, title,
                        subtitle_mode=requested_mode, embed=requested_embed)

    log(f"Downloading \"{title}\" ({q_label})...", "info")
    try:
        ok = download_with_retry(
            url, opts, output_dir, label=url, log=log,
            fetch_subtitles_fn=lambda u, d: fetch_subtitles(u, d, log, should_stop, mode=subtitle_mode),
            should_stop=should_stop,
        )
    except Cancelled:
        log("Stopped by user.", "warn")
        return {"success": False, "cancelled": True, "output_dir": None, "title": title, "path": None}

    if ok:
        clear_single_pending(url)
        media_file = _find_media_file(output_dir, vid_id, audio_only) if vid_id else None
        if vid_id and media_file:
            mark_video_done(vid_id, quality_key, title, str(media_file))
        if embed and media_file and not audio_only:
            embed_downloaded_subtitles(media_file, log)
        log(f"Saved to: {output_dir.resolve()}  ({q_label})", "success")
        return {"success": True, "cancelled": False, "output_dir": output_dir,
                "title": title, "path": media_file}
    return {"success": False, "cancelled": False, "output_dir": None, "title": title, "path": None}


# ─────────────────────────────────────────────
#  Playlist
# ─────────────────────────────────────────────
def read_playlist_info(url: str, log: LogFn = _default_log) -> Optional[dict]:
    """Fetch playlist metadata with retries. None if it couldn't be read."""
    url = normalize_playlist_url(url)
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
                       is_resume: bool = False,
                       selected: Optional[list] = None,
                       subtitle_mode: Optional[str] = None,
                       embed: Optional[bool] = None) -> dict:
    """
    Download every not-yet-completed video in `entries` (from
    read_playlist_info) at `quality_key`. Progress is tracked per
    (video_id, quality_key) so re-running only fetches what's missing.
    `selected` (video ids) limits the run to just those videos; it's
    remembered, so resuming later continues the same selection.
    If should_stop() returns True (checked between videos — a video
    already in flight is cancelled instead, via on_video_progress
    raising Cancelled), the loop ends early and stopped=True is set.
    is_resume=True skips the old-file cleanup for every item in this
    run, so a video that was mid-download when previously stopped can
    have its partial file continued instead of restarted from 0 — a
    no-op for items with no partial file, so it's always safe to set.
    Returns a summary dict: output_dir, total, already_done, done, failed, stopped.
    """
    from .progress_store import (
        find_completed_video, load_progress, mark_done, mark_video_done, set_playlist_meta,
    )
    from .subtitles import fetch_subtitles
    from .utils import safe_dir_name

    url        = normalize_playlist_url(url)
    progress   = load_progress()
    if is_resume:   # continue with the options the run was started with
        saved = progress.get(url, {}).get("options") or {}
        subtitle_mode = subtitle_mode or saved.get("subtitle_mode")
        embed = saved.get("embed") if embed is None else embed
    requested = {"subtitle_mode": subtitle_mode, "embed": embed}
    embed      = settings.get("embed_subtitles") if embed is None else embed
    output_dir = DOWNLOAD_DIR / safe_dir_name(playlist_title)
    output_dir.mkdir(parents=True, exist_ok=True)

    if is_resume and selected is None:
        selected = progress.get(url, {}).get("selected")
    if selected:
        wanted  = set(selected)
        entries = [e for e in entries if e.get("id") in wanted]
    set_playlist_meta(progress, url, playlist_title, len(entries), selected or None, quality_key,
                      requested)

    audio_only = quality_key == AUDIO_ONLY_KEY
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
            delete_old_versions(output_dir, video_id, log, audio_only)
        try:
            success = download_with_retry(
                video_url, opts, output_dir, label=title, log=log,
                fetch_subtitles_fn=lambda u, d: fetch_subtitles(u, d, log, should_stop, mode=subtitle_mode),
                should_stop=should_stop,
            )
        except Cancelled:
            log("Stopped by user.", "warn")
            stopped = True
            break
        if success:
            mark_done(progress, url, done_key, title)
            done_now += 1
            media_file = _find_media_file(output_dir, video_id, audio_only) if video_id else None
            if video_id and media_file:
                mark_video_done(video_id, quality_key, title, str(media_file))
            if embed and media_file and not audio_only:
                embed_downloaded_subtitles(media_file, log)
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
                              should_stop: Optional[Callable[[], bool]] = None,
                              on_item_start: Optional[Callable[[int, int, str], None]] = None) -> dict:
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
        if on_item_start and len(urls) > 1:
            on_item_start(i, len(urls), url)
        log(f"[{i}/{len(urls)}] {url}" if len(urls) > 1 else "Downloading...", "info")
        try:
            if download_with_retry(url, opts, output_dir, label=url, log=log, should_stop=should_stop):
                ok += 1
            else:
                failed.append(url)
        except Cancelled:
            log("Stopped by user.", "warn")
            stopped = True
            break

    return {"output_dir": output_dir, "ok": ok, "total": len(urls), "failed": failed, "stopped": stopped}
