"""Small formatting / URL helpers shared across the package."""

import re
from urllib.parse import parse_qs, urlparse

from yt_dlp.utils import sanitize_filename

_YT_ID_RE      = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_PATH_ID_RE = re.compile(r"^/(?:shorts|embed|live|v|e)/([^/?#]+)")
_YT_HOSTS      = ("youtube.com", "youtube-nocookie.com")


def _parse(url: str):
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    try:
        return urlparse(url)
    except ValueError:
        return None


def _host(parsed) -> str:
    return (parsed.hostname or "").lower() if parsed else ""


def _is_youtube_host(host: str) -> bool:
    return host == "youtu.be" or any(host == h or host.endswith("." + h) for h in _YT_HOSTS)


def extract_youtube_id(url: str) -> "str | None":
    """The 11-char video id from any YouTube URL form — watch?v=,
    youtu.be/, /shorts/, /embed/, /live/, m./music. hosts, and `v`
    anywhere in the query (e.g. watch?app=desktop&v=…) — or None if url
    isn't a recognizable YouTube video link."""
    p = _parse(url)
    host = _host(p)
    if not _is_youtube_host(host):
        return None
    if host == "youtu.be":
        candidate = p.path.lstrip("/").split("/")[0]
    elif p.path.rstrip("/") == "/watch":
        candidate = parse_qs(p.query).get("v", [""])[0]
    else:
        m = _YT_PATH_ID_RE.match(p.path)
        candidate = m.group(1) if m else ""
    return candidate if _YT_ID_RE.match(candidate) else None


def extract_playlist_id(url: str) -> "str | None":
    """The `list=` id of a YouTube playlist link (also present on a
    watch?v=…&list=… link to a video inside a playlist), or None."""
    p = _parse(url)
    if not _is_youtube_host(_host(p)):
        return None
    pid = parse_qs(p.query).get("list", [""])[0].strip()
    return pid if re.match(r"^[A-Za-z0-9_-]{2,64}$", pid) else None


def normalize_youtube_url(url: str) -> str:
    """Collapse different share-link variants of the same YouTube video
    (youtu.be/ID?si=..., youtube.com/watch?v=ID&si=..., /shorts/ID, ...)
    to one canonical form. Without this, re-pasting a freshly-shared link
    for a video already in progress creates a brand new pending/history
    entry instead of recognizing it as the same download, so Resume never
    finds it and each attempt restarts instead of continuing."""
    vid = extract_youtube_id(url)
    return f"https://www.youtube.com/watch?v={vid}" if vid else url.strip()


def normalize_playlist_url(url: str) -> str:
    """Same idea for playlists: the `si=` tracking parameter YouTube adds
    to every share link made the same playlist look like a different one
    each time it was shared, splitting its resume progress in two."""
    pid = extract_playlist_id(url)
    return f"https://www.youtube.com/playlist?list={pid}" if pid else url.strip()


def is_youtube_url(url: str) -> bool:
    return _is_youtube_host(_host(_parse(url)))


def classify_url(url: str) -> str:
    """'youtube' | 'instagram' | 'x' | 'other' — which downloader a pasted
    link belongs to."""
    host = _host(_parse(url))
    if _is_youtube_host(host):
        return "youtube"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "instagram"
    if host in ("x.com", "twitter.com", "mobile.twitter.com", "www.x.com", "www.twitter.com"):
        return "x"
    return "other"


def fmt_size(b: float) -> str:
    if not b or b <= 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}" if unit in ("B", "KB") else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def fmt_time(seconds: float) -> str:
    """Convert seconds → HH:MM:SS or MM:SS."""
    s = int(seconds or 0)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def safe_dir_name(name: str) -> str:
    """Sanitize a playlist/folder name for Windows."""
    name = sanitize_filename(name, restricted=False)
    return name[:60].strip() or "playlist"


def safe_file_stem(name: str, limit: int = 60) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name or "")[:limit].strip() or "untitled"
