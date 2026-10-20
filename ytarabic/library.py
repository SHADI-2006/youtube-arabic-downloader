"""
The downloads folder as a library: what's been downloaded (with its
subtitles), saved transcripts, and leftover partial files that can be
cleaned up. Paths cross the API as forward-slash strings relative to
DOWNLOAD_DIR — resolve() is the single gate that turns one back into a
real path, refusing anything outside the downloads folder.
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from . import config
from .config import AUDIO_EXTS, MIN_VIDEO_BYTES, SUB_EXTS, VALID_VIDEO_EXTS
from .subtitles import is_arabic_subtitle, read_subtitle_source, sub_lang

LogFn = Callable[[str, str], None]

MEDIA_EXTS = VALID_VIDEO_EXTS | AUDIO_EXTS
TEXT_EXTS  = {".txt", ".md"}

_ID_TAG_RE    = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
_FORMAT_RE    = re.compile(r"\.f\d+(?:-\d+)?$")          # "Title [id].f617" — a pre-merge stream
_PARTIAL_RE   = re.compile(r"\.(?:part(?:-Frag\d+)?(?:\.part)?|ytdl|temp|embedding)$", re.IGNORECASE)
_BASE_SPLIT_RE = re.compile(r"\.(?:f\d+(?:-\d+)?|part|temp|ytdl|embedding)(?:[.-]|$)", re.IGNORECASE)


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


def root() -> Path:
    return config.DOWNLOAD_DIR.resolve()


def rel(path: Path) -> str:
    return path.resolve().relative_to(root()).as_posix()


def resolve(rel_path: str) -> Path:
    """A path from the browser → a real path inside DOWNLOAD_DIR.
    Raises ValueError for anything that escapes it (../, absolute paths,
    other drives)."""
    if not rel_path:
        raise ValueError("empty path")
    p = (root() / rel_path).resolve()
    if p != root() and root() not in p.parents:
        raise ValueError("path outside the downloads folder")
    return p


def _is_hidden(path: Path) -> bool:
    try:
        parts = path.relative_to(root()).parts
    except ValueError:
        return True
    return any(part.startswith(".") for part in parts)


def _walk():
    base = root()
    if not base.exists():
        return
    for f in base.rglob("*"):
        if f.is_file() and not _is_hidden(f):
            yield f


def parse_media_name(path: Path) -> tuple:
    """(video_id or None, title) from "Title [id].ext"."""
    m = _ID_TAG_RE.search(path.stem)
    if m:
        return m.group(1), path.stem[:m.start()].strip() or path.stem
    return None, path.stem


def _is_final_media(f: Path) -> bool:
    return f.suffix.lower() in MEDIA_EXTS and not _is_leftover(f)


def _subtitle_entry(sub: Path) -> dict:
    lang = sub_lang(sub) or "?"
    return {
        "path": rel(sub),
        "lang": lang,
        "is_arabic": is_arabic_subtitle(sub),
        "source": read_subtitle_source(sub) if is_arabic_subtitle(sub) else None,
        "ext": sub.suffix.lower().lstrip("."),
    }


def subtitles_for(media: Path, siblings: Optional[list] = None) -> list:
    """Subtitle files that belong to `media` — same folder, and either the
    same [video_id] tag (survives the title changing on YouTube between
    downloading the video and fetching its subtitle later) or, for files
    without one, the same filename stem plus a language code
    ("Title.ar.srt"). Arabic first."""
    siblings = siblings if siblings is not None else list(media.parent.iterdir())
    video_id = parse_media_name(media)[0]
    if video_id:
        tag = f"[{video_id}]"
        belongs = lambda s: tag in s.name
    else:
        prefix = media.stem + "."
        belongs = lambda s: s.name.startswith(prefix)
    subs = [s for s in siblings if s.suffix.lower() in SUB_EXTS and belongs(s)]
    subs.sort(key=lambda s: (not is_arabic_subtitle(s), (sub_lang(s) or "") != "ar",
                             s.suffix.lower() != ".srt", s.name))
    return subs


def scan(query: str = "") -> dict:
    """Every finished download, newest first, plus totals."""
    by_folder = defaultdict(list)
    for f in _walk():
        by_folder[f.parent].append(f)

    items = []
    q = query.strip().lower()
    for folder, files in by_folder.items():
        for f in files:
            if not _is_final_media(f):
                continue
            st = f.stat()
            if st.st_size < MIN_VIDEO_BYTES and f.suffix.lower() in VALID_VIDEO_EXTS:
                continue
            video_id, title = parse_media_name(f)
            if q and q not in f.name.lower():
                continue
            subs = [_subtitle_entry(s) for s in subtitles_for(f, files)]
            items.append({
                "path": rel(f),
                "folder": rel(folder) if folder != root() else "",
                "title": title,
                "video_id": video_id,
                "ext": f.suffix.lower().lstrip("."),
                "is_audio": f.suffix.lower() in AUDIO_EXTS,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "subtitles": subs,
                "has_arabic": any(s["is_arabic"] for s in subs),
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg" if video_id else None,
            })
    items.sort(key=lambda i: i["mtime"], reverse=True)
    return {
        "items": items,
        "total_size": sum(i["size"] for i in items),
        "count": len(items),
    }


# ─────────────────────────────────────────────
#  Leftover partial files
# ─────────────────────────────────────────────
def _is_leftover(f: Path) -> bool:
    # "….part", "….part-Frag12.part", "….ytdl", and "Title [id].temp.mp4"
    # (yt-dlp's merge output before its final rename) / our own
    # ".embedding" temp file
    if ".part-Frag" in f.name or _PARTIAL_RE.search(f.name) or _PARTIAL_RE.search(f.stem):
        return True
    # "Title [id].f617.mp4" — one stream of a download that was merged
    # (or meant to be merged) into the final "Title [id].mp4"
    return f.suffix.lower() in MEDIA_EXTS and bool(_FORMAT_RE.search(f.stem))


def _leftover_base(f: Path) -> str:
    m = _BASE_SPLIT_RE.search(f.name)
    return f.name[:m.start()] if m else f.stem


def find_leftovers() -> dict:
    """
    Partial / intermediate files yt-dlp left behind, split in two:
      junk       — the finished file for the same video is right there, so
                   these are pure leftovers (e.g. the separate video stream
                   of an interrupted-then-resumed download).
      unfinished — no finished file yet: a download that was stopped and
                   could still be resumed. Only deleted on request.
    """
    by_folder = defaultdict(list)
    for f in _walk():
        by_folder[f.parent].append(f)

    junk, unfinished = [], []
    for folder, files in by_folder.items():
        finals = [f for f in files if _is_final_media(f) and not _is_leftover(f)]
        final_ids = {parse_media_name(f)[0] for f in finals} - {None}
        final_stems = {f.stem for f in finals}
        for f in files:
            if not _is_leftover(f):
                continue
            vid = parse_media_name(Path(_leftover_base(f) + ".x"))[0]
            done = (vid in final_ids) if vid else (_leftover_base(f) in final_stems)
            entry = {"path": rel(f), "size": f.stat().st_size, "name": f.name}
            (junk if done else unfinished).append(entry)

    return {
        "junk": junk,
        "unfinished": unfinished,
        "junk_bytes": sum(e["size"] for e in junk),
        "unfinished_bytes": sum(e["size"] for e in unfinished),
    }


def cleanup(include_unfinished: bool = False, log: LogFn = _default_log) -> dict:
    found = find_leftovers()
    targets = found["junk"] + (found["unfinished"] if include_unfinished else [])
    removed, freed = 0, 0
    for entry in targets:
        try:
            p = resolve(entry["path"])
            size = p.stat().st_size
            p.unlink()
            removed += 1
            freed += size
        except (OSError, ValueError) as e:
            log(f"Couldn't remove {entry['name']}: {e}", "warn")
    return {"removed": removed, "freed": freed}


# ─────────────────────────────────────────────
#  Saved transcripts / X threads / summaries
# ─────────────────────────────────────────────
def summary_path(transcript: Path, lang: str) -> Path:
    return transcript.with_name(transcript.stem + f".summary.{lang}.md")


def _transcript_title(path: Path, head: str) -> str:
    m = re.search(r"^Title\s*:\s*(.+)$", head, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r"^Author\s*:\s*(.+)$", head, re.MULTILINE)
    if m:
        return f"X — {m.group(1).strip()}"
    return path.stem


def list_transcripts() -> list:
    """Transcripts (transcript_*.txt) and X threads (tweet_*/transcript.txt),
    newest first, with which summaries exist for each."""
    out = []
    for f in _walk():
        if f.suffix.lower() != ".txt":
            continue
        is_tweet = f.name == "transcript.txt" and f.parent.name.startswith("tweet_")
        if not (f.name.startswith("transcript_") or is_tweet):
            continue
        try:
            head = f.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            continue
        words = re.search(r"^Words\s*:\s*([\d,]+)", head, re.MULTILINE)
        url = re.search(r"^URL\s*:\s*(\S+)", head, re.MULTILINE)
        out.append({
            "path": rel(f),
            "kind": "tweet" if is_tweet else "transcript",
            "title": _transcript_title(f, head),
            "words": int(words.group(1).replace(",", "")) if words else None,
            "url": url.group(1) if url else None,
            "mtime": f.stat().st_mtime,
            "summaries": {lang: rel(summary_path(f, lang))
                          for lang in ("ar", "en") if summary_path(f, lang).exists()},
        })
    out.sort(key=lambda t: t["mtime"], reverse=True)
    return out
