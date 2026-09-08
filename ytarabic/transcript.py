"""Transcript extraction — plain-text English transcript for AI analysis."""

import json
import re
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from .config import DOWNLOAD_DIR
from .utils import fmt_time
from .youtube import base_opts

LogFn = Callable[[str, str], None]


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


def _parse_json3(data: str, chapters: list) -> str:
    """Parse YouTube json3 subtitles, split into chapters if provided."""
    try:
        obj = json.loads(data)
    except Exception:
        return ""
    events = obj.get("events", [])

    if not chapters:
        lines, seen = [], set()
        for ev in events:
            line = "".join(s.get("utf8", "") for s in ev.get("segs", [])).strip()
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line and line != "\n" and line not in seen:
                seen.add(line)
                lines.append(line)
        return "\n".join(lines)

    chapter_lines: dict = {i: [] for i in range(len(chapters))}
    seen_global: set = set()
    for ev in events:
        t_sec = ev.get("tStartMs", 0) / 1000.0
        line  = "".join(s.get("utf8", "") for s in ev.get("segs", [])).strip()
        line  = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line == "\n":
            continue
        ch_idx = 0
        for i, ch in enumerate(chapters):
            if t_sec >= ch["start_time"]:
                ch_idx = i
            else:
                break
        if line not in seen_global:
            seen_global.add(line)
            chapter_lines[ch_idx].append(line)

    parts = []
    for i, ch in enumerate(chapters):
        header = f"\n{'─'*50}\n▶ Chapter {i+1}: {ch['title']}  [{fmt_time(ch['start_time'])}]\n{'─'*50}"
        body   = "\n".join(chapter_lines[i]) if chapter_lines[i] else "  (no transcript for this section)"
        parts.append(header + "\n" + body)
    return "\n".join(parts)


def _parse_vtt_text(data: str, chapters: list) -> str:
    """Parse VTT subtitle text, split into chapters if provided."""
    cues = []
    lines = data.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            time_match = re.match(r"(\d+):(\d+):(\d+)[.,](\d+)", line) \
                         or re.match(r"(\d+):(\d+)[.,](\d+)", line)
            start_sec = 0.0
            if time_match:
                g = time_match.groups()
                if len(g) == 4:
                    start_sec = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
                else:
                    start_sec = int(g[0]) * 60 + int(g[1]) + int(g[2]) / 1000
            i += 1
            text_parts = []
            while i < len(lines) and lines[i].strip():
                clean = re.sub(r"<[^>]+>", "", lines[i]).strip()
                if clean:
                    text_parts.append(clean)
                i += 1
            if text_parts:
                cues.append((start_sec, " ".join(text_parts)))
        i += 1

    if not chapters:
        seen, result = set(), []
        for _, text in cues:
            if text not in seen:
                seen.add(text)
                result.append(text)
        return "\n".join(result)

    chapter_lines: dict = {i: [] for i in range(len(chapters))}
    seen_global: set = set()
    for t_sec, text in cues:
        ch_idx = 0
        for i, ch in enumerate(chapters):
            if t_sec >= ch["start_time"]:
                ch_idx = i
            else:
                break
        if text not in seen_global:
            seen_global.add(text)
            chapter_lines[ch_idx].append(text)

    parts = []
    for i, ch in enumerate(chapters):
        header = f"\n{'─'*50}\n▶ Chapter {i+1}: {ch['title']}  [{fmt_time(ch['start_time'])}]\n{'─'*50}"
        body   = "\n".join(chapter_lines[i]) if chapter_lines[i] else "  (no transcript for this section)"
        parts.append(header + "\n" + body)
    return "\n".join(parts)


def extract_transcript(url: str, log: LogFn = _default_log) -> Optional[Path]:
    """
    Extract an English transcript from YouTube subtitle tracks, split by
    chapters if available. Saves a .txt file under DOWNLOAD_DIR and
    returns its path, or None on failure.
    """
    log("Fetching video info...", "info")
    try:
        with yt_dlp.YoutubeDL({**base_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        log(f"Error: {e}", "error")
        return None
    if not info:
        log("Could not fetch video info.", "error")
        return None

    title      = info.get("title", "Unknown Title")
    channel    = info.get("uploader", info.get("channel", "Unknown Channel"))
    duration_s = info.get("duration", 0)
    upload_ts  = info.get("upload_date", "")
    view_count = info.get("view_count", 0)
    video_url  = info.get("webpage_url", url)
    chapters   = info.get("chapters") or []

    upload_date = (f"{upload_ts[:4]}-{upload_ts[4:6]}-{upload_ts[6:]}"
                   if len(upload_ts) == 8 else upload_ts or "Unknown")
    mins, secs   = divmod(int(duration_s or 0), 60)
    hrs, mins    = divmod(mins, 60)
    duration_str = f"{hrs}h {mins}m {secs}s" if hrs else f"{mins}m {secs}s"

    if chapters:
        log(f"{len(chapters)} chapters found", "success")
    else:
        log("No chapters — transcript will be continuous", "warn")

    subs_dict = info.get("subtitles", {})
    auto_dict = info.get("automatic_captions", {})

    chosen_lang, chosen_source = None, None
    for lang in ["en", "en-orig"] + sorted(subs_dict):
        if lang.startswith("en") and lang in subs_dict:
            chosen_lang, chosen_source = lang, "manual"
            break
    if not chosen_lang:
        for lang in ["en", "en-orig"] + sorted(auto_dict):
            if lang.startswith("en") and lang in auto_dict:
                chosen_lang, chosen_source = lang, "auto-generated"
                break
    if not chosen_lang:
        log("No English subtitles available.", "warn")
        return None
    log(f"Using {chosen_lang} ({chosen_source})", "success")

    track_list = (subs_dict if chosen_source == "manual" else auto_dict)[chosen_lang]
    sub_url, sub_fmt = None, None
    for preferred in ("json3", "vtt", "ttml", "srv3", "srv2", "srv1"):
        for entry in track_list:
            if entry.get("ext") == preferred:
                sub_url, sub_fmt = entry["url"], preferred
                break
        if sub_url:
            break
    if not sub_url and track_list:
        sub_url = track_list[0].get("url")
        sub_fmt = track_list[0].get("ext", "unknown")
    if not sub_url:
        log("No subtitle URL found.", "error")
        return None

    try:
        req = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log(f"Failed to fetch subtitle: {e}", "error")
        return None

    raw_text = _parse_json3(raw_data, chapters) if sub_fmt == "json3" else _parse_vtt_text(raw_data, chapters)
    if not raw_text.strip():
        log("Transcript is empty after parsing.", "error")
        return None

    word_count = len(raw_text.split())
    ch_summary = ""
    if chapters:
        ch_lines = [f"  {'─'*40}"]
        for i, ch in enumerate(chapters, 1):
            ch_lines.append(f"  {i:>2}. [{fmt_time(ch['start_time'])}]  {ch['title']}")
        ch_lines.append(f"  {'─'*40}\n")
        ch_summary = "\n".join(ch_lines) + "\n"

    header = (
        f"=== YOUTUBE VIDEO TRANSCRIPT ===\n"
        f"Title    : {title}\n"
        f"Channel  : {channel}\n"
        f"Date     : {upload_date}\n"
        f"Duration : {duration_str}\n"
        f"Views    : {view_count:,}\n"
        f"URL      : {video_url}\n"
        f"Subtitles: {chosen_lang} ({chosen_source})\n"
        f"Chapters : {len(chapters) if chapters else 'none'}\n"
        f"Words    : {word_count:,}\n"
        f"================================\n\n"
    )
    if ch_summary:
        header += "CHAPTER INDEX:\n" + ch_summary

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:60].strip()
    out_path   = DOWNLOAD_DIR / f"transcript_{upload_date}_{safe_title}.txt"
    out_path.write_text(header + raw_text, encoding="utf-8")

    log(f"Transcript saved: {out_path}  ({word_count:,} words)", "success")
    return out_path
