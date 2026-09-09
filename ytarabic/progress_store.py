"""Resumable-download progress tracking + a persistent download history log
(both atomic JSON files)."""

import json
from datetime import datetime
from .config import DOWNLOAD_DIR, PROGRESS_FILE

HISTORY_FILE  = DOWNLOAD_DIR / ".history.json"
HISTORY_LIMIT = 200
PENDING_FILE  = DOWNLOAD_DIR / ".pending.json"


def atomic_save_progress(data: dict):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PROGRESS_FILE)


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def mark_done(progress: dict, playlist_url: str, done_key: str, title: str):
    if playlist_url not in progress:
        progress[playlist_url] = {"done": [], "titles": {}}
    if done_key not in progress[playlist_url]["done"]:
        progress[playlist_url]["done"].append(done_key)
    progress[playlist_url]["titles"][done_key] = title
    atomic_save_progress(progress)


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def log_history(kind: str, url: str, title: str, status: str, detail: str = ""):
    """
    Record one item in the download history (newest first, capped at
    HISTORY_LIMIT). `kind`: video | playlist | transcript | tweet |
    instagram | subtitle. `status`: success | failed | cancelled.

    Re-attempting the same `(kind, url)` replaces its previous entry
    instead of adding a new row — retries don't pile up as duplicates,
    the entry just moves to the top with its latest status and, once
    known, its real title instead of the raw URL.
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "time":   datetime.now().isoformat(timespec="seconds"),
        "kind":   kind,
        "url":    url,
        "title":  title,
        "status": status,
        "detail": detail,
    }
    history = [h for h in load_history() if not (h.get("kind") == kind and h.get("url") == url)]
    history.insert(0, entry)
    del history[HISTORY_LIMIT:]
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HISTORY_FILE)


def load_pending() -> dict:
    if PENDING_FILE.exists():
        try:
            return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def mark_single_pending(url: str, quality: str, title: str = ""):
    """Record a single-video download as started-but-not-confirmed-done,
    so it shows up in Resume if it gets stopped or the app closes mid-download."""
    pending = load_pending()
    pending[url] = {"quality": quality, "title": title or url}
    _save_pending(pending)


def clear_single_pending(url: str):
    pending = load_pending()
    if pending.pop(url, None) is not None:
        _save_pending(pending)


def _save_pending(pending: dict):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PENDING_FILE)
