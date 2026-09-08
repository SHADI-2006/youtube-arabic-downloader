"""Resumable-download progress tracking + a persistent download history log
(both atomic JSON files)."""

import json
from datetime import datetime
from .config import DOWNLOAD_DIR, PROGRESS_FILE

HISTORY_FILE  = DOWNLOAD_DIR / ".history.json"
HISTORY_LIMIT = 200


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


def log_history(kind: str, title: str, status: str, detail: str = ""):
    """
    Append one entry to the download history (newest first, capped at
    HISTORY_LIMIT). `kind`: video | playlist | transcript | tweet |
    instagram | subtitle. `status`: success | failed | cancelled.
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "time":   datetime.now().isoformat(timespec="seconds"),
        "kind":   kind,
        "title":  title,
        "status": status,
        "detail": detail,
    }
    history = load_history()
    history.insert(0, entry)
    del history[HISTORY_LIMIT:]
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HISTORY_FILE)
