"""FFmpeg-based helpers for finished downloads: embedding subtitles into
the video file, and serving subtitles to a browser player as WebVTT."""

import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .config import HAS_FFMPEG, SUB_EXTS, UTF8_BOM

LogFn = Callable[[str, str], None]

_SRT_TIME_RE = re.compile(r"(\d{1,2}:\d{2}:\d{2}),(\d{3})")

# Subtitle codec each container accepts for a soft (switchable) track
_SUB_CODEC = {".mp4": "mov_text", ".mkv": "srt", ".webm": "webvtt"}
_ISO639_2 = {"ar": "ara", "en": "eng"}


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


def read_text(path: Path) -> str:
    return path.read_bytes().lstrip(UTF8_BOM).decode("utf-8", errors="replace")


def srt_to_vtt(text: str) -> str:
    """SRT → WebVTT: the timestamps' decimal comma becomes a dot, and the
    WEBVTT header goes on top. Cue numbers are valid VTT cue ids as-is."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    return "WEBVTT\n\n" + _SRT_TIME_RE.sub(r"\1.\2", text.strip()) + "\n"


def subtitle_as_vtt(path: Path) -> Optional[str]:
    """Any subtitle file as WebVTT text for a <track> element."""
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        text = read_text(path)
        return text if text.lstrip().startswith("WEBVTT") else "WEBVTT\n\n" + text
    if suffix == ".srt":
        return srt_to_vtt(read_text(path))
    if suffix in SUB_EXTS and HAS_FFMPEG:   # .ass / .ssa
        try:
            out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "webvtt", "-"],
                                 capture_output=True, timeout=30)
            if out.returncode == 0:
                return out.stdout.decode("utf-8", errors="replace")
        except Exception:
            pass
    return None


def embed_subtitles(video: Path, subs: list, log: LogFn = _default_log) -> bool:
    """
    Mux `subs` [(path, lang_code)] into `video` as soft subtitle tracks
    (switchable on/off in any player — not burned into the picture), the
    first one marked default. Streams are copied, never re-encoded, so it
    takes seconds even for a long video. Any subtitle tracks the file
    already had are replaced, so running it again doesn't pile up
    duplicates. The original file is only replaced once FFmpeg succeeds.
    """
    if not HAS_FFMPEG:
        log("Embedding subtitles needs FFmpeg — it isn't installed.", "warn")
        return False
    codec = _SUB_CODEC.get(video.suffix.lower())
    if not codec:
        log(f"Can't embed subtitles into a {video.suffix} file.", "warn")
        return False
    subs = [(Path(p), lang) for p, lang in subs if Path(p).exists()]
    if not subs:
        log("No subtitle file to embed.", "warn")
        return False

    tmp = video.with_name(video.stem + ".embedding" + video.suffix)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video)]
    for path, _ in subs:
        cmd += ["-i", str(path)]
    cmd += ["-map", "0", "-map", "-0:s"]
    for i in range(len(subs)):
        cmd += ["-map", str(i + 1)]
    cmd += ["-c", "copy", "-c:s", codec]
    for i, (_, lang) in enumerate(subs):
        base = (lang or "").split("-")[0].lower()
        cmd += [f"-metadata:s:s:{i}", f"language={_ISO639_2.get(base, base or 'und')}",
                f"-metadata:s:s:{i}", f"title={'العربية' if base == 'ar' else (lang or 'Subtitle')}",
                f"-disposition:s:{i}", "default" if i == 0 else "0"]
    cmd.append(str(tmp))

    names = ", ".join(lang or "?" for _, lang in subs)
    log(f"Embedding subtitles ({names}) into the video file...", "info")
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=1800)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log(f"Embedding failed: {e}", "error")
        return False
    if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        err = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        log(f"Embedding failed: {err[-1] if err else 'ffmpeg error'}", "error")
        return False
    try:
        os.replace(tmp, video)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        log(f"Embedding failed — couldn't replace the video file (is it open in a player?): {e}", "error")
        return False
    log(f"Subtitles embedded into {video.name}", "success")
    return True


MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".webm": "video/webm",
    # Chrome/Edge play Matroska with the codecs YouTube uses (VP9/AV1/H.264
    # + Opus/AAC) when it's labelled as WebM — WebM *is* a Matroska subset.
    ".mkv": "video/webm",
    ".mp3": "audio/mpeg",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
}
