"""Central settings — edit these to match your setup."""

import shutil
from pathlib import Path

DOWNLOAD_DIR  = Path("downloads")
PROGRESS_FILE = DOWNLOAD_DIR / ".progress.json"

MAX_RETRIES = 5     # retries per video on network failure
RETRY_WAIT  = 15    # seconds between retries

# Cookies file exported from browser (fixes bot detection).
# Use extension "Get cookies.txt LOCALLY" on YouTube, then set path here,
# or set the YT_COOKIES_FILE environment variable instead.
import os
COOKIES_FILE = os.environ.get("YT_COOKIES_FILE", "")

# Instagram cookies (optional) — only needed for private accounts or
# reels that show "login required". Export the same way but while
# logged into instagram.com.
INSTAGRAM_COOKIES_FILE = os.environ.get("INSTAGRAM_COOKIES_FILE", "")

# Gemini model used for auto-translation (see subtitles.py for the
# full Arabic-subtitle priority chain)
GEMINI_MODEL      = "gemini-3.8-flash"
GEMINI_RETRIES    = 2    # extra attempts on transient server/connection errors
GEMINI_RETRY_WAIT = 5    # seconds between those retries (never retries a 429)

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
