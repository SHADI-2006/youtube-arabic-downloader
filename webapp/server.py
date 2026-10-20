"""
ytarabic — local web interface (FastAPI + WebSocket).

Run:  python -m webapp.server        (or: uvicorn webapp.server:app --reload)
Then open http://127.0.0.1:8000
"""

import asyncio
import hashlib
import os
import queue
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webapp.jobs import JobManager
from ytarabic import (
    __version__, config, library, media, settings, social, subtitles, summary,
    transcript, youtube,
)
from ytarabic.progress_store import (
    clear_history, clear_single_pending, forget_playlist, load_history, load_pending,
    load_progress, log_history,
)
from ytarabic.utils import (
    classify_url, extract_playlist_id, extract_youtube_id, fmt_size, normalize_playlist_url,
    normalize_youtube_url,
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_broadcast_loop())
    yield
    task.cancel()


app = FastAPI(title="ytarabic", docs_url="/api/docs", lifespan=lifespan)
jobs = JobManager()


# ─────────────────────────────────────────────
#  Local-only guard
# ─────────────────────────────────────────────
# The server only listens on 127.0.0.1, but any website open in the same
# browser can still *send* requests to it (that's how a page can make your
# browser hit localhost). Requiring our own Host header blocks DNS-rebinding
# tricks, and refusing state-changing requests from a foreign Origin stops a
# random page from starting downloads, deleting leftover files, or opening
# folders on your machine.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _hostname(value: str) -> str:
    try:
        return (urlparse("//" + value).hostname or "").lower()
    except ValueError:
        return ""


def _origin_ok(origin: Optional[str]) -> bool:
    if not origin:
        return True   # same-origin GETs and non-browser clients send none
    try:
        return (urlparse(origin).hostname or "").lower() in _LOCAL_HOSTS
    except ValueError:
        return False


@app.middleware("http")
async def local_only(request: Request, call_next):
    if _hostname(request.headers.get("host", "")) not in _LOCAL_HOSTS:
        return PlainTextResponse("Forbidden host", status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _origin_ok(request.headers.get("origin")):
        return PlainTextResponse("Cross-site request refused", status_code=403)
    return await call_next(request)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
SUB_MODES = {"ar", "ar_en", "en", "none"}
_probe_cache: dict = {}    # url → (time, result)
PROBE_TTL = 600


def _quality(q: Optional[str]) -> str:
    return q if q in config.QUALITY_OPTIONS else settings.get("default_quality")


def _short_quality(key: str) -> str:
    return " ".join(config.quality_label(key).split())


def _record(kind: str, url: str, title: str, status: str, detail: str = "", **extra):
    """History entry + the job's outcome (shown in the "done" notification)."""
    log_history(kind, url, title, status, detail, **extra)
    jobs.outcome = status


def _rel(path) -> Optional[str]:
    try:
        return library.rel(Path(path))
    except (ValueError, TypeError):
        return None


def _known_title(url: str) -> Optional[str]:
    """A title for a queue label, if this link was previewed recently."""
    for key in (url, normalize_youtube_url(url), normalize_playlist_url(url)):
        hit = _probe_cache.get(key)
        if hit and hit[1].get("ok") and hit[1].get("title"):
            return hit[1]["title"]
    return None


def _resolve(rel_path: str, allowed_exts: Optional[set] = None) -> Path:
    p = library.resolve(rel_path)
    if not p.exists():
        raise FileNotFoundError(rel_path)
    if allowed_exts is not None and p.suffix.lower() not in allowed_exts:
        raise ValueError("file type not allowed")
    return p


def _err(msg: str) -> dict:
    return {"ok": False, "error": msg}


# ─────────────────────────────────────────────
#  Request models
# ─────────────────────────────────────────────
class DownloadRequest(BaseModel):
    urls: list[str] = []
    url: str = ""                       # single link (older clients)
    quality: Optional[str] = None
    playlist: bool = False              # treat a watch?v=…&list=… link as the whole playlist
    is_playlist: bool = False           # older name for `playlist`
    items: Optional[list[str]] = None   # playlist: only these video ids
    subtitle_mode: Optional[str] = None
    embed: Optional[bool] = None
    with_transcript: bool = False


class UrlRequest(BaseModel):
    url: str


class UrlsRequest(BaseModel):
    urls: list[str]


class TranscriptRequest(BaseModel):
    url: str
    lang: Optional[str] = None
    timestamps: Optional[bool] = None


class PathRequest(BaseModel):
    path: str = ""


class SubtitleRequest(BaseModel):
    path: str
    engine: str = "auto"     # auto | manual | youtube | gemini | google | english


class SummaryRequest(BaseModel):
    path: str
    lang: Optional[str] = None


class CleanupRequest(BaseModel):
    include_unfinished: bool = False


class ForgetRequest(BaseModel):
    url: str
    type: str = "playlist"   # playlist | single


# ─────────────────────────────────────────────
#  Status / settings
# ─────────────────────────────────────────────
@app.get("/api/status")
def status():
    def _exists(p):
        return bool(p and Path(p).exists())
    return {
        "version": __version__,
        "busy": jobs.busy,
        "job": jobs.current,
        "label": jobs.current_label,
        "queue": jobs.queued,
        "ffmpeg": config.HAS_FFMPEG,
        "ffmpeg_path": config.FFMPEG_PATH,
        "cookies": _exists(config.COOKIES_FILE),
        "instagram_cookies": _exists(config.INSTAGRAM_COOKIES_FILE),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "qualities": [
            {"key": k, "label": label} for k, (label, _, _) in config.QUALITY_OPTIONS.items()
        ],
        "download_dir": str(config.DOWNLOAD_DIR.resolve()),
        "settings": settings.load(),
    }


@app.get("/api/settings")
def get_settings():
    return {"settings": settings.load(), "defaults": settings.DEFAULTS}


@app.post("/api/settings")
def save_settings(changes: dict = Body(...)):
    data, rejected = settings.update(changes)
    return {"ok": not rejected, "settings": data, "rejected": rejected,
            **({"error": "Invalid value for: " + ", ".join(rejected)} if rejected else {})}


# ─────────────────────────────────────────────
#  Link preview
# ─────────────────────────────────────────────
@app.post("/api/probe")
def probe(req: UrlRequest):
    url = req.url.strip()
    if not url:
        return _err("No link given")
    hit = _probe_cache.get(url)
    if hit and time.time() - hit[0] < PROBE_TTL:
        return hit[1]
    result = youtube.probe(url)
    if result.get("ok"):
        now = time.time()
        for key in {url, result.get("url") or url}:
            _probe_cache[key] = (now, result)
        if len(_probe_cache) > 200:
            for key, _ in sorted(_probe_cache.items(), key=lambda kv: kv[1][0])[:100]:
                _probe_cache.pop(key, None)
    return result


# Kept for older clients / the API docs
@app.post("/api/sizes")
def sizes(req: UrlRequest):
    return {"sizes": youtube.get_all_sizes(req.url)}


@app.post("/api/playlist-info")
def playlist_info(req: UrlRequest):
    info = youtube.read_playlist_info(req.url, log=jobs.log)
    if not info:
        return _err("Could not read playlist")
    entries = [e for e in info.get("entries", []) if e]
    return {"ok": True, "title": info.get("title", "playlist"), "count": len(entries)}


# ─────────────────────────────────────────────
#  Downloads
# ─────────────────────────────────────────────
def _queue_single(url: str, quality: str, mode: Optional[str], embed: Optional[bool],
                  with_transcript: bool) -> str:
    url = normalize_youtube_url(url) if classify_url(url) == "youtube" else url.strip()
    q_label = _short_quality(quality)

    def task():
        out = youtube.download_single(
            url, quality, log=jobs.log, on_video_progress=jobs.video_hook,
            should_stop=jobs.should_stop, subtitle_mode=mode, embed=embed,
            on_info=lambda title: jobs.set_label(f"{title} · {q_label}"),
        )
        status = "cancelled" if out["cancelled"] else ("success" if out["success"] else "failed")
        _record("video", url, out["title"], status, q_label, quality=quality)
        if out["success"] and out.get("path") and _rel(out["path"]):
            jobs.result("media", path=_rel(out["path"]), title=out["title"])
        if (out["success"] and with_transcript and quality != config.AUDIO_ONLY_KEY
                and classify_url(url) == "youtube"):
            path = transcript.extract_transcript(url, log=jobs.log)
            log_history("transcript", url, path.stem if path else url, "success" if path else "failed")
            if path:
                jobs.result("transcript", path=_rel(path))

    title = _known_title(url) or url
    return jobs.start("download", task, label=f"{title} · {q_label}")


def _run_playlist(url: str, quality: str, entries: list, title: str, *, mode=None, embed=None,
                  selected=None, is_resume=False):
    q_label = _short_quality(quality)
    result = youtube.download_playlist(
        url, quality, entries, title,
        log=jobs.log, on_video_progress=jobs.video_hook, on_item_start=jobs.item,
        should_stop=jobs.should_stop, is_resume=is_resume, selected=selected,
        subtitle_mode=mode, embed=embed,
    )
    status = ("cancelled" if result["stopped"]
              else "failed" if result["failed"] and not result["done"] else "success")
    if result["stopped"]:
        jobs.log(f"Stopped — {result['done']} downloaded before stopping ({q_label}).", "warn")
    else:
        jobs.log(f"Finished ({q_label}) — saved to {result['output_dir'].resolve()}", "success")
        if result["failed"]:
            jobs.log(f"Failed ({len(result['failed'])}): " + ", ".join(result["failed"][:5]), "warn")
    _record("playlist", url, title, status,
            f"{q_label} · {result['done']} downloaded, {len(result['failed'])} failed", quality=quality)


def _queue_playlist(url: str, quality: str, mode: Optional[str], embed: Optional[bool],
                    items: Optional[list]) -> str:
    url = normalize_playlist_url(url)
    q_label = _short_quality(quality)

    def task():
        jobs.log("Reading playlist…", "info")
        info = youtube.read_playlist_info(url, log=jobs.log)
        if not info:
            jobs.log("Could not read playlist.", "error")
            _record("playlist", url, url, "failed", f"{q_label} · could not read playlist", quality=quality)
            return
        entries = [e for e in info.get("entries", []) if e]
        title = info.get("title", "playlist")
        picked = f"{len(items)} of {len(entries)}" if items else str(len(entries))
        jobs.log(f"Playlist: {title} ({picked} videos, {q_label})", "info")
        _run_playlist(url, quality, entries, title, mode=mode, embed=embed, selected=items or None)

    title = _known_title(url) or "Playlist"
    count = f" ({len(items)})" if items else ""
    return jobs.start("playlist", task, label=f"{title}{count} · {q_label}")


def _queue_instagram(urls: list) -> str:
    def task():
        result = youtube.download_instagram_reels(
            urls, log=jobs.log, on_video_progress=jobs.video_hook,
            should_stop=jobs.should_stop, on_item_start=jobs.item,
        )
        if result["stopped"]:
            jobs.log(f"Stopped — {result['ok']}/{result['total']} downloaded before stopping.", "warn")
        else:
            jobs.log(f"Done — {result['ok']}/{result['total']} downloaded → {result['output_dir'].resolve()}",
                     "success")
        status = "cancelled" if result["stopped"] else ("failed" if not result["ok"] else "success")
        _record("instagram", "|".join(urls), f"{result['ok']}/{result['total']} reels", status)

    return jobs.start("instagram", task, label=f"Instagram · {len(urls)} reel(s)")


@app.post("/api/download")
def start_download(req: DownloadRequest):
    urls = [u.strip() for u in (req.urls or [req.url]) if u and u.strip()]
    if not urls:
        return _err("No link given")
    quality = _quality(req.quality)
    mode = req.subtitle_mode if req.subtitle_mode in SUB_MODES else None
    as_playlist = (req.playlist or req.is_playlist) and len(urls) == 1

    statuses = []
    instagram = [u for u in urls if classify_url(u) == "instagram"]
    for u in urls:
        if u in instagram:
            continue
        pure_playlist = extract_playlist_id(u) and not extract_youtube_id(u)
        if as_playlist or pure_playlist:
            if not extract_playlist_id(u):
                return _err("That link isn't a YouTube playlist.")
            statuses.append(_queue_playlist(u, quality, mode, req.embed,
                                            req.items if len(urls) == 1 else None))
        else:
            statuses.append(_queue_single(u, quality, mode, req.embed, req.with_transcript))
    if instagram:
        statuses.append(_queue_instagram(instagram))

    return {"ok": True, "jobs": len(statuses),
            "status": "started" if statuses and statuses[0] == "started" else "queued"}


@app.post("/api/instagram")
def start_instagram(req: UrlsRequest):
    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        return _err("No link given")
    return {"ok": True, "status": _queue_instagram(urls)}


@app.post("/api/stop")
def stop_job():
    if not jobs.busy:
        return _err("Nothing is running")
    jobs.request_stop()
    return {"ok": True}


@app.get("/api/queue")
def get_queue():
    return {"busy": jobs.busy, "job": jobs.current, "label": jobs.current_label, "queue": jobs.queued}


@app.post("/api/queue/remove")
def remove_queued(index: int):
    removed = jobs.remove_queued(index)
    if removed is None:
        return _err("No such queued item")
    jobs.log(f"Removed from queue: {removed['label']}" if removed["label"] else "Removed from queue.", "info")
    return {"ok": True}


@app.post("/api/queue/clear")
def clear_queue():
    n = jobs.clear_queue()
    if n:
        jobs.log(f"Cleared {n} queued job(s).", "info")
    return {"ok": True, "removed": n}


# ─────────────────────────────────────────────
#  Transcripts, X threads, summaries
# ─────────────────────────────────────────────
@app.post("/api/transcript")
def start_transcript(req: TranscriptRequest):
    url = req.url.strip()
    if not url:
        return _err("No link given")
    lang = req.lang if req.lang in ("auto", "en", "ar") else None

    def task():
        out = transcript.extract_transcript(url, log=jobs.log, lang=lang, timestamps=req.timestamps)
        _record("transcript", url, out.stem if out else url, "success" if out else "failed")
        if out:
            jobs.result("transcript", path=_rel(out))

    return {"ok": True, "status": jobs.start("transcript", task, label=f"Transcript · {_known_title(url) or url}")}


@app.post("/api/tweet")
def start_tweet(req: UrlRequest):
    url = req.url.strip()
    if not url:
        return _err("No link given")

    def task():
        out = social.extract_tweet(url, log=jobs.log)
        _record("tweet", url, out.name if out else url, "success" if out else "failed")
        if out and (out / "transcript.txt").exists():
            jobs.result("transcript", path=_rel(out / "transcript.txt"))

    return {"ok": True, "status": jobs.start("tweet", task, label="X thread")}


@app.get("/api/transcripts")
def list_transcripts():
    return {"items": library.list_transcripts()}


@app.post("/api/summarize")
def start_summary(req: SummaryRequest):
    try:
        path = _resolve(req.path, {".txt"})
    except (ValueError, FileNotFoundError):
        return _err("Transcript not found")
    lang = req.lang if req.lang in ("ar", "en") else None

    def task():
        out = summary.summarize(path, lang, log=jobs.log)
        _record("summary", _rel(path) or path.name, path.stem, "success" if out else "failed")
        if out:
            jobs.result("summary", path=_rel(out), source=_rel(path))

    return {"ok": True, "status": jobs.start("summary", task, label=f"Summary · {path.stem[:60]}")}


@app.get("/api/text")
def read_text(path: str):
    try:
        p = _resolve(path, library.TEXT_EXTS)
    except (ValueError, FileNotFoundError):
        return PlainTextResponse("Not found", status_code=404)
    if p.stat().st_size > 20 * 1024 * 1024:
        return PlainTextResponse("File too large to show", status_code=413)
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


# ─────────────────────────────────────────────
#  Library: browse, play, subtitles, embed, clean up
# ─────────────────────────────────────────────
@app.get("/api/library")
def get_library(q: str = ""):
    data = library.scan(q)
    left = library.find_leftovers()
    data["leftovers"] = {
        "junk_bytes": left["junk_bytes"], "junk_count": len(left["junk"]),
        "unfinished_bytes": left["unfinished_bytes"], "unfinished_count": len(left["unfinished"]),
    }
    return data


@app.get("/api/media")
def get_media(path: str):
    try:
        p = _resolve(path, library.MEDIA_EXTS)
    except (ValueError, FileNotFoundError):
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(p, media_type=media.MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream"))


@app.get("/api/subtitle")
def get_subtitle(path: str):
    try:
        p = _resolve(path, config.SUB_EXTS)
    except (ValueError, FileNotFoundError):
        return PlainTextResponse("Not found", status_code=404)
    vtt = media.subtitle_as_vtt(p)
    if vtt is None:
        return PlainTextResponse("Can't convert this subtitle", status_code=415)
    return Response(vtt, media_type="text/vtt; charset=utf-8")


def _reveal(p: Path):
    """Open the folder in the system file manager (the file selected, if it's a file)."""
    if sys.platform == "win32":
        if p.is_file():
            # Windows filenames can't contain '"', so quoting is safe here
            subprocess.Popen(f'explorer /select,"{p}"')
        else:
            os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])


@app.post("/api/open")
def open_in_explorer(req: PathRequest):
    try:
        if req.path:
            p = _resolve(req.path)
        else:
            p = library.root()
            p.mkdir(parents=True, exist_ok=True)
    except (ValueError, FileNotFoundError):
        return _err("Not found")
    try:
        _reveal(p)
    except OSError as e:
        return _err(f"Couldn't open: {e}")
    return {"ok": True}


@app.post("/api/fetch-subtitle")
def fetch_subtitle(req: SubtitleRequest):
    try:
        p = _resolve(req.path, library.MEDIA_EXTS)
    except (ValueError, FileNotFoundError):
        return _err("Video not found")
    video_id, title = library.parse_media_name(p)
    if not video_id:
        return _err("This file has no YouTube id in its name, so its subtitles can't be looked up.")
    engine = req.engine if req.engine in subtitles.ENGINES + ("english",) else "auto"
    url = f"https://www.youtube.com/watch?v={video_id}"

    def task():
        if engine == "english":
            source = subtitles.fetch_subtitles(url, p.parent, jobs.log, jobs.should_stop, mode="en")
        else:
            jobs.log(f"Fetching Arabic subtitle for \"{title}\"…", "info")
            source = subtitles.fetch_subtitles(url, p.parent, jobs.log, jobs.should_stop,
                                               mode="ar", engine=engine)
            if source:
                jobs.log(f"Done — Arabic subtitle saved ({source}).", "success")
            else:
                jobs.log("No Arabic subtitle could be produced this time — the previous one (if any) was kept.",
                         "warn")
        _record("subtitle", url, title, "success" if source else "failed", source or "")

    label = {"auto": "Arabic subtitle", "english": "English subtitle"}.get(engine, f"Arabic subtitle ({engine})")
    return {"ok": True, "status": jobs.start("subtitle", task, label=f"{label} · {title[:60]}")}


@app.post("/api/embed")
def embed(req: PathRequest):
    try:
        p = _resolve(req.path, config.VALID_VIDEO_EXTS)
    except (ValueError, FileNotFoundError):
        return _err("Video not found")

    def task():
        ok = youtube.embed_downloaded_subtitles(p, jobs.log)
        jobs.outcome = "success" if ok else "failed"

    return {"ok": True, "status": jobs.start("embed", task, label=f"Embed subtitles · {p.stem[:60]}")}


@app.get("/api/cleanup")
def cleanup_preview():
    return library.find_leftovers()


@app.post("/api/cleanup")
def cleanup(req: CleanupRequest):
    if jobs.busy:
        return _err("A download is running — clean up once it finishes.")
    result = library.cleanup(req.include_unfinished, log=jobs.log)
    jobs.log(f"Cleaned up {result['removed']} leftover file(s) — freed {fmt_size(result['freed'])}.", "success")
    return {"ok": True, **result}


# ─────────────────────────────────────────────
#  Resume
# ─────────────────────────────────────────────
@app.get("/api/saved-progress")
def saved_progress():
    """Everything with room to resume: playlists with incomplete items,
    and single videos that started but never finished (stopped, or the
    app closed mid-download)."""
    playlists = []
    for url, data in load_progress().items():
        done = data.get("done", [])
        key = data.get("quality") or (done[0].rsplit("_", 1)[-1] if done and "_" in done[0] else "2")
        done_here = [d for d in done if d.rsplit("_", 1)[-1] == key]
        total = data.get("total")
        if not done_here and not total:
            continue
        if total and len(done_here) >= total:
            continue   # finished — nothing left to resume
        titles = list(data.get("titles", {}).values())
        playlists.append({
            "type": "playlist",
            "url": url,
            "title": data.get("title") or (titles[-1] if titles else url),
            "done": len(done_here),
            "total": total,
            "selected": len(data["selected"]) if data.get("selected") else None,
            "quality": key,
            "quality_label": config.quality_label(key),
            "recent": titles[-3:],
        })

    singles = []
    for url, data in load_pending().items():
        q = data.get("quality", "2")
        singles.append({
            "type": "single",
            "url": url,
            "title": data.get("title", url),
            "quality": q,
            "quality_label": config.quality_label(q),
        })

    return {"playlists": playlists, "singles": singles}


@app.post("/api/resume")
def resume(req: UrlRequest):
    url = normalize_playlist_url(req.url)
    data = load_progress().get(url, {})
    done = data.get("done", [])
    key = data.get("quality") or (done[0].rsplit("_", 1)[-1] if done and "_" in done[0] else "2")
    q_label = _short_quality(key)

    def task():
        info = youtube.read_playlist_info(url, log=jobs.log)
        if not info:
            jobs.log("Could not re-read playlist.", "error")
            _record("playlist", url, url, "failed", f"{q_label} · could not re-read playlist", quality=key)
            return
        entries = [e for e in info.get("entries", []) if e]
        jobs.log(f"Resuming at {q_label}...", "info")
        _run_playlist(url, key, entries, info.get("title", "playlist"), is_resume=True)

    title = data.get("title") or "playlist"
    return {"ok": True, "status": jobs.start("resume", task, label=f"Resume · {title} · {q_label}")}


@app.post("/api/resume-single")
def resume_single(req: UrlRequest):
    url = normalize_youtube_url(req.url)
    pending = load_pending().get(url) or load_pending().get(req.url)
    if not pending:
        return _err("Not a pending download")
    quality = pending.get("quality", "2")
    q_label = _short_quality(quality)

    def task():
        jobs.log(f"Resuming at {q_label}...", "info")
        out = youtube.download_single(
            url, quality, log=jobs.log, on_video_progress=jobs.video_hook,
            should_stop=jobs.should_stop, is_resume=True,
        )
        status = "cancelled" if out["cancelled"] else ("success" if out["success"] else "failed")
        _record("video", url, out["title"], status, q_label, quality=quality)
        if out["success"] and out.get("path") and _rel(out["path"]):
            jobs.result("media", path=_rel(out["path"]), title=out["title"])

    return {"ok": True, "status": jobs.start("resume", task,
                                             label=f"Resume · {pending.get('title', url)} · {q_label}")}


@app.post("/api/resume/forget")
def resume_forget(req: ForgetRequest):
    ok = forget_playlist(req.url) if req.type == "playlist" else (
        clear_single_pending(req.url) or clear_single_pending(normalize_youtube_url(req.url)))
    return {"ok": True} if ok else _err("Not found")


@app.get("/api/playlist-detail")
def playlist_detail(url: str, quality: str = "2"):
    """Every video in the playlist, in order, with its downloaded state
    at `quality` — for expanding a Resume card into a per-video list."""
    url = normalize_playlist_url(url)
    info = youtube.read_playlist_info(url, log=jobs.log)
    if not info:
        return _err("Could not read playlist")
    entries = [e for e in info.get("entries", []) if e]
    data = load_progress().get(url, {})
    done = set(data.get("done", []))
    selected = set(data.get("selected") or [])
    videos = [
        {
            "video_id": e.get("id", ""),
            "title": e.get("title", ""),
            "downloaded": f"{e.get('id')}_{quality}" in done,
            "selected": not selected or e.get("id") in selected,
        }
        for e in entries
    ]
    return {"ok": True, "title": info.get("title", "playlist"), "videos": videos}


# ─────────────────────────────────────────────
#  History
# ─────────────────────────────────────────────
@app.get("/api/history")
def history():
    return {"entries": load_history()}


@app.post("/api/history/clear")
def history_clear():
    clear_history()
    return {"ok": True}


# ─────────────────────────────────────────────
#  WebSocket — live logs + progress
# ─────────────────────────────────────────────
async def _broadcast_loop():
    """
    Single consumer of the job queue: fans every event out to *all*
    connected tabs. (Draining the queue per-socket would split events
    between tabs instead of broadcasting them.)
    """
    while True:
        try:
            event = jobs.events.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.08)
            continue

        jobs.activity.append(event)
        del jobs.activity[:-400]

        for ws in list(jobs.clients):
            try:
                await ws.send_json(event)
            except Exception:
                jobs.clients.discard(ws)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    if not _origin_ok(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    await ws.accept()
    jobs.clients.add(ws)
    try:
        await ws.send_json({"kind": "replay-start"})
        for event in jobs.activity[-400:]:   # catch up a tab opened mid-job
            await ws.send_json(event)
        await ws.send_json({"kind": "replay-end"})
        while True:
            await ws.receive_text()          # blocks until the tab goes away
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        jobs.clients.discard(ws)


# ─────────────────────────────────────────────
#  Static frontend
# ─────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _asset_version() -> str:
    """Changes whenever a static file does — appended to the CSS/JS URLs
    so a browser never runs a cached old app.js against a newer server."""
    h = hashlib.sha1(__version__.encode())
    for f in sorted(STATIC_DIR.iterdir()):
        h.update(f"{f.name}{f.stat().st_mtime_ns}".encode())
    return h.hexdigest()[:10]


@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", _asset_version()),
                        headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
