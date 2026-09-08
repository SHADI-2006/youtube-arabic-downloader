"""Small formatting helpers shared across the package."""

from yt_dlp.utils import sanitize_filename


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
