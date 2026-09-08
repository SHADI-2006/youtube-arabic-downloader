#!/usr/bin/env python3
"""
ytarabic — command-line interface (rich-powered).

Requirements:  pip install -r requirements.txt
"""

import signal
import sys
from pathlib import Path

# Windows consoles often use a legacy codepage that can't encode every
# Unicode character a video/playlist title might contain — force UTF-8
# on stdout/stderr so unusual titles degrade to '?' instead of crashing.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn, DownloadColumn, Progress, TextColumn,
        TimeRemainingColumn, TransferSpeedColumn,
    )
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
except ImportError:
    print("ERROR: Install required libraries first:\n  pip install -r requirements.txt")
    sys.exit(1)

from ytarabic import config, social, subtitles, transcript, youtube
from ytarabic.progress_store import load_progress

console = Console()
LEVEL_STYLE = {"info": "cyan", "warn": "yellow", "error": "bold red", "success": "bold green"}


def log(msg: str, level: str = "info") -> None:
    console.print(f"  [{LEVEL_STYLE.get(level, 'white')}]{msg}[/{LEVEL_STYLE.get(level, 'white')}]")


def _handle_sigint(sig, frame):
    console.print("\n[yellow]Interrupted.[/yellow]")
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_sigint)


# ─────────────────────────────────────────────
#  Shared UI helpers
# ─────────────────────────────────────────────
def print_header():
    ffmpeg_str  = "[green]installed[/green]" if config.HAS_FFMPEG else "[yellow]not found[/yellow]"
    cookies_str = (f"[green]{Path(config.COOKIES_FILE).name}[/green]"
                   if config.COOKIES_FILE and Path(config.COOKIES_FILE).exists()
                   else "[yellow]not set (YT_COOKIES_FILE)[/yellow]")
    console.print(Panel.fit(
        "[bold cyan]YouTube / Instagram / X Downloader  —  Arabic subtitles[/bold cyan]\n"
        f"FFmpeg: {ffmpeg_str}    Cookies: {cookies_str}",
        border_style="cyan",
    ))


def choose_quality(url: str = "") -> str:
    sizes = youtube.get_all_sizes(url) if url else {}
    if not config.HAS_FFMPEG:
        log("FFmpeg not found — quality may be limited to 360p", "warn")

    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("#", width=3)
    table.add_column("Quality")
    table.add_column("Size", style="green")
    for key, (label, _, _) in config.QUALITY_OPTIONS.items():
        table.add_row(key, label, sizes.get(key, "?"))
    console.print(table)

    while True:
        choice = Prompt.ask("\n  Quality number (0 = back)", default="2")
        if choice == "0":
            return None
        if choice in config.QUALITY_OPTIONS:
            return choice
        log("Invalid choice.", "error")


def run_with_progress(action_label: str, fn, *args, **kwargs):
    """Run `fn` with a rich progress bar wired to yt-dlp's progress_hook."""
    with Progress(
        TextColumn("[cyan]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(action_label, total=None)

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                progress.update(task, total=total, completed=d.get("downloaded_bytes", 0))
            elif d["status"] == "finished":
                progress.update(task, completed=progress.tasks[0].total or 1)

        return fn(*args, on_video_progress=hook, **kwargs)


def collect_urls(action_label: str) -> list:
    urls = []
    while True:
        prompt = f"  URL {len(urls)+1} (0 = back)" if not urls else \
                 f"  URL {len(urls)+1}  (Enter = start {action_label} / 0 = back)"
        raw = Prompt.ask(prompt, default="")
        if raw == "0":
            return []
        if raw == "" and urls:
            return urls
        if raw == "" and not urls:
            log("Please enter at least one URL.", "warn")
            continue
        urls.append(raw)
        log(f"Added ({len(urls)} in queue)", "success")


def pause_return():
    Prompt.ask("\n  [yellow]Press Enter to return to menu[/yellow]", default="")


# ─────────────────────────────────────────────
#  Menu actions
# ─────────────────────────────────────────────
def action_download_single(url: str):
    quality_key = choose_quality(url)
    if not quality_key:
        return
    if not Confirm.ask("\n  Start download?", default=True):
        return
    result = run_with_progress("Downloading", youtube.download_single, url, quality_key, log=log)
    if result and quality_key != "6":
        if Confirm.ask("\n  Extract transcript too?", default=False):
            transcript.extract_transcript(url, log=log)


def action_download_playlist(url: str):
    log("Reading playlist...", "info")
    info = youtube.read_playlist_info(url, log=log)
    if not info:
        log("Could not read playlist. Check the URL.", "error")
        return

    playlist_title = info.get("title", "playlist")
    entries = [e for e in info.get("entries", []) if e]
    console.print(f"\n  Playlist : [cyan]{playlist_title}[/cyan]\n  Total    : {len(entries)}\n")

    first_url = f"https://www.youtube.com/watch?v={entries[0]['id']}" if entries else ""
    quality_key = choose_quality(first_url)
    if not quality_key:
        return

    progress = load_progress()
    done_list = progress.get(url, {}).get("done", [])
    remaining = [e for e in entries if f"{e.get('id')}_{quality_key}" not in done_list]
    console.print(f"\n  Already done: {len(entries)-len(remaining)}  |  Remaining: {len(remaining)}")

    if remaining:
        with console.status("[yellow]Calculating total size..."):
            total_size = youtube.get_playlist_total_size(remaining, quality_key)
        console.print(f"  Total size : [green]{total_size}[/green]")
    else:
        log("All videos already downloaded!", "success")
        return

    if not Confirm.ask("\n  Start download?", default=True):
        return

    def on_item_start(idx, total, title):
        console.print(f"\n  [cyan][{idx}/{total}][/cyan] {title}")

    with Progress(
        TextColumn("[cyan]{task.description}"), BarColumn(), DownloadColumn(),
        TransferSpeedColumn(), TimeRemainingColumn(), console=console,
    ) as rprogress:
        task = rprogress.add_task("Downloading", total=None)

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                rprogress.update(task, total=total, completed=d.get("downloaded_bytes", 0))
            elif d["status"] == "finished":
                rprogress.update(task, completed=rprogress.tasks[0].total or 1)

        result = youtube.download_playlist(
            url, quality_key, entries, playlist_title, log=log,
            on_video_progress=hook, on_item_start=on_item_start,
        )

    console.print(f"\n  [green]Finished! Saved to: {result['output_dir'].resolve()}[/green]")
    if result["failed"]:
        console.print(f"\n  [yellow]Failed ({len(result['failed'])}):[/yellow]")
        for t in result["failed"]:
            console.print(f"    - {t[:60]}")


def action_resume():
    progress = load_progress()
    candidates = []
    for url, data in progress.items():
        done = data.get("done", [])
        if not done:
            continue
        key = done[0].rsplit("_", 1)[-1] if "_" in done[0] else "2"
        candidates.append((url, data, key))
    if not candidates:
        log("No resumable downloads found.", "warn")
        return

    table = Table(header_style="bold cyan", box=None)
    table.add_column("#"); table.add_column("Quality"); table.add_column("Done"); table.add_column("URL")
    for i, (url, data, key) in enumerate(candidates, 1):
        qlabel = config.QUALITY_OPTIONS.get(key, ("?",))[0]
        table.add_row(str(i), qlabel, str(len(data.get("done", []))), url[:55])
    console.print(table)

    choice = Prompt.ask("\n  Pick number (0 = back)", default="0")
    if choice == "0" or not choice.isdigit() or not (1 <= int(choice) <= len(candidates)):
        return
    url, _, key = candidates[int(choice) - 1]

    info = youtube.read_playlist_info(url, log=log)
    if not info:
        log("Could not re-read playlist.", "error")
        return
    entries = [e for e in info.get("entries", []) if e]
    result = run_with_progress(
        "Downloading", youtube.download_playlist, url, key, entries,
        info.get("title", "playlist"), log=log,
    )
    console.print(f"\n  [green]Finished! Saved to: {result['output_dir'].resolve()}[/green]")


def action_show_progress():
    progress = load_progress()
    if not progress:
        log("No saved progress yet.", "warn")
        return
    for url, data in progress.items():
        console.print(f"\n  URL : {url[:55]}")
        console.print(f"  Done: {len(data.get('done', []))} videos")
        for _, title in list(data.get("titles", {}).items())[-3:]:
            console.print(f"    - {title[:55]}")


def action_retry_subtitle():
    query = Prompt.ask("\n  Search video name (Enter = show all)", default="")
    matches = subtitles.find_downloaded_videos(config.DOWNLOAD_DIR, query)
    if not matches:
        log("No matching downloaded videos found.", "warn")
        return

    table = Table(header_style="bold cyan", box=None)
    table.add_column("#"); table.add_column("Status"); table.add_column("Title")
    for i, (path, video_id, title) in enumerate(matches, 1):
        tag = f"[{video_id}]"
        subs = {f for f in path.parent.iterdir() if f.suffix in config.SUB_EXTS and tag in f.name}
        status = "[green]has Arabic[/green]" if subtitles.has_arabic_subtitle(subs) else "[yellow]missing[/yellow]"
        table.add_row(str(i), status, title[:55])
    console.print(table)

    choice = Prompt.ask("\n  Pick number (0 = back)", default="0")
    if choice == "0" or not choice.isdigit() or not (1 <= int(choice) <= len(matches)):
        return

    path, video_id, title = matches[int(choice) - 1]
    url = f"https://www.youtube.com/watch?v={video_id}"
    console.print(f"\n  [cyan]Fetching subtitle for: {title}[/cyan]")
    subtitles.fetch_subtitles(url, path.parent, log=log)

    tag = f"[{video_id}]"
    subs = {f for f in path.parent.iterdir() if f.suffix in config.SUB_EXTS and tag in f.name}
    if subtitles.has_arabic_subtitle(subs):
        log("Done — Arabic subtitle saved.", "success")
    else:
        log("Still no Arabic subtitle available for this video.", "warn")


# ─────────────────────────────────────────────
#  Main menu
# ─────────────────────────────────────────────
MENU = [
    ("1", "Download single video"),
    ("2", "Download playlist  (resumes automatically)"),
    ("3", "Resume last download  (no URL needed)"),
    ("4", "Show saved progress"),
    ("5", "Extract transcript  (for AI analysis)"),
    ("6", "Extract tweet / X thread"),
    ("7", "Download Instagram reel(s)"),
    ("8", "Retry missing subtitle  (no re-download needed)"),
    ("0", "Exit"),
]


def main():
    while True:
        print_header()
        for key, label in MENU:
            console.print(f"  [yellow]{key}[/yellow]  {label}")
        choice = Prompt.ask("\n  Choice", default="0")

        if choice == "1":
            urls = collect_urls("download")
            for i, url in enumerate(urls, 1):
                if len(urls) > 1:
                    console.print(f"\n  [cyan][{i}/{len(urls)}] {url}[/cyan]")
                action_download_single(url)
            if urls:
                pause_return()
        elif choice == "2":
            url = Prompt.ask("  Playlist URL (0 = back)", default="0")
            if url != "0":
                action_download_playlist(url)
                pause_return()
        elif choice == "3":
            action_resume()
            pause_return()
        elif choice == "4":
            action_show_progress()
            pause_return()
        elif choice == "5":
            urls = collect_urls("extract transcript")
            for i, url in enumerate(urls, 1):
                if len(urls) > 1:
                    console.print(f"\n  [cyan][{i}/{len(urls)}] {url}[/cyan]")
                transcript.extract_transcript(url, log=log)
            if urls:
                pause_return()
        elif choice == "6":
            urls = collect_urls("extract tweet")
            for i, url in enumerate(urls, 1):
                if len(urls) > 1:
                    console.print(f"\n  [cyan][{i}/{len(urls)}] {url}[/cyan]")
                social.extract_tweet(url, log=log)
            if urls:
                pause_return()
        elif choice == "7":
            urls = collect_urls("download reel(s)")
            if urls:
                result = run_with_progress("Downloading", youtube.download_instagram_reels, urls, log=log)
                console.print(f"\n  [green]Done — {result['ok']}/{result['total']} downloaded.[/green]")
                console.print(f"  Saved to: [cyan]{result['output_dir'].resolve()}[/cyan]")
                pause_return()
        elif choice == "8":
            action_retry_subtitle()
            pause_return()
        elif choice == "0":
            console.print("  Bye!")
            break
        else:
            log("Invalid choice.", "error")


if __name__ == "__main__":
    main()
