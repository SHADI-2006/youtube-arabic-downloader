#!/usr/bin/env python3
"""
ytarabic — desktop interface (CustomTkinter).

Requirements:  pip install -r requirements.txt
"""

import queue
import sys
import threading
from pathlib import Path

try:
    import customtkinter as ctk
    from tkinter import ttk
except ImportError:
    print("ERROR: Install required libraries first:\n  pip install -r requirements.txt")
    sys.exit(1)

from ytarabic import config, social, subtitles, transcript, youtube
from ytarabic.progress_store import load_progress

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

LEVEL_COLOR = {"info": "#8ec9ff", "warn": "#ffcc66", "error": "#ff6b6b", "success": "#7CFC9A"}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ytarabic — YouTube / Instagram / X Downloader")
        self.geometry("980x720")
        self.minsize(820, 600)

        self._log_queue: "queue.Queue" = queue.Queue()
        self._busy = False

        self._build_layout()
        self.after(80, self._drain_log_queue)

    # ── layout ──────────────────────────────────────────────
    def _build_layout(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="ytarabic", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")

        ffmpeg_txt  = "FFmpeg ✓" if config.HAS_FFMPEG else "FFmpeg ✗ (limited quality)"
        cookies_txt = "Cookies ✓" if (config.COOKIES_FILE and Path(config.COOKIES_FILE).exists()) else "Cookies — not set"
        ctk.CTkLabel(header, text=f"{ffmpeg_txt}    {cookies_txt}",
                     text_color="#9aa0a6").pack(side="right")

        self.tabs = ctk.CTkTabview(self, width=940)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=8)
        for name in ("Download", "Resume", "Transcript / Tweet", "Instagram", "Fix Subtitle"):
            self.tabs.add(name)

        self._build_download_tab(self.tabs.tab("Download"))
        self._build_resume_tab(self.tabs.tab("Resume"))
        self._build_transcript_tab(self.tabs.tab("Transcript / Tweet"))
        self._build_instagram_tab(self.tabs.tab("Instagram"))
        self._build_subtitle_tab(self.tabs.tab("Fix Subtitle"))

        # progress + log (always visible)
        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="both", expand=False, padx=16, pady=(0, 16))

        self.progress_bar = ctk.CTkProgressBar(bottom)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=12, pady=(12, 4))

        self.status_label = ctk.CTkLabel(bottom, text="Ready", text_color="#9aa0a6", anchor="w")
        self.status_label.pack(fill="x", padx=12)

        self.log_box = ctk.CTkTextbox(bottom, height=180, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.log_box.configure(state="disabled")
        for level, color in LEVEL_COLOR.items():
            self.log_box.tag_config(level, foreground=color)

    def _build_download_tab(self, tab):
        ctk.CTkLabel(tab, text="Video or playlist URL").pack(anchor="w", padx=12, pady=(12, 0))
        self.url_entry = ctk.CTkEntry(tab, placeholder_text="https://www.youtube.com/watch?v=...")
        self.url_entry.pack(fill="x", padx=12, pady=(2, 10))

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=12)
        ctk.CTkLabel(row, text="Quality").pack(side="left")
        self.quality_var = ctk.StringVar(value="1080p  FHD")
        quality_labels = [label for _, (label, _, _) in config.QUALITY_OPTIONS.items()]
        self._quality_map = {label: key for key, (label, _, _) in config.QUALITY_OPTIONS.items()}
        ctk.CTkOptionMenu(row, values=quality_labels, variable=self.quality_var, width=200).pack(side="left", padx=10)

        self.playlist_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row, text="This is a playlist", variable=self.playlist_var).pack(side="left", padx=20)

        self.transcript_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row, text="Also extract transcript", variable=self.transcript_var).pack(side="left", padx=6)

        self.download_btn = ctk.CTkButton(tab, text="Download", command=self._on_download_click)
        self.download_btn.pack(anchor="w", padx=12, pady=14)

    def _build_resume_tab(self, tab):
        ctk.CTkLabel(tab, text="Playlists with saved progress").pack(anchor="w", padx=12, pady=(12, 4))
        self.resume_list = ttk.Treeview(tab, columns=("done", "url"), show="headings", height=10)
        self.resume_list.heading("done", text="Done")
        self.resume_list.heading("url", text="Playlist URL")
        self.resume_list.column("done", width=70, anchor="center")
        self.resume_list.column("url", width=650)
        self.resume_list.pack(fill="x", padx=12, pady=4)

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(row, text="Refresh", command=self._refresh_resume_list, width=100).pack(side="left")
        ctk.CTkButton(row, text="Resume Selected", command=self._on_resume_click).pack(side="left", padx=10)
        self._refresh_resume_list()

    def _build_transcript_tab(self, tab):
        ctk.CTkLabel(tab, text="YouTube video or Twitter/X URL").pack(anchor="w", padx=12, pady=(12, 0))
        self.tt_entry = ctk.CTkEntry(tab, placeholder_text="https://...")
        self.tt_entry.pack(fill="x", padx=12, pady=(2, 10))
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=12)
        ctk.CTkButton(row, text="Extract Transcript (YouTube)", command=self._on_transcript_click).pack(side="left")
        ctk.CTkButton(row, text="Extract Tweet / Thread", command=self._on_tweet_click).pack(side="left", padx=10)

    def _build_instagram_tab(self, tab):
        ctk.CTkLabel(tab, text="Reel URL(s) — one per line").pack(anchor="w", padx=12, pady=(12, 0))
        self.ig_box = ctk.CTkTextbox(tab, height=140)
        self.ig_box.pack(fill="x", padx=12, pady=(2, 10))
        ctk.CTkButton(tab, text="Download Reel(s)", command=self._on_instagram_click).pack(anchor="w", padx=12)

    def _build_subtitle_tab(self, tab):
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(row, text="Search downloaded videos").pack(side="left")
        self.sub_search_entry = ctk.CTkEntry(row, width=300)
        self.sub_search_entry.pack(side="left", padx=10)
        ctk.CTkButton(row, text="Search", command=self._refresh_subtitle_list).pack(side="left")

        self.sub_list = ttk.Treeview(tab, columns=("status", "title"), show="headings", height=12)
        self.sub_list.heading("status", text="Arabic subtitle")
        self.sub_list.heading("title", text="Video title")
        self.sub_list.column("status", width=120, anchor="center")
        self.sub_list.column("title", width=600)
        self.sub_list.pack(fill="both", expand=True, padx=12, pady=4)

        ctk.CTkButton(tab, text="Fetch Subtitle for Selected", command=self._on_fetch_subtitle_click)\
            .pack(anchor="w", padx=12, pady=10)

    # ── logging / thread-safety ─────────────────────────────
    def log(self, msg: str, level: str = "info"):
        self._log_queue.put(("log", msg, level))

    def set_progress(self, fraction: float, status: str = None):
        self._log_queue.put(("progress", fraction, status))

    def _drain_log_queue(self):
        try:
            while True:
                item = self._log_queue.get_nowait()
                if item[0] == "log":
                    _, msg, level = item
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", f"{msg}\n", level)
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif item[0] == "progress":
                    _, fraction, status = item
                    self.progress_bar.set(max(0.0, min(1.0, fraction)))
                    if status:
                        self.status_label.configure(text=status)
        except queue.Empty:
            pass
        self.after(80, self._drain_log_queue)

    def _run_task(self, fn):
        """Run fn() in a background thread; disable buttons meanwhile."""
        if self._busy:
            self.log("A task is already running — please wait.", "warn")
            return
        self._busy = True
        self.status_label.configure(text="Working...")

        def worker():
            try:
                fn()
            except Exception as e:
                self.log(f"Unexpected error: {e}", "error")
            finally:
                self._busy = False
                self.set_progress(0.0, "Ready")

        threading.Thread(target=worker, daemon=True).start()

    def _video_progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                self.set_progress(downloaded / total, f"Downloading — {downloaded/1_048_576:.1f} / {total/1_048_576:.1f} MB")
        elif d["status"] == "finished":
            self.set_progress(1.0, "Finished")

    # ── button handlers ─────────────────────────────────────
    def _on_download_click(self):
        url = self.url_entry.get().strip()
        if not url:
            self.log("Enter a URL first.", "warn")
            return
        quality_key = self._quality_map[self.quality_var.get()]
        is_playlist = self.playlist_var.get()
        want_transcript = self.transcript_var.get()

        def task():
            if is_playlist:
                self.log("Reading playlist...", "info")
                info = youtube.read_playlist_info(url, log=self.log)
                if not info:
                    self.log("Could not read playlist.", "error")
                    return
                entries = [e for e in info.get("entries", []) if e]
                self.log(f"Playlist: {info.get('title')}  ({len(entries)} videos)", "info")
                result = youtube.download_playlist(
                    url, quality_key, entries, info.get("title", "playlist"),
                    log=self.log, on_video_progress=self._video_progress_hook,
                    on_item_start=lambda i, n, t: self.log(f"[{i}/{n}] {t}", "info"),
                )
                self.log(f"Finished — saved to {result['output_dir'].resolve()}", "success")
                if result["failed"]:
                    self.log(f"Failed ({len(result['failed'])}): " + ", ".join(result["failed"][:5]), "warn")
            else:
                out_dir = youtube.download_single(url, quality_key, log=self.log,
                                                    on_video_progress=self._video_progress_hook)
                if out_dir and want_transcript and quality_key != "6":
                    transcript.extract_transcript(url, log=self.log)

        self._run_task(task)

    def _refresh_resume_list(self):
        for row in self.resume_list.get_children():
            self.resume_list.delete(row)
        progress = load_progress()
        self._resume_urls = []
        for url, data in progress.items():
            done = data.get("done", [])
            if not done:
                continue
            self._resume_urls.append(url)
            self.resume_list.insert("", "end", values=(len(done), url[:80]))

    def _on_resume_click(self):
        sel = self.resume_list.selection()
        if not sel:
            self.log("Select a playlist first.", "warn")
            return
        idx = self.resume_list.index(sel[0])
        url = self._resume_urls[idx]
        progress = load_progress()
        done = progress.get(url, {}).get("done", [])
        key = done[0].rsplit("_", 1)[-1] if done and "_" in done[0] else "2"

        def task():
            info = youtube.read_playlist_info(url, log=self.log)
            if not info:
                self.log("Could not re-read playlist.", "error")
                return
            entries = [e for e in info.get("entries", []) if e]
            result = youtube.download_playlist(
                url, key, entries, info.get("title", "playlist"),
                log=self.log, on_video_progress=self._video_progress_hook,
                on_item_start=lambda i, n, t: self.log(f"[{i}/{n}] {t}", "info"),
            )
            self.log(f"Finished — saved to {result['output_dir'].resolve()}", "success")

        self._run_task(task)

    def _on_transcript_click(self):
        url = self.tt_entry.get().strip()
        if not url:
            self.log("Enter a URL first.", "warn")
            return
        self._run_task(lambda: transcript.extract_transcript(url, log=self.log))

    def _on_tweet_click(self):
        url = self.tt_entry.get().strip()
        if not url:
            self.log("Enter a URL first.", "warn")
            return
        self._run_task(lambda: social.extract_tweet(url, log=self.log))

    def _on_instagram_click(self):
        urls = [u.strip() for u in self.ig_box.get("1.0", "end").splitlines() if u.strip()]
        if not urls:
            self.log("Enter at least one reel URL.", "warn")
            return

        def task():
            result = youtube.download_instagram_reels(urls, log=self.log, on_video_progress=self._video_progress_hook)
            self.log(f"Done — {result['ok']}/{result['total']} downloaded. Saved to {result['output_dir'].resolve()}", "success")

        self._run_task(task)

    def _refresh_subtitle_list(self):
        for row in self.sub_list.get_children():
            self.sub_list.delete(row)
        query = self.sub_search_entry.get().strip()
        self._sub_matches = subtitles.find_downloaded_videos(config.DOWNLOAD_DIR, query)
        for path, video_id, title in self._sub_matches:
            tag = f"[{video_id}]"
            subs = {f for f in path.parent.iterdir() if f.suffix in config.SUB_EXTS and tag in f.name}
            status = "has Arabic" if subtitles.has_arabic_subtitle(subs) else "missing"
            self.sub_list.insert("", "end", values=(status, title[:70]))

    def _on_fetch_subtitle_click(self):
        sel = self.sub_list.selection()
        if not sel:
            self.log("Select a video first.", "warn")
            return
        idx = self.sub_list.index(sel[0])
        path, video_id, title = self._sub_matches[idx]
        url = f"https://www.youtube.com/watch?v={video_id}"

        def task():
            self.log(f"Fetching subtitle for: {title}", "info")
            subtitles.fetch_subtitles(url, path.parent, log=self.log)
            tag = f"[{video_id}]"
            subs = {f for f in path.parent.iterdir() if f.suffix in config.SUB_EXTS and tag in f.name}
            if subtitles.has_arabic_subtitle(subs):
                self.log("Done — Arabic subtitle saved.", "success")
            else:
                self.log("Still no Arabic subtitle available for this video.", "warn")
            self.after(0, self._refresh_subtitle_list)

        self._run_task(task)


if __name__ == "__main__":
    app = App()
    app.mainloop()
