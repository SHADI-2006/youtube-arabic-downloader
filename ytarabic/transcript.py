"""Transcript extraction — plain-text transcript for reading or AI analysis."""

import json
import re
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from . import settings
from .config import DOWNLOAD_DIR
from .utils import fmt_time, safe_file_stem
from .youtube import base_opts, clean_error

LogFn = Callable[[str, str], None]


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


# ─────────────────────────────────────────────
#  Parsing: subtitle track → [(start_seconds, text)]
# ─────────────────────────────────────────────
def _cues_from_json3(data: str) -> list:
    try:
        obj = json.loads(data)
    except Exception:
        return []
    cues = []
    for ev in obj.get("events", []):
        line = "".join(s.get("utf8", "") for s in ev.get("segs", []) or []).strip()
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            cues.append((ev.get("tStartMs", 0) / 1000.0, line))
    return cues


def _cues_from_vtt(data: str) -> list:
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
    return cues


def _render(cues: list, chapters: list, timestamps: bool = False) -> str:
    """Cues → text, de-duplicated (auto-captions repeat each line as it
    scrolls), split into chapter sections if the video has chapters,
    optionally with a [m:ss] stamp in front of every line."""
    def fmt(t, text):
        return f"[{fmt_time(t)}] {text}" if timestamps else text

    seen, kept = set(), []
    for t, text in cues:
        if text not in seen:
            seen.add(text)
            kept.append((t, text))

    if not chapters:
        return "\n".join(fmt(t, text) for t, text in kept)

    chapter_lines: dict = {i: [] for i in range(len(chapters))}
    for t, text in kept:
        ch_idx = 0
        for i, ch in enumerate(chapters):
            if t >= ch["start_time"]:
                ch_idx = i
            else:
                break
        chapter_lines[ch_idx].append(fmt(t, text))

    parts = []
    for i, ch in enumerate(chapters):
        header = f"\n{'─'*50}\n▶ Chapter {i+1}: {ch['title']}  [{fmt_time(ch['start_time'])}]\n{'─'*50}"
        body   = "\n".join(chapter_lines[i]) if chapter_lines[i] else "  (no transcript for this section)"
        parts.append(header + "\n" + body)
    return "\n".join(parts)


def _parse_json3(data: str, chapters: list, timestamps: bool = False) -> str:
    """Parse YouTube json3 subtitles, split into chapters if provided."""
    return _render(_cues_from_json3(data), chapters, timestamps)


def _parse_vtt_text(data: str, chapters: list, timestamps: bool = False) -> str:
    """Parse VTT subtitle text, split into chapters if provided."""
    return _render(_cues_from_vtt(data), chapters, timestamps)


# ─────────────────────────────────────────────
#  Which subtitle track to use
# ─────────────────────────────────────────────
def original_language(info: dict) -> Optional[str]:
    """The language the video is spoken in — yt-dlp's `language` field,
    or else read off YouTube's "<lang>-orig" speech-recognition track."""
    lang = info.get("language")
    if lang:
        return lang
    for code in (info.get("automatic_captions") or {}):
        if code.endswith("-orig"):
            return code[:-5]
    return None


def pick_track(info: dict, lang_pref: str = "auto") -> tuple:
    """
    (lang_code, source) of the subtitle track to build the transcript
    from, or (None, None). source is "manual", "auto-generated", or
    "YouTube auto-translated".
      en   — English: human-made, else YouTube's speech recognition
      ar   — Arabic: human-made, else Arabic speech recognition (Arabic
             videos), else YouTube's Arabic auto-translation
      auto — whatever the video is spoken in, falling back to English
    """
    manual = info.get("subtitles") or {}
    auto   = info.get("automatic_captions") or {}
    orig   = original_language(info)
    base_orig = (orig or "").split("-")[0]

    order = []   # (pool, code-or-prefix)
    if lang_pref == "ar":
        order += [("manual", "ar"), ("auto", "ar-orig"), ("auto", "ar")]
    if lang_pref == "auto" and base_orig and base_orig != "en":
        order += [("manual", base_orig), ("auto", f"{orig}-orig"), ("auto", orig)]
    if lang_pref in ("auto", "en"):
        order += [("manual", "en"), ("auto", "en"), ("auto", "en-orig")]
    if lang_pref == "auto":
        order += [("manual", code) for code in sorted(manual)]
        order += [("auto", code) for code in sorted(auto) if code.endswith("-orig")]

    for pool, code in order:
        if pool == "manual":
            matches = sorted((c for c in manual if c == code or c.startswith(code + "-")),
                             key=lambda c: (c != code, c))
            if matches:
                return matches[0], "manual"
        elif code in auto:
            spoken = code.endswith("-orig") or (base_orig and code.split("-")[0] == base_orig)
            return code, "auto-generated" if spoken or not base_orig else "YouTube auto-translated"
    return None, None


# ─────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────
def extract_transcript(url: str, log: LogFn = _default_log, lang: Optional[str] = None,
                       timestamps: Optional[bool] = None) -> Optional[Path]:
    """
    Extract a transcript from YouTube subtitle tracks, split by chapters
    if available. Saves a .txt file under DOWNLOAD_DIR and returns its
    path, or None on failure.
    lang: "auto" (the video's own language) | "en" | "ar" — default from
    settings, as is timestamps ([m:ss] before every line).
    """
    lang = lang or settings.get("transcript_lang")
    timestamps = settings.get("transcript_timestamps") if timestamps is None else timestamps

    log("Fetching video info...", "info")
    try:
        with yt_dlp.YoutubeDL({**base_opts(), "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        log(f"Error: {clean_error(e)}", "error")
        return None
    if not info:
        log("Could not fetch video info.", "error")
        return None

    title      = info.get("title") or "Unknown Title"
    channel    = info.get("uploader") or info.get("channel") or "Unknown Channel"
    duration_s = info.get("duration") or 0
    upload_ts  = info.get("upload_date") or ""
    view_count = info.get("view_count") or 0
    video_url  = info.get("webpage_url", url)
    chapters   = info.get("chapters") or []

    upload_date = (f"{upload_ts[:4]}-{upload_ts[4:6]}-{upload_ts[6:]}"
                   if len(upload_ts) == 8 else upload_ts or "Unknown")
    mins, secs   = divmod(int(duration_s), 60)
    hrs, mins    = divmod(mins, 60)
    duration_str = f"{hrs}h {mins}m {secs}s" if hrs else f"{mins}m {secs}s"

    if chapters:
        log(f"{len(chapters)} chapters found", "success")
    else:
        log("No chapters — transcript will be continuous", "warn")

    chosen_lang, chosen_source = pick_track(info, lang)
    if not chosen_lang:
        wanted = {"en": "English", "ar": "Arabic"}.get(lang, "")
        log(f"No {wanted + ' ' if wanted else ''}subtitles available for this video.", "warn")
        return None
    log(f"Using {chosen_lang} ({chosen_source})", "success")

    pool = info.get("subtitles") if chosen_source == "manual" else info.get("automatic_captions")
    track_list = (pool or {})[chosen_lang]
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log(f"Failed to fetch subtitle: {e}", "error")
        return None

    raw_text = (_parse_json3(raw_data, chapters, timestamps) if sub_fmt == "json3"
                else _parse_vtt_text(raw_data, chapters, timestamps))
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

    lang_tag = chosen_lang.split("-")[0]
    suffix   = "" if lang_tag == "en" else f" ({lang_tag})"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOWNLOAD_DIR / f"transcript_{upload_date}_{safe_file_stem(title)}{suffix}.txt"
    out_path.write_text(header + raw_text, encoding="utf-8")

    log(f"Transcript saved: {out_path}  ({word_count:,} words)", "success")
    return out_path
