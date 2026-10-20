"""
Job runner for the web UI — one job at a time on a worker thread, with a
queue behind it, and every log line / progress update turned into an
event that the server broadcasts to all open browser tabs.
"""

import gc
import queue
import threading
import time

from ytarabic.errors import Cancelled
from ytarabic.utils import fmt_size


class JobManager:
    def __init__(self):
        self.events: "queue.Queue[dict]" = queue.Queue()
        self.clients: set = set()       # every connected browser tab
        self.activity: list = []        # this job's events, replayed to tabs that join mid-job
        self.busy = False
        self.current = ""
        self.current_label = ""
        self.queued: list = []          # [{"name", "label"}] — display only, fn kept out of this list
        self.outcome = None             # set by a task: success | failed | cancelled
        self._stop_requested = False
        self._max_total = 0             # largest total_bytes seen for the current file
        self._cur_file = None
        self._last_progress = 0.0
        self._pending: list = []        # [{"name", "label", "fn"}] — actual queue
        self._lock = threading.RLock()  # start()/queue edits come from request threads

    # ── events ────────────────────────────────
    def emit(self, kind: str, **payload):
        self.events.put({"kind": kind, **payload})

    def log(self, message: str, level: str = "info"):
        self.emit("log", message=message, level=level)

    def progress(self, fraction: float, label: str = "", **extra):
        self.emit("progress", fraction=max(0.0, min(1.0, fraction)), label=label, **extra)

    def item(self, index: int, total: int, title: str):
        """A playlist (or batch) moved on to its next video."""
        self._max_total = 0
        self._cur_file = None
        self.emit("item", index=index, total=total, title=title)

    def set_label(self, label: str):
        """Rename the running job — e.g. from its link to the video's title
        once that's known."""
        if self.busy:
            self.current_label = label
            self.emit("state", busy=True, job=self.current, label=label)

    def result(self, type_: str, **payload):
        """Something the UI can offer to open — a finished video, a transcript..."""
        self.emit("result", type=type_, **payload)

    def should_stop(self) -> bool:
        return self._stop_requested

    def request_stop(self):
        self._stop_requested = True
        self.log("Stopping…", "warn")

    def video_hook(self, d):
        """yt-dlp progress_hook → browser progress bar, with structured
        done/total/speed/eta fields the UI formats itself. Raises
        Cancelled to abort the in-flight download when a stop was requested.

        yt-dlp's own total_bytes_estimate is a rough extrapolation from
        the fragments seen so far and can shrink partway through a
        download (e.g. an early keyframe-heavy fragment overshoots the
        per-fragment average) — that looked like the video itself was
        shrinking. Never display a total smaller than one already shown
        for the same file. (Per *file*: a 1080p download is a big video
        stream then a small audio stream, and holding the video's total
        made the audio part look stuck at 2%.)"""
        if self._stop_requested:
            raise Cancelled("stop requested")
        if d["status"] == "downloading":
            filename = d.get("filename")
            if filename != self._cur_file:
                self._cur_file = filename
                self._max_total = 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0) or 0
            now = time.monotonic()
            if now - self._last_progress < 0.25:   # plenty for a progress bar
                return
            self._last_progress = now
            if total:
                self._max_total = max(self._max_total, total)
                total = self._max_total
                speed = d.get("speed") or 0
                label = f"{fmt_size(done)} / {fmt_size(total)}"
                if speed:
                    label += f"  ·  {fmt_size(speed)}/s"
                self.progress(done / total, label, done=done, total=total,
                              speed=speed, eta=d.get("eta"))
        elif d["status"] == "finished":
            self.progress(1.0, "Processing…", phase="processing")

    # ── running ───────────────────────────────
    def start(self, name: str, fn, label: str = "") -> str:
        """
        Run fn() on a worker thread, or queue it if a job is already
        running — it starts automatically once the current one (and
        anything queued ahead of it) finishes. Returns "started" or
        "queued".
        """
        with self._lock:
            if self.busy:
                self._pending.append({"name": name, "label": label, "fn": fn})
                self._publish_queue()
                self.log(f"Queued: {label}" if label else "Queued — will start when the current job finishes.", "info")
                return "queued"
            self._run(name, fn, label)
            return "started"

    def remove_queued(self, index: int):
        with self._lock:
            if not 0 <= index < len(self._pending):
                return None
            removed = self._pending.pop(index)
            self._publish_queue()
            return removed

    def clear_queue(self) -> int:
        with self._lock:
            n = len(self._pending)
            self._pending.clear()
            self._publish_queue()
            return n

    def _publish_queue(self):
        self.queued = [{"name": p["name"], "label": p["label"]} for p in self._pending]
        self.emit("queued", queue=list(self.queued))

    def _run(self, name: str, fn, label: str = ""):
        self.busy = True
        self.current = name
        self.current_label = label
        self.outcome = None
        self._stop_requested = False
        self._max_total = 0
        self._cur_file = None
        self.activity.clear()   # each job starts a fresh activity log
        self.emit("state", busy=True, job=name, label=label)

        def worker():
            try:
                fn()
            except Cancelled:
                self.outcome = "cancelled"
                self.log("Stopped by user.", "warn")
            except Exception as exc:
                self.outcome = "failed"
                self.log(f"Unexpected error: {exc}", "error")
            finally:
                # A stopped download can leave yt-dlp's output file open
                # until the garbage collector runs (see download_with_retry)
                gc.collect()
                outcome = self.outcome or ("cancelled" if self._stop_requested else "success")
                with self._lock:
                    self.busy = False
                    self.current = ""
                    self.current_label = ""
                    self._stop_requested = False
                    self.progress(0.0, "")
                    self.emit("state", busy=False, job="", label="")
                    self.emit("done", job=name, label=label, status=outcome)
                    self._advance_queue()

        threading.Thread(target=worker, daemon=True).start()

    def _advance_queue(self):
        if not self._pending:
            return
        nxt = self._pending.pop(0)
        self._publish_queue()
        self.log(f"Starting queued job: {nxt['label']}" if nxt["label"] else "Starting next queued job...", "info")
        self._run(nxt["name"], nxt["fn"], nxt["label"])
