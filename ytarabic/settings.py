"""
User preferences — editable from the web UI's Settings tab, persisted to
settings.json in the project root (git-ignored).

Unlike config.py (fixed at startup, mostly from .env), these are read
fresh every time they're used, so a change in the UI applies to the very
next download/translation without restarting anything. Unknown keys and
invalid values are ignored rather than raising — a hand-edited or
outdated settings.json can never stop the app from starting.
"""

import json
import os
import re
import threading
from pathlib import Path

from .config import GEMINI_MODEL, PROJECT_ROOT, QUALITY_OPTIONS

SETTINGS_FILE = Path(os.environ.get("YTARABIC_SETTINGS_FILE") or PROJECT_ROOT / "settings.json")

DEFAULTS = {
    "default_quality":       "2",
    # ar     — Arabic only (the full priority chain)
    # ar_en  — Arabic, plus keep an English subtitle next to it
    # en     — English only, no translation
    # none   — no subtitles at all
    "subtitle_mode":         "ar",
    # Which machine translation to try first when a video has no real
    # (human-made) Arabic subtitle. YouTube's own is instant and costs
    # nothing; Gemini reads the whole file for context and usually reads
    # more naturally, but uses your free-tier quota.
    "translation_order":     "youtube_first",   # youtube_first | gemini_first
    "gemini_model":          GEMINI_MODEL,
    "embed_subtitles":       False,   # mux subtitles into the video file as a soft track
    "rate_limit_mb":         0,       # download speed cap in MB/s, 0 = unlimited
    "transcript_lang":       "auto",  # auto (video's own language) | en | ar
    "transcript_timestamps": False,
    "summary_lang":          "ar",    # ar | en
}

_CHOICES = {
    "default_quality":   set(QUALITY_OPTIONS),
    "subtitle_mode":     {"ar", "ar_en", "en", "none"},
    "translation_order": {"youtube_first", "gemini_first"},
    "transcript_lang":   {"auto", "en", "ar"},
    "summary_lang":      {"ar", "en"},
}
_MODEL_RE = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")
_lock = threading.Lock()


def _clean(key: str, value):
    """The validated value for key, or None if it's not acceptable."""
    if key in _CHOICES:
        return value if value in _CHOICES[key] else None
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if key == "rate_limit_mb":
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if 0 <= value <= 10_000 else None
    if key == "gemini_model":
        value = str(value).strip()
        return value if _MODEL_RE.match(value) else None
    return None


def load() -> dict:
    """Every setting — saved values over defaults."""
    data = dict(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key in DEFAULTS:
                cleaned = _clean(key, value)
                if cleaned is not None:
                    data[key] = cleaned
    return data


def get(key: str):
    return load()[key]


def update(changes: dict) -> tuple:
    """Apply `changes` and save. Returns (settings, rejected_keys) —
    anything unknown or invalid is reported back instead of saved."""
    rejected = []
    with _lock:
        data = load()
        for key, value in (changes or {}).items():
            if key not in DEFAULTS:
                rejected.append(key)
                continue
            cleaned = _clean(key, value)
            if cleaned is None:
                rejected.append(key)
            else:
                data[key] = cleaned
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    return data, rejected
