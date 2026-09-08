"""
Arabic subtitle handling: fetching, RTL/encoding fixes, and the
translation priority chain (manual → Gemini → YouTube auto → Google).

Every function takes an optional `log(message, level)` callback instead
of printing directly, so the same logic can drive a CLI, a GUI, or a
test — `level` is one of "info" | "warn" | "error" | "success".
"""

import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from .config import (
    AR_TAGS, GEMINI_MODEL, GEMINI_RETRIES, GEMINI_RETRY_WAIT,
    HAS_FFMPEG, SUB_EXTS, SUBTITLES_EN, UTF8_BOM,
)
from .youtube import base_opts, build_subtitle_opts

LogFn = Callable[[str, str], None]


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


# ─────────────────────────────────────────────
#  RTL / encoding post-processing
# ─────────────────────────────────────────────
def _srt_fix_line_order(text: str) -> str:
    """
    In Arabic auto-generated subtitles, lines within a cue are often
    reversed (line 2 shown before line 1). This fixes the order.
    Only reverses when the block has exactly 2 lines of text.
    """
    blocks = text.strip().split("\n\n")
    fixed = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) >= 4:
            header  = lines[:2]
            content = lines[2:]
            content.reverse()
            fixed.append("\n".join(header + content))
        else:
            fixed.append(block)
    return "\n\n".join(fixed)


def _convert_to_srt(src: Path) -> Optional[Path]:
    """Convert a .vtt/.ass/.ssa file to .srt using FFmpeg."""
    if not HAS_FFMPEG or src.suffix.lower() == ".srt":
        return None
    dst = src.with_suffix(".srt")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), str(dst)],
            capture_output=True, timeout=30
        )
        if result.returncode == 0 and dst.exists():
            return dst
    except Exception:
        pass
    return None


def fix_subtitle_bom(directory: Path):
    """
    For every subtitle file in directory:
      1. Convert .vtt/.ass/.ssa → .srt  (Windows player compatibility)
      2. Fix reversed line order inside each cue  (Arabic auto-subs)
      3. Add UTF-8 BOM  (Arabic rendering in Windows)
    """
    if not directory.exists():
        return
    for f in list(directory.iterdir()):
        if f.suffix.lower() not in SUB_EXTS:
            continue
        try:
            if f.suffix.lower() in {".vtt", ".ass", ".ssa"}:
                srt_path = _convert_to_srt(f)
                if srt_path:
                    f.unlink()
                    f = srt_path
            if f.suffix.lower() == ".srt":
                raw  = f.read_bytes()
                text = raw.lstrip(UTF8_BOM).decode("utf-8", errors="replace")
                text = _srt_fix_line_order(text)
                f.write_bytes(UTF8_BOM + text.encode("utf-8"))
            else:
                raw = f.read_bytes()
                if not raw.startswith(UTF8_BOM):
                    f.write_bytes(UTF8_BOM + raw)
        except Exception:
            pass


def has_arabic_subtitle(files: set) -> bool:
    for f in files:
        name = f.name.lower()
        if f.suffix in SUB_EXTS and any(tag in name for tag in AR_TAGS):
            return True
    return False


# ─────────────────────────────────────────────
#  Translation engine 1 — Google Translate (free, no key, literal)
# ─────────────────────────────────────────────
TRANSLATE_CUES_PER_REQUEST = 25   # cues per Google Translate request
_CUE_SEP = "\n|||\n"


def translate_srt_to_arabic(src: Path, log: LogFn = _default_log) -> Optional[Path]:
    """
    Translate an English .srt to Arabic with Google Translate (free,
    via deep-translator — no API key needed). Keeps index/timestamp
    lines untouched, translates cue text only, in small batches.
    """
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        log("Translation skipped — run: pip install deep-translator", "warn")
        return None

    try:
        raw = src.read_bytes().lstrip(UTF8_BOM).decode("utf-8", errors="replace")
    except Exception:
        return None

    blocks = [b for b in raw.strip().split("\n\n") if b.strip()]
    if not blocks:
        return None

    parsed = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) < 3:
            parsed.append((lines, None))
        else:
            parsed.append((lines[:2], "\n".join(lines[2:]).strip()))

    translator = GoogleTranslator(source="en", target="ar")
    translated = [None] * len(parsed)
    text_idxs  = [i for i, (_, t) in enumerate(parsed) if t]

    log(f"Translating {len(text_idxs)} lines to Arabic (Google Translate)...", "info")
    for start in range(0, len(text_idxs), TRANSLATE_CUES_PER_REQUEST):
        batch = text_idxs[start:start + TRANSLATE_CUES_PER_REQUEST]
        chunk = _CUE_SEP.join(parsed[i][1] for i in batch)

        pieces = None
        try:
            result = translator.translate(chunk)
            candidate = [p.strip() for p in result.split(_CUE_SEP.strip())]
            if len(candidate) == len(batch):
                pieces = candidate
        except Exception:
            pieces = None

        if pieces is None:
            pieces = []
            for i in batch:
                try:
                    pieces.append(translator.translate(parsed[i][1]).strip())
                except Exception:
                    pieces.append(parsed[i][1])

        for i, piece in zip(batch, pieces):
            translated[i] = piece

    out_blocks = []
    for (header, original), new_text in zip(parsed, translated):
        out_blocks.append("\n".join(header + [new_text or original]) if original else "\n".join(header))

    name     = src.name
    dst_name = name[:-7] + ".ar.srt" if name.lower().endswith(".en.srt") else src.stem + ".ar.srt"
    dst      = src.parent / dst_name
    dst.write_bytes(UTF8_BOM + ("\n\n".join(out_blocks) + "\n").encode("utf-8"))
    return dst


# ─────────────────────────────────────────────
#  Translation engine 2 — Gemini (free tier, priority, best context)
# ─────────────────────────────────────────────
def translate_srt_to_arabic_gemini(src: Path, log: LogFn = _default_log) -> Optional[Path]:
    """
    Translate an English .srt to Arabic with Gemini (free tier, via
    google-genai). Sends the whole file in ONE request so the model
    reads full context and produces a naturally connected translation
    instead of isolated per-cue text. Retries transient server/
    connection errors; a 429 (request/quota limit) is reported clearly
    and NOT retried. Returns None if the SDK isn't installed,
    GEMINI_API_KEY isn't set, the limit was hit, or the response
    looks incomplete — callers should fall back to another engine.
    """
    import os
    try:
        from google import genai
    except ImportError:
        log("Gemini translation skipped — run: pip install google-genai", "warn")
        return None

    if not os.environ.get("GEMINI_API_KEY"):
        log("Gemini translation skipped — GEMINI_API_KEY not set", "warn")
        return None

    try:
        raw = src.read_bytes().lstrip(UTF8_BOM).decode("utf-8", errors="replace")
    except Exception:
        return None

    cue_count = raw.count("-->")
    if cue_count == 0:
        return None

    prompt = (
        "Translate this SRT subtitle file from English to Arabic.\n"
        "Rules:\n"
        "- Keep every cue number and timestamp line EXACTLY unchanged.\n"
        "- Translate only the subtitle text lines.\n"
        "- Read the whole file for context so the translation reads as one "
        "connected, natural passage across cues — not word-for-word in isolation.\n"
        "- Output ONLY the resulting SRT file. No explanation, no code fences.\n\n"
        f"{raw}"
    )

    client = genai.Client()
    result = None
    for attempt in range(1, GEMINI_RETRIES + 2):
        try:
            interaction = client.interactions.create(model=GEMINI_MODEL, input=prompt)
            result      = interaction.output_text.strip()
            break
        except Exception as e:
            status_code = getattr(e, "status_code", None) or getattr(e, "code", None)

            if status_code == 429:
                log("GEMINI LIMIT REACHED (HTTP 429) — free-tier request limit hit "
                    "(per-minute rate or free quota). Falling back to other sources.",
                    "error")
                return None

            is_transient = status_code is None or (isinstance(status_code, int) and status_code >= 500)
            if is_transient and attempt <= GEMINI_RETRIES:
                log(f"Gemini busy ({e}) — retry {attempt}/{GEMINI_RETRIES} "
                    f"in {GEMINI_RETRY_WAIT}s...", "warn")
                time.sleep(GEMINI_RETRY_WAIT)
                continue

            log(f"Gemini translation failed: {e}", "warn")
            return None

    if result is None:
        return None

    if result.startswith("```"):
        result = result.split("\n", 1)[1] if "\n" in result else result
        if result.rstrip().endswith("```"):
            result = result.rstrip()[:-3]
        result = result.strip()

    if result.count("-->") < cue_count * 0.9:
        log("Gemini output looked incomplete — falling back", "warn")
        return None

    name     = src.name
    dst_name = name[:-7] + ".ar.srt" if name.lower().endswith(".en.srt") else src.stem + ".ar.srt"
    dst      = src.parent / dst_name
    dst.write_bytes(UTF8_BOM + (result + "\n").encode("utf-8"))
    return dst


# ─────────────────────────────────────────────
#  Arabic subtitle discovery on YouTube (manual vs auto-translated)
# ─────────────────────────────────────────────
_AR_PRIORITY = ["ar", "ar-orig", "ar-SA", "ar-EG", "ar-AE", "ar-IQ"]


def arabic_lang_options(url: str) -> tuple:
    """
    Look up Arabic subtitle options in a single request. Returns
    (manual_lang, auto_lang):
      manual_lang — best real, human-authored Arabic subtitle language,
                    or None.
      auto_lang   — best YouTube-auto-translated/auto-generated Arabic
                    caption language, or None.
    Manual is always preferred over auto — a human translation beats
    any machine translation, YouTube's or ours.
    """
    try:
        with yt_dlp.YoutubeDL({**base_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return None, None

        def _best(pool: set) -> Optional[str]:
            for lang in _AR_PRIORITY:
                if lang in pool:
                    return lang
            for lang in sorted(pool):
                if lang.startswith("ar"):
                    return lang
            return None

        manual = set(info.get("subtitles", {}).keys())
        auto   = set(info.get("automatic_captions", {}).keys())
        return _best(manual), _best(auto)
    except Exception:
        return None, None


def is_youtube(url: str) -> bool:
    """Return True only for YouTube URLs — subtitles only make sense there."""
    return any(d in url for d in ("youtube.com", "youtu.be"))


# ─────────────────────────────────────────────
#  Main entry point — the full Arabic subtitle priority chain
# ─────────────────────────────────────────────
def fetch_subtitles(url: str, output_dir: Path, log: LogFn = _default_log):
    """
    Arabic subtitle priority (never raises — every step is best-effort):
      1. Real, human-authored Arabic subtitle — used as-is, nothing beats it.
      2. No manual Arabic: download English and translate with Gemini
         (priority engine — reads the whole file for natural, connected
         translation). A 429 (request/quota limit) is reported clearly.
      3. Gemini unavailable/failed: fall back to YouTube's own
         auto-translated Arabic captions (free, built-in).
      4. That's unavailable too: fall back to Google Translate
         (deep-translator) on the English text — always free, no key,
         last resort so a translation always happens.
    Silently skips non-YouTube URLs (Twitter, Instagram, etc.)
    """
    if not is_youtube(url):
        return

    manual_lang, auto_lang = arabic_lang_options(url)

    # 1) Real, human-made Arabic subtitle
    if manual_lang:
        log(f"Subtitle: {manual_lang} (manual)", "info")
        ar_opts = build_subtitle_opts(output_dir, [manual_lang])
        try:
            with yt_dlp.YoutubeDL(ar_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass
        subs = {f for f in output_dir.iterdir() if f.suffix in SUB_EXTS}
        if has_arabic_subtitle(subs):
            fix_subtitle_bom(output_dir)
            return

    # 2) No manual Arabic — download English as the source to translate
    log("No manual Arabic sub — downloading English to translate...", "info")
    before = {f for f in output_dir.iterdir() if f.suffix in SUB_EXTS} if output_dir.exists() else set()
    en_opts = build_subtitle_opts(output_dir, SUBTITLES_EN)
    try:
        with yt_dlp.YoutubeDL(en_opts) as ydl:
            ydl.download([url])
    except Exception:
        pass
    fix_subtitle_bom(output_dir)

    after       = {f for f in output_dir.iterdir() if f.suffix in SUB_EXTS} if output_dir.exists() else set()
    new_en_subs = {f for f in (after - before) if f.suffix == ".srt"}
    if not new_en_subs:
        return

    # 3) Gemini — priority translation engine
    remaining = []
    for f in new_en_subs:
        translated = translate_srt_to_arabic_gemini(f, log)
        if translated:
            log(f"Arabic translation saved (Gemini): {translated.name}", "success")
        else:
            remaining.append(f)
    if not remaining:
        return

    # 4) Gemini unavailable/failed — try YouTube's own auto-translated
    #    Arabic captions before falling back to our own Google Translate call
    if auto_lang:
        log(f"Trying YouTube's own Arabic translation ({auto_lang})...", "info")
        yt_ar_opts = build_subtitle_opts(output_dir, [auto_lang])
        try:
            with yt_dlp.YoutubeDL(yt_ar_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass
        fix_subtitle_bom(output_dir)
        subs = {f for f in output_dir.iterdir() if f.suffix in SUB_EXTS}
        if has_arabic_subtitle(subs):
            return

    # 5) Final fallback — Google Translate (deep-translator), always free
    for f in remaining:
        translated = translate_srt_to_arabic(f, log)
        if translated:
            log(f"Arabic translation saved (Google Translate): {translated.name}", "success")


# ─────────────────────────────────────────────
#  Retry a missing subtitle without re-downloading the video
# ─────────────────────────────────────────────
def find_downloaded_videos(download_dir: Path, query: str = "") -> list:
    """
    Scan download_dir recursively for already-downloaded YouTube videos
    (identified by the [video_id] tag every download embeds in its
    filename). Returns a list of (path, video_id, title) tuples,
    optionally filtered by a case-insensitive substring match.
    """
    import re
    from .config import VALID_VIDEO_EXTS

    results = []
    if not download_dir.exists():
        return results
    for f in download_dir.rglob("*"):
        if f.suffix.lower() not in VALID_VIDEO_EXTS:
            continue
        m = re.search(r"\[([A-Za-z0-9_-]{11})\]", f.stem)
        if not m:
            continue
        if query and query.lower() not in f.name.lower():
            continue
        video_id = m.group(1)
        title    = f.stem[:m.start()].strip()
        results.append((f, video_id, title))
    return results
