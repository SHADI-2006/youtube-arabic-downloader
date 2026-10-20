"""
Central settings.

Configuration comes from environment variables, and from a local `.env`
file in the project root if one exists (never committed — see .gitignore).
The `.env` file wins only where the variable isn't already set in the
environment, so an explicit shell variable always takes precedence.

User preferences that can change at runtime (default quality, translation
order, Gemini model, ...) live in settings.py instead — they're editable
from the web UI without touching code.
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

# Anchored to the project root rather than the current directory, so
# launching from somewhere else doesn't scatter a second downloads/ folder.
# YTARABIC_DOWNLOAD_DIR overrides it (also what the tests use, to keep
# their files out of your real library).
DOWNLOAD_DIR  = Path(os.environ.get("YTARABIC_DOWNLOAD_DIR") or PROJECT_ROOT / "downloads")
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

# Default Gemini model used for auto-translation and summaries — the one
# actually used is the "gemini_model" setting (Settings tab), which starts
# out as this. See subtitles.py for the full Arabic-subtitle priority chain.
GEMINI_MODEL      = "gemini-3.5-flash-lite"
GEMINI_RETRIES    = 2    # extra attempts on transient server/connection errors
GEMINI_RETRY_WAIT = 5    # seconds between those retries (never retries a 429)
GEMINI_TIMEOUT    = 90   # seconds — without this, a stalled request hangs forever
                          # (no retry, no way to Stop it — it's not a checkpoint yt-dlp
                          # or our should_stop() callback ever gets a chance to hit).
                          # A 150-cue chunk measured ~33s under light load but 60-90s+
                          # under heavier account contention, so 30s was timing out on
                          # essentially every request — 90s gives real margin.
GEMINI_SUMMARY_TIMEOUT = 240   # a whole multi-hour transcript in one request

# ── Runtime constants ──
FFMPEG_PATH = shutil.which("ffmpeg")
HAS_FFMPEG  = FFMPEG_PATH is not None
UTF8_BOM   = b"\xef\xbb\xbf"
SUB_EXTS   = {".srt", ".vtt", ".ass", ".ssa"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
VALID_VIDEO_EXTS = {".mp4", ".mkv", ".webm"}   # completed video files only
AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".ogg"}  # completed audio-only downloads
MIN_VIDEO_BYTES  = 100 * 1024                   # 100 KB — ignore empty/partial files

SUBTITLES_EN = ["en"]        # exact match — one file only

AUDIO_ONLY_KEY = "6"

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

# Max video height per quality key (audio-only has none)
QUALITY_HEIGHT = {"1": 2160, "2": 1080, "3": 720, "4": 480, "5": 360}


def get_fmt(key: str) -> str:
    _, with_ff, no_ff = QUALITY_OPTIONS[key]
    return with_ff if HAS_FFMPEG else no_ff


def quality_label(key: str) -> str:
    return QUALITY_OPTIONS.get(key, (key,))[0]
