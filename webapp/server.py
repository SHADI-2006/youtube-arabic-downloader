"""
ytarabic — local web interface (FastAPI + WebSocket).

Run:  python -m webapp.server        (or: uvicorn webapp.server:app --reload)
Then open http://127.0.0.1:8000
"""

import asyncio
import queue
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ytarabic import config, social, subtitles, transcript, youtube
from ytarabic.progress_store import load_progress

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_broadcast_loop())
    yield
    task.cancel()


app = FastAPI(title="ytarabic", docs_url="/api/docs", lifespan=lifespan)


# ─────────────────────────────────────────────
#  Job manager — one job at a time, streamed to the browser
# ─────────────────────────────────────────────
class JobManager:
    def __init__(self):
        self.events: "queue.Queue[dict]" = queue.Queue()
        self.clients: set = set()      # every connected browser tab
        self.history: list = []        # replayed to tabs that join mid-job
        self.busy = False
        self.current = ""

    def emit(self, kind: str, **payload):
        self.events.put({"kind": kind, **payload})

    def log(self, message: str, level: str = "info"):
        self.emit("log", message=message, level=level)

    def progress(self, fraction: float, label: str = ""):
        self.emit("progress", fraction=max(0.0, min(1.0, fraction)), label=label)

    def video_hook(self, d):
        """yt-dlp progress_hook → browser progress bar."""
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            if total:
                speed = d.get("speed") or 0
                label = f"{done/1_048_576:.1f} / {total/1_048_576:.1f} MB"
                if speed:
                    label += f"  ·  {speed/1_048_576:.1f} MB/s"
                self.progress(done / total, label)
        elif d["status"] == "finished":
            self.progress(1.0, "Processing…")

    def start(self, name: str, fn) -> bool:
        """Run fn() on a worker thread. False if a job is already running."""
        if self.busy:
            return False
        self.busy = True
        self.current = name
        self.emit("state", busy=True, job=name)

        self.history.clear()   # each job starts a fresh activity log

        def worker():
            try:
                fn()
            except Exception as exc:
                self.log(f"Unexpected error: {exc}", "error")
            finally:
                self.busy = False
                self.current = ""
                self.progress(0.0, "")
                self.emit("state", busy=False, job="")
                self.emit("done")

        threading.Thread(target=worker, daemon=True).start()
        return True


jobs = JobManager()


# ─────────────────────────────────────────────
#  Request models
# ─────────────────────────────────────────────
class DownloadRequest(BaseModel):
    url: str
    quality: str = "2"
    is_playlist: bool = False
    with_transcript: bool = False


class UrlRequest(BaseModel):
    url: str


class UrlsRequest(BaseModel):
    urls: list[str]


class SubtitleRequest(BaseModel):
    video_id: str
    folder: str


# ─────────────────────────────────────────────
#  API
# ─────────────────────────────────────────────
@app.get("/api/status")
def status():
    cookies_path = Path(config.COOKIES_FILE) if config.COOKIES_FILE else None
    import os
    return {
        "busy": jobs.busy,
        "job": jobs.current,
        "ffmpeg": config.HAS_FFMPEG,
        "cookies": bool(cookies_path and cookies_path.exists()),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "qualities": [
            {"key": k, "label": label} for k, (label, _, _) in config.QUALITY_OPTIONS.items()
        ],
        "download_dir": str(config.DOWNLOAD_DIR.resolve()),
    }


@app.post("/api/playlist-info")
def playlist_info(req: UrlRequest):
    info = youtube.read_playlist_info(req.url, log=jobs.log)
    if not info:
        return {"ok": False, "error": "Could not read playlist"}
    entries = [e for e in info.get("entries", []) if e]
    return {
        "ok": True,
        "title": info.get("title", "playlist"),
        "count": len(entries),
    }


@app.post("/api/sizes")
def sizes(req: UrlRequest):
    return {"sizes": youtube.get_all_sizes(req.url)}


@app.post("/api/download")
def start_download(req: DownloadRequest):
    def task():
        if req.is_playlist:
            jobs.log("Reading playlist…", "info")
            info = youtube.read_playlist_info(req.url, log=jobs.log)
            if not info:
                jobs.log("Could not read playlist.", "error")
                return
            entries = [e for e in info.get("entries", []) if e]
            title = info.get("title", "playlist")
            jobs.log(f"Playlist: {title} ({len(entries)} videos)", "info")
            result = youtube.download_playlist(
                req.url, req.quality, entries, title,
                log=jobs.log, on_video_progress=jobs.video_hook,
                on_item_start=lambda i, n, t: jobs.emit("item", index=i, total=n, title=t),
            )
            jobs.log(f"Finished — saved to {result['output_dir'].resolve()}", "success")
            if result["failed"]:
                jobs.log(f"Failed ({len(result['failed'])}): " + ", ".join(result["failed"][:5]), "warn")
        else:
            out = youtube.download_single(
                req.url, req.quality, log=jobs.log, on_video_progress=jobs.video_hook
            )
            if out and req.with_transcript and req.quality != "6":
                transcript.extract_transcript(req.url, log=jobs.log)

    if not jobs.start("download", task):
        return {"ok": False, "error": "A job is already running"}
    return {"ok": True}


@app.post("/api/transcript")
def start_transcript(req: UrlRequest):
    if not jobs.start("transcript", lambda: transcript.extract_transcript(req.url, log=jobs.log)):
        return {"ok": False, "error": "A job is already running"}
    return {"ok": True}


@app.post("/api/tweet")
def start_tweet(req: UrlRequest):
    if not jobs.start("tweet", lambda: social.extract_tweet(req.url, log=jobs.log)):
        return {"ok": False, "error": "A job is already running"}
    return {"ok": True}


@app.post("/api/instagram")
def start_instagram(req: UrlsRequest):
    def task():
        result = youtube.download_instagram_reels(
            req.urls, log=jobs.log, on_video_progress=jobs.video_hook
        )
        jobs.log(
            f"Done — {result['ok']}/{result['total']} downloaded → {result['output_dir'].resolve()}",
            "success",
        )

    if not jobs.start("instagram", task):
        return {"ok": False, "error": "A job is already running"}
    return {"ok": True}


@app.get("/api/videos")
def list_videos(q: str = ""):
    out = []
    for path, video_id, title in subtitles.find_downloaded_videos(config.DOWNLOAD_DIR, q):
        tag = f"[{video_id}]"
        subs = {f for f in path.parent.iterdir() if f.suffix in config.SUB_EXTS and tag in f.name}
        out.append({
            "video_id": video_id,
            "title": title,
            "folder": str(path.parent),
            "has_arabic": subtitles.has_arabic_subtitle(subs),
        })
    return {"videos": out}


@app.post("/api/fetch-subtitle")
def fetch_subtitle(req: SubtitleRequest):
    folder = Path(req.folder)
    url = f"https://www.youtube.com/watch?v={req.video_id}"

    def task():
        jobs.log(f"Fetching subtitle for {req.video_id}…", "info")
        subtitles.fetch_subtitles(url, folder, log=jobs.log)
        tag = f"[{req.video_id}]"
        subs = {f for f in folder.iterdir() if f.suffix in config.SUB_EXTS and tag in f.name}
        if subtitles.has_arabic_subtitle(subs):
            jobs.log("Done — Arabic subtitle saved.", "success")
        else:
            jobs.log("Still no Arabic subtitle available for this video.", "warn")

    if not jobs.start("subtitle", task):
        return {"ok": False, "error": "A job is already running"}
    return {"ok": True}


@app.get("/api/saved-progress")
def saved_progress():
    out = []
    for url, data in load_progress().items():
        done = data.get("done", [])
        if not done:
            continue
        key = done[0].rsplit("_", 1)[-1] if "_" in done[0] else "2"
        out.append({
            "url": url,
            "done": len(done),
            "quality": key,
            "quality_label": config.QUALITY_OPTIONS.get(key, ("?",))[0],
            "recent": list(data.get("titles", {}).values())[-3:],
        })
    return {"playlists": out}


@app.post("/api/resume")
def resume(req: UrlRequest):
    progress = load_progress()
    done = progress.get(req.url, {}).get("done", [])
    key = done[0].rsplit("_", 1)[-1] if done and "_" in done[0] else "2"

    def task():
        info = youtube.read_playlist_info(req.url, log=jobs.log)
        if not info:
            jobs.log("Could not re-read playlist.", "error")
            return
        entries = [e for e in info.get("entries", []) if e]
        result = youtube.download_playlist(
            req.url, key, entries, info.get("title", "playlist"),
            log=jobs.log, on_video_progress=jobs.video_hook,
            on_item_start=lambda i, n, t: jobs.emit("item", index=i, total=n, title=t),
        )
        jobs.log(f"Finished — saved to {result['output_dir'].resolve()}", "success")

    if not jobs.start("resume", task):
        return {"ok": False, "error": "A job is already running"}
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

        jobs.history.append(event)
        del jobs.history[:-400]

        for ws in list(jobs.clients):
            try:
                await ws.send_json(event)
            except Exception:
                jobs.clients.discard(ws)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    jobs.clients.add(ws)
    try:
        for event in jobs.history[-400:]:   # catch up a tab opened mid-job
            await ws.send_json(event)
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


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
