"""
Arabic subtitle handling: fetching, RTL/encoding fixes, and the
translation priority chain (manual → Gemini → YouTube auto → Google).

Every function takes an optional `log(message, level)` callback instead
of printing directly, so the same logic can drive a CLI, a GUI, or a
test — `level` is one of "info" | "warn" | "error" | "success".
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from .config import (
    AR_TAGS, GEMINI_MODEL, GEMINI_RETRIES, GEMINI_RETRY_WAIT, GEMINI_TIMEOUT,
    HAS_FFMPEG, SUB_EXTS, SUBTITLES_EN, UTF8_BOM,
)
from .errors import Cancelled
from .utils import extract_youtube_id
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


def _find_arabic_subtitle(files: set) -> Optional[Path]:
    for f in files:
        if f.suffix in SUB_EXTS and any(tag in f.name.lower() for tag in AR_TAGS):
            return f
    return None


def _mark_subtitle_source(ar_file: Optional[Path], source: str):
    """Write a tiny sidecar text file next to the Arabic subtitle recording
    which engine produced it. A different extension entirely (".source"),
    so no player ever sees it — it's only there so you can check later,
    without having watched the live log when the download happened."""
    if not ar_file:
        return
    try:
        Path(str(ar_file) + ".source").write_text(source, encoding="utf-8")
    except Exception:
        pass


# ─────────────────────────────────────────────
#  Translation engine 1 — Google Translate (free, no key, literal)
# ─────────────────────────────────────────────
TRANSLATE_CUES_PER_REQUEST = 25   # cues per Google Translate request
_CUE_SEP = "\n|||\n"


def _google_translate_srt_text(raw: str, log: LogFn = _default_log) -> Optional[str]:
    """Translate raw SRT text to Arabic with Google Translate (free, via
    deep-translator — no API key needed). Keeps index/timestamp lines
    untouched, translates cue text only, in small batches. Works on text
    directly (not a file) so it can also serve as a per-chunk fallback
    when a single Gemini chunk fails without discarding a whole file's
    worth of otherwise-successful Gemini translation."""
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        log("Translation skipped — run: pip install deep-translator", "warn")
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

    return "\n\n".join(out_blocks)


def translate_srt_to_arabic(src: Path, log: LogFn = _default_log) -> Optional[Path]:
    """Translate an English .srt file to Arabic with Google Translate —
    see _google_translate_srt_text for the actual translation logic."""
    try:
        raw = src.read_bytes().lstrip(UTF8_BOM).decode("utf-8", errors="replace")
    except Exception:
        return None

    result = _google_translate_srt_text(raw, log)
    if result is None:
        return None

    name     = src.name
    dst_name = name[:-7] + ".ar.srt" if name.lower().endswith(".en.srt") else src.stem + ".ar.srt"
    dst      = src.parent / dst_name
    dst.write_bytes(UTF8_BOM + (result + "\n").encode("utf-8"))
    return dst


_GEMINI_RETRY_DELAY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


def _gemini_error_detail(e: Exception) -> str:
    """The real message Google sent back (which quota metric, its limit,
    how long to wait) instead of guessing at the cause."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        msg = body.get("error", {}).get("message")
        if msg:
            return msg
    return str(e)


def _gemini_retry_delay(e: Exception) -> Optional[float]:
    """Seconds until the quota that tripped this 429 resets, if Google's
    error message states one (it does for the short per-minute burst
    limit, not for a fully exhausted daily quota)."""
    m = _GEMINI_RETRY_DELAY_RE.search(_gemini_error_detail(e))
    return float(m.group(1)) if m else None


GEMINI_CUES_PER_REQUEST = 150   # A long course can run 10+ hours / thousands
                                 # of cues — sending that as one request either
                                 # times out or gets silently truncated by the
                                 # model's own output-length ceiling. Chunking
                                 # keeps every request's output small and fast
                                 # regardless of the video's length, at the
                                 # cost of full-file context across chunk
                                 # boundaries (an acceptable tradeoff — still
                                 # far more natural than per-cue translation).


def _gemini_translate_chunk(client, chunk_text: str, chunk_cue_count: int,
                             log: LogFn) -> Optional[str]:
    """One chunked request, with the same 429/transient retry handling as
    before. Returns the translated SRT excerpt, or None to fall back."""
    prompt = (
        "Translate this SRT subtitle excerpt from English to Arabic.\n"
        "Rules:\n"
        "- Keep every cue number and timestamp line EXACTLY unchanged.\n"
        "- Translate only the subtitle text lines.\n"
        "- Read the whole excerpt for context so the translation reads as one "
        "connected, natural passage across cues — not word-for-word in isolation.\n"
        "- Output ONLY the resulting SRT excerpt. No explanation, no code fences.\n\n"
        f"{chunk_text}"
    )

    result = None
    for attempt in range(1, GEMINI_RETRIES + 2):
        try:
            interaction = client.interactions.create(
                model=GEMINI_MODEL, input=prompt, timeout=GEMINI_TIMEOUT,
            )
            result      = interaction.output_text.strip()
            break
        except Exception as e:
            status_code = getattr(e, "status_code", None) or getattr(e, "code", None)

            if status_code == 429:
                delay = _gemini_retry_delay(e)
                # A short stated delay means this is the per-minute burst
                # limit resetting, not the daily quota — worth one retry
                # instead of giving up on a video that would otherwise
                # translate fine a few seconds later.
                if delay is not None and delay <= 30 and attempt <= GEMINI_RETRIES:
                    wait = delay + 1
                    log(f"Gemini rate limit hit — resets in {wait:.0f}s, retrying "
                        f"({attempt}/{GEMINI_RETRIES})...", "warn")
                    time.sleep(wait)
                    continue
                log(f"GEMINI LIMIT REACHED (HTTP 429): {_gemini_error_detail(e)}",
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

    if result.count("-->") < chunk_cue_count * 0.9:
        log("Gemini output looked incomplete — falling back", "warn")
        return None

    return result


# ─────────────────────────────────────────────
#  Translation engine 2 — Gemini (free tier, priority, best context)
# ─────────────────────────────────────────────
def translate_srt_to_arabic_gemini(src: Path, log: LogFn = _default_log,
                                    should_stop: Optional[Callable[[], bool]] = None,
                                    youtube_fallback: Optional[Callable[[], Optional[list]]] = None) -> Optional[Path]:
    """
    Translate an English .srt to Arabic with Gemini (free tier, via
    google-genai), in chunks of GEMINI_CUES_PER_REQUEST cues so a long
    (multi-hour) video doesn't send one request too large to finish
    before it times out or gets truncated. Retries transient server/
    connection errors per chunk; a 429 with a short stated reset time
    is retried once.

    A chunk that still fails after retries (e.g. the free tier's daily
    quota runs out partway through a long video) is patched from
    another source for JUST that chunk instead of discarding every
    other chunk's already-successful Gemini translation — a 10-hour
    course can need a dozen-plus requests, and throwing away 11 good
    ones because the 12th hit a quota wall would waste both the quota
    already spent and the translation quality already gained.

    `youtube_fallback`, if given, is called at most once (lazily, only
    if a chunk actually fails) and should return YouTube's own
    auto-translated Arabic subtitle as a list of cue blocks aligned
    with this file's, or None. When it lines up (same cue count as the
    English source — otherwise a chunk's cue range can't be safely
    mapped across the two files), it's preferred over Google Translate
    for the failed chunk since YouTube's own translation is generally
    the better of the two. Google Translate is the last resort when
    that isn't available or doesn't line up. The ".source" sidecar
    records exactly which engine produced which part, e.g. "Gemini
    (11/12 parts) + YouTube auto-translate (1 part(s): 5)", so a mixed
    result is never silently misattributed as pure Gemini.

    Returns None only if nothing could be produced at all (SDK missing,
    GEMINI_API_KEY unset, or every fallback also failed for some
    chunk) — callers should then fall back to another engine for the
    whole file.
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

    blocks = [b for b in raw.strip().split("\n\n") if b.strip()]
    if not blocks:
        return None

    client          = genai.Client()
    translated      = []
    fallback_parts  = {}   # part number -> engine name, for the .source label
    yt_blocks       = "not fetched yet"   # lazy, fetched at most once
    chunk_starts    = list(range(0, len(blocks), GEMINI_CUES_PER_REQUEST))
    total_chunks    = len(chunk_starts)

    for i, start in enumerate(chunk_starts, 1):
        if should_stop and should_stop():
            raise Cancelled("stop requested")
        chunk_blocks = blocks[start:start + GEMINI_CUES_PER_REQUEST]
        chunk_text   = "\n\n".join(chunk_blocks)
        if total_chunks > 1:
            log(f"Translating with Gemini — part {i}/{total_chunks}...", "info")
        piece = _gemini_translate_chunk(client, chunk_text, chunk_text.count("-->"), log)

        if piece is None:
            if yt_blocks == "not fetched yet":
                yt_blocks = youtube_fallback() if youtube_fallback else None
            if yt_blocks is not None and len(yt_blocks) == len(blocks):
                log(f"Part {i}/{total_chunks}: using YouTube's own Arabic translation "
                    "for just this part...", "warn")
                piece = "\n\n".join(yt_blocks[start:start + GEMINI_CUES_PER_REQUEST])
                fallback_parts[i] = "YouTube auto-translate"
            else:
                log(f"Part {i}/{total_chunks}: falling back to Google Translate for "
                    "just this part...", "warn")
                piece = _google_translate_srt_text(chunk_text, log)
                if piece is None:
                    return None
                fallback_parts[i] = "Google Translate"

        translated.append(piece)

    result = "\n\n".join(translated)

    name     = src.name
    dst_name = name[:-7] + ".ar.srt" if name.lower().endswith(".en.srt") else src.stem + ".ar.srt"
    dst      = src.parent / dst_name
    dst.write_bytes(UTF8_BOM + (result + "\n").encode("utf-8"))

    if fallback_parts:
        gemini_n = total_chunks - len(fallback_parts)
        by_engine = {}
        for part, engine in fallback_parts.items():
            by_engine.setdefault(engine, []).append(part)
        pieces = [f"Gemini ({gemini_n}/{total_chunks} parts)"]
        for engine, parts in by_engine.items():
            pieces.append(f"{engine} ({len(parts)} part(s): {', '.join(map(str, sorted(parts)))})")
        source = " + ".join(pieces)
    else:
        source = "Gemini"
    _mark_subtitle_source(dst, source)
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
def fetch_subtitles(url: str, output_dir: Path, log: LogFn = _default_log,
                     should_stop: Optional[Callable[[], bool]] = None):
    """
    Arabic subtitle priority (never raises except Cancelled — every
    step is otherwise best-effort):
      1. Real, human-authored Arabic subtitle — used as-is, nothing beats it.
      2. No manual Arabic: download English and translate with Gemini
         (priority engine — reads the whole file for natural, connected
         translation). A 429 (request/quota limit) is reported clearly.
      3. Gemini unavailable/failed: fall back to YouTube's own
         auto-translated Arabic captions (free, built-in).
      4. That's unavailable too: fall back to Google Translate
         (deep-translator) on the English text — always free, no key,
         last resort so a translation always happens.
    should_stop(), if given, is checked before each tier and raises
    Cancelled to stop the whole chain (e.g. mid-translation) early.
    Silently skips non-YouTube URLs (Twitter, Instagram, etc.)
    """
    if not is_youtube(url):
        return

    def _check_stop():
        if should_stop and should_stop():
            raise Cancelled("stop requested")

    # Single downloads all share one "single/" folder, so scanning the
    # whole directory would pick up other videos' subtitle files too.
    # Scope every lookup to this video's own [id] tag instead.
    video_id = extract_youtube_id(url)
    tag = f"[{video_id}]" if video_id else None

    def _own_subs() -> set:
        if not output_dir.exists():
            return set()
        subs = {f for f in output_dir.iterdir() if f.suffix in SUB_EXTS}
        return {f for f in subs if tag is None or tag in f.name}

    def _fetch_youtube_translated_blocks(lang: str) -> Optional[list]:
        """Download YouTube's own auto-translated Arabic subtitle and
        parse it into cue blocks, for the Gemini per-chunk fallback."""
        opts = build_subtitle_opts(output_dir, [lang])
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception:
            return None
        fix_subtitle_bom(output_dir)
        candidates = [f for f in _own_subs() if f.suffix == ".srt"
                      and any(t in f.name.lower() for t in AR_TAGS)]
        if not candidates:
            return None
        try:
            raw = candidates[0].read_bytes().lstrip(UTF8_BOM).decode("utf-8", errors="replace")
        except Exception:
            return None
        return [b for b in raw.strip().split("\n\n") if b.strip()]

    manual_lang, auto_lang = arabic_lang_options(url)
    _check_stop()

    # 1) Real, human-made Arabic subtitle
    if manual_lang:
        log(f"Subtitle: {manual_lang} (manual)", "info")
        ar_opts = build_subtitle_opts(output_dir, [manual_lang])
        try:
            with yt_dlp.YoutubeDL(ar_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass
        subs = _own_subs()
        if has_arabic_subtitle(subs):
            fix_subtitle_bom(output_dir)
            _mark_subtitle_source(_find_arabic_subtitle(subs), "Manual (real Arabic subtitle on YouTube)")
            return

    # 2) No manual Arabic — download English as the source to translate.
    # Looked up by this video's own tag afterwards (not a before/after
    # diff) so a retry still finds it even if an English subtitle with
    # the same filename was already sitting there from an earlier attempt.
    _check_stop()
    log("No manual Arabic sub — downloading English to translate...", "info")
    en_opts = build_subtitle_opts(output_dir, SUBTITLES_EN)
    try:
        with yt_dlp.YoutubeDL(en_opts) as ydl:
            ydl.download([url])
    except Exception:
        pass
    fix_subtitle_bom(output_dir)

    new_en_subs = {f for f in _own_subs() if f.suffix == ".srt" and f.name.lower().endswith(".en.srt")}
    if not new_en_subs:
        return

    # 3) Gemini — priority translation engine
    _check_stop()
    remaining = []
    for f in new_en_subs:
        _check_stop()
        yt_fallback = (lambda: _fetch_youtube_translated_blocks(auto_lang)) if auto_lang else None
        translated = translate_srt_to_arabic_gemini(f, log, should_stop, yt_fallback)
        if translated:
            log(f"Arabic translation saved: {translated.name}", "success")
        else:
            remaining.append(f)
    if not remaining:
        return

    # 4) Gemini unavailable/failed — try YouTube's own auto-translated
    #    Arabic captions before falling back to our own Google Translate call
    _check_stop()
    if auto_lang:
        log(f"Trying YouTube's own Arabic translation ({auto_lang})...", "info")
        yt_ar_opts = build_subtitle_opts(output_dir, [auto_lang])
        try:
            with yt_dlp.YoutubeDL(yt_ar_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass
        fix_subtitle_bom(output_dir)
        subs = _own_subs()
        if has_arabic_subtitle(subs):
            _mark_subtitle_source(_find_arabic_subtitle(subs), "YouTube auto-translate")
            return

    # 5) Final fallback — Google Translate (deep-translator), always free
    _check_stop()
    for f in remaining:
        _check_stop()
        translated = translate_srt_to_arabic(f, log)
        if translated:
            log(f"Arabic translation saved (Google Translate): {translated.name}", "success")
            _mark_subtitle_source(translated, "Google Translate (fallback)")


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
