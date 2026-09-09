"""
Central settings.

Configuration comes from environment variables, and from a local `.env`
file in the project root if one exists (never committed — see .gitignore).
The `.env` file wins only where the variable isn't already set in the
environment, so an explicit shell variable always takes precedence.
"""

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass   # optional — env vars still work without it

DOWNLOAD_DIR  = Path("downloads")
PROGRESS_FILE = DOWNLOAD_DIR / ".progress.json"

MAX_RETRIES = 5     # retries per video on network failure
RETRY_WAIT  = 15    # seconds between retries

# Cookies file exported from the browser (fixes YouTube bot-detection).
# Export with the "Get cookies.txt LOCALLY" extension, then point
# YT_COOKIES_FILE at it (shell variable or .env entry).
COOKIES_FILE = os.environ.get("YT_COOKIES_FILE", "")

# Instagram cookies (optional) — only needed for private accounts or
# reels that show "login required". Export the same way but while
# logged into instagram.com.
INSTAGRAM_COOKIES_FILE = os.environ.get("INSTAGRAM_COOKIES_FILE", "")

# Gemini model used for auto-translation (see subtitles.py for the
# full Arabic-subtitle priority chain)
GEMINI_MODEL      = "gemini-3.6-flash"
GEMINI_RETRIES    = 2    # extra attempts on transient server/connection errors
GEMINI_RETRY_WAIT = 5    # seconds between those retries (never retries a 429)
GEMINI_TIMEOUT    = 30   # seconds — without this, a stalled request hangs forever
                          # (no retry, no way to Stop it — it's not a checkpoint yt-dlp
                          # or our should_stop() callback ever gets a chance to hit)

# ── Runtime constants ──
HAS_FFMPEG = shutil.which("ffmpeg") is not None
UTF8_BOM   = b"\xef\xbb\xbf"
SUB_EXTS   = {".srt", ".vtt", ".ass", ".ssa"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
VALID_VIDEO_EXTS = {".mp4", ".mkv", ".webm"}   # completed video files only
MIN_VIDEO_BYTES  = 100 * 1024                   # 100 KB — ignore empty/partial files
AR_TAGS    = ("ar.", "ar-", ".ar_", "arabic", ".ara.", "ar-orig")

SUBTITLES_EN = ["en"]        # exact match — one file only

QUALITY_OPTIONS = {
    "1": ("2160p  4K",
          "bv*[height<=2160][vcodec!=av01]+ba/b[height<=2160]",
          "b[height<=2160]/b"),
    "2": ("1080p  FHD",
          "bv*[height<=1080][vcodec!=av01]+ba/b[height<=1080]",
          "b[height<=1080]/b"),
    "3": ("720p   HD",
          "bv*[height<=720][vcodec!=av01]+ba/b[height<=720]",
          "b[height<=720]/b"),
    "4": ("480p",
          "bv*[height<=480][vcodec!=av01]+ba/b[height<=480]",
          "b[height<=480]/b"),
    "5": ("360p",
          "bv*[height<=360][vcodec!=av01]+ba/b[height<=360]",
          "b[height<=360]/b"),
    "6": ("Audio only  MP3",
          "bestaudio[ext=m4a]/bestaudio",
          "bestaudio[ext=m4a]/bestaudio"),
}


def get_fmt(key: str) -> str:
    _, with_ff, no_ff = QUALITY_OPTIONS[key]
    return with_ff if HAS_FFMPEG else no_ff
