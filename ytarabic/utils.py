"""Small formatting helpers shared across the package."""

import re

from yt_dlp.utils import sanitize_filename

_YT_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})"
)


def normalize_youtube_url(url: str) -> str:
    """Collapse different share-link variants of the same YouTube video
    (youtu.be/ID?si=..., youtube.com/watch?v=ID&si=..., /shorts/ID, ...)
    to one canonical form. Without this, re-pasting a freshly-shared link
    for a video already in progress creates a brand new pending/history
    entry instead of recognizing it as the same download, so Resume never
    finds it and each attempt restarts instead of continuing."""
    m = _YT_ID_RE.search(url)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else url


def fmt_size(b: float) -> str:
    if b <= 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def fmt_time(seconds: float) -> str:
    """Convert seconds → HH:MM:SS or MM:SS."""
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def safe_dir_name(name: str) -> str:
    """Sanitize a playlist/folder name for Windows."""
    name = sanitize_filename(name, restricted=False)
    return name[:60].strip() or "playlist"
