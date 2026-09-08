"""Resumable-download progress tracking (atomic JSON file)."""

import json
from .config import DOWNLOAD_DIR, PROGRESS_FILE


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
