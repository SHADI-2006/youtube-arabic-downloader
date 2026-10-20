"""Resumable-download progress tracking + a persistent download history log
(both atomic JSON files)."""

import json
import threading
from datetime import datetime
from pathlib import Path

from .config import DOWNLOAD_DIR, PROGRESS_FILE
from .utils import normalize_playlist_url

HISTORY_FILE   = DOWNLOAD_DIR / ".history.json"
HISTORY_LIMIT  = 300
PENDING_FILE   = DOWNLOAD_DIR / ".pending.json"
COMPLETED_FILE = DOWNLOAD_DIR / ".completed.json"

# Every file here is read-modify-written from the job thread and from web
# request threads — one lock keeps two writers from losing each other's update.
_lock = threading.RLock()


def _write_json(path: Path, data):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


# ─────────────────────────────────────────────
#  Playlist progress
# ─────────────────────────────────────────────
def atomic_save_progress(data: dict):
    with _lock:
        _write_json(PROGRESS_FILE, data)


def _merge_duplicate_playlists(progress: dict) -> bool:
    """Older versions keyed progress by the raw pasted link, so the same
    playlist shared twice (each share link gets a new `si=` parameter)
    ended up as two separate entries, each with part of the progress.
    Fold them into one entry under the canonical playlist URL."""
    changed = False
    for key in list(progress):
        canonical = normalize_playlist_url(key)
        if canonical == key:
            continue
        old = progress.pop(key)
        entry = progress.setdefault(canonical, {"done": [], "titles": {}})
        for done_key in old.get("done", []):
            if done_key not in entry.setdefault("done", []):
                entry["done"].append(done_key)
        entry.setdefault("titles", {}).update(old.get("titles", {}))
        for meta in ("title", "total", "selected", "quality"):
            if meta in old and meta not in entry:
                entry[meta] = old[meta]
        changed = True
    return changed


def load_progress() -> dict:
    with _lock:
        progress = _read_json(PROGRESS_FILE, {})
        if not isinstance(progress, dict):
            return {}
        if _merge_duplicate_playlists(progress):
            _write_json(PROGRESS_FILE, progress)
        return progress


def _apply_and_save(progress: dict, playlist_url: str, change):
    """Apply `change(entry)` to the caller's in-memory copy *and* to a
    fresh read of the file, then save the fresh one — so a long playlist
    run holding an old snapshot can't undo, say, a playlist you removed
    from Resume in the meantime."""
    with _lock:
        fresh = load_progress()
        for data in (progress, fresh):
            change(data.setdefault(playlist_url, {"done": [], "titles": {}}))
        atomic_save_progress(fresh)


def mark_done(progress: dict, playlist_url: str, done_key: str, title: str):
    def change(entry):
        if done_key not in entry.setdefault("done", []):
            entry["done"].append(done_key)
        entry.setdefault("titles", {})[done_key] = title
    _apply_and_save(progress, playlist_url, change)


def set_playlist_meta(progress: dict, playlist_url: str, title: str, total: int,
                      selected, quality: str, options: "dict | None" = None):
    """Remember the playlist's title, how many videos this run covers,
    which ones were picked (None = all) and the subtitle options — so
    Resume can show "7 / 12" and continue the same way."""
    _apply_and_save(progress, playlist_url, lambda entry: entry.update(
        {"title": title, "total": total, "selected": selected, "quality": quality,
         "options": {k: v for k, v in (options or {}).items() if v is not None}}))


def forget_playlist(playlist_url: str) -> bool:
    with _lock:
        progress = load_progress()
        if progress.pop(normalize_playlist_url(playlist_url), None) is None:
            return False
        atomic_save_progress(progress)
        return True


# ─────────────────────────────────────────────
#  History
# ─────────────────────────────────────────────
def load_history() -> list:
    data = _read_json(HISTORY_FILE, [])
    return data if isinstance(data, list) else []


def log_history(kind: str, url: str, title: str, status: str, detail: str = "", **extra):
    """
    Record one item in the download history (newest first, capped at
    HISTORY_LIMIT). `kind`: video | playlist | transcript | tweet |
    instagram | subtitle | summary. `status`: success | failed | cancelled.
    `extra` (e.g. quality="2") is stored too, so a failed item can be
    retried with the same options.

    Re-attempting the same `(kind, url)` replaces its previous entry
    instead of adding a new row — retries don't pile up as duplicates,
    the entry just moves to the top with its latest status and, once
    known, its real title instead of the raw URL.
    """
    entry = {
        "time":   datetime.now().isoformat(timespec="seconds"),
        "kind":   kind,
        "url":    url,
        "title":  title,
        "status": status,
        "detail": detail,
        **extra,
    }
    with _lock:
        history = [h for h in load_history() if not (h.get("kind") == kind and h.get("url") == url)]
        history.insert(0, entry)
        del history[HISTORY_LIMIT:]
        _write_json(HISTORY_FILE, history)


def clear_history():
    with _lock:
        _write_json(HISTORY_FILE, [])


# ─────────────────────────────────────────────
#  Single videos started but not finished
# ─────────────────────────────────────────────
def load_pending() -> dict:
    data = _read_json(PENDING_FILE, {})
    return data if isinstance(data, dict) else {}


def mark_single_pending(url: str, quality: str, title: str = "", **options):
    """Record a single-video download as started-but-not-confirmed-done,
    so it shows up in Resume if it gets stopped or the app closes mid-download.
    `options` (subtitle_mode, embed) are kept so Resume uses the same ones."""
    with _lock:
        pending = load_pending()
        pending[url] = {"quality": quality, "title": title or url,
                        **{k: v for k, v in options.items() if v is not None}}
        _write_json(PENDING_FILE, pending)


def clear_single_pending(url: str) -> bool:
    with _lock:
        pending = load_pending()
        if pending.pop(url, None) is None:
            return False
        _write_json(PENDING_FILE, pending)
        return True


# ─────────────────────────────────────────────
#  Cross single/playlist dedup: "already have this video at this
#  quality" regardless of whether it was downloaded standalone or as
#  part of a playlist.
# ─────────────────────────────────────────────
def _load_completed() -> dict:
    data = _read_json(COMPLETED_FILE, {})
    return data if isinstance(data, dict) else {}


def mark_video_done(video_id: str, quality: str, title: str, path: str):
    with _lock:
        completed = _load_completed()
        completed[f"{video_id}_{quality}"] = {"title": title, "path": str(Path(path).resolve())}
        _write_json(COMPLETED_FILE, completed)


def find_completed_video(video_id: str, quality: str) -> "str | None":
    """Path to the existing file for (video_id, quality), or None if
    never downloaded at that quality — or the record is stale because
    the file was since moved/deleted."""
    entry = _load_completed().get(f"{video_id}_{quality}")
    if not entry:
        return None
    p = Path(entry["path"])
    if not p.is_absolute():
        # Older records were relative to the project folder
        from .config import PROJECT_ROOT
        p = PROJECT_ROOT / p
    return str(p) if p.exists() else None
