"""
Arabic subtitle handling: fetching, RTL/encoding fixes, and the
translation priority chain (manual → YouTube auto-translate → Google).

Every function takes an optional `log(message, level)` callback instead
of printing directly, so the same logic can drive a CLI, a GUI, or a
test — `level` is one of "info" | "warn" | "error" | "success".
"""

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from . import settings
from .config import HAS_FFMPEG, SUB_EXTS, SUBTITLES_EN, UTF8_BOM
from .errors import Cancelled
from .utils import extract_youtube_id, is_youtube_url
from .youtube import base_opts, build_subtitle_opts

LogFn = Callable[[str, str], None]


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


# ─────────────────────────────────────────────
#  Which language is a subtitle file?
# ─────────────────────────────────────────────
_LANG_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8}){0,3}$")


def sub_lang(path: Path) -> Optional[str]:
    """The language code yt-dlp put in a subtitle's filename —
    "Title [id].ar.srt" → "ar", "Title [id].ar-en.vtt" → "ar-en" — or
    None if the name doesn't carry one."""
    stem = Path(path.name).stem
    if "." not in stem:
        return None
    code = stem.rsplit(".", 1)[1]
    return code if _LANG_CODE_RE.match(code) else None


def is_arabic_lang(code: Optional[str]) -> bool:
    if not code:
        return False
    code = code.lower()
    return code in ("ar", "ara", "arabic") or code.startswith(("ar-", "ar_"))


def is_arabic_subtitle(path: Path) -> bool:
    """Decided from the language code in the filename only — a title that
    merely contains "ar." somewhere (say "Star. Wars") is not Arabic."""
    return path.suffix.lower() in SUB_EXTS and is_arabic_lang(sub_lang(path))


def has_arabic_subtitle(files) -> bool:
    return any(is_arabic_subtitle(f) for f in files)


def _find_arabic_subtitle(files) -> Optional[Path]:
    # Prefer the plain "ar" track over variants like "ar-ja" (an old
    # yt-dlp language glob used to pull every ar-* translation).
    arabic = sorted((f for f in files if is_arabic_subtitle(f)),
                    key=lambda f: (sub_lang(f).lower() != "ar", f.suffix.lower() != ".srt", f.name))
    return arabic[0] if arabic else None


def read_subtitle_source(sub: Path) -> Optional[str]:
    """Which engine produced a subtitle, from its ".source" sidecar."""
    try:
        return Path(str(sub) + ".source").read_text(encoding="utf-8").strip() or None
    except OSError:
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
#  RTL / encoding post-processing
# ─────────────────────────────────────────────
def _srt_fix_line_order(text: str) -> str:
    """
    In Arabic auto-generated subtitles, lines within a cue are often
    reversed (line 2 shown before line 1). This fixes the order for any
    cue with two or more text lines.
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


def fix_subtitle_bom(directory: Path, tag: Optional[str] = None):
    """
    For every subtitle file in directory (only those whose name contains
    `tag`, e.g. "[VIDEO_ID]", when given):
      1. Convert .vtt/.ass/.ssa → .srt  (Windows player compatibility)
      2. Fix reversed line order inside each cue  (Arabic subtitles only)
      3. Add UTF-8 BOM  (Arabic rendering in Windows)

    The BOM doubles as a "done" marker: a file that already starts with
    one is skipped. Without that, every call re-reversed every file it
    touched — and since one folder (single/) holds many videos, each new
    download flipped the line order of every *other* video's subtitles
    back and forth, English ones included (scrambling English text right
    before it was sent off for translation).
    """
    if not directory.exists():
        return
    for f in list(directory.iterdir()):
        if f.suffix.lower() not in SUB_EXTS or (tag and tag not in f.name):
            continue
        try:
            if f.suffix.lower() in {".vtt", ".ass", ".ssa"}:
                srt_path = _convert_to_srt(f)
                if srt_path:
                    f.unlink()
                    f = srt_path
            raw = f.read_bytes()
            if raw.startswith(UTF8_BOM):
                continue
            if f.suffix.lower() == ".srt":
                # Cues are split on blank lines — with Windows line endings
                # there are none, and the whole file got reordered as one cue.
                text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
                if is_arabic_subtitle(f):
                    text = _srt_fix_line_order(text)
                f.write_bytes(UTF8_BOM + text.encode("utf-8"))
            else:
                f.write_bytes(UTF8_BOM + raw)
        except Exception:
            pass


# ─────────────────────────────────────────────
#  Our own translation — Google Translate (free, no key, literal)
# ─────────────────────────────────────────────
# (A Gemini engine used to sit here too. It was removed on request: in
# practice its translations weren't good enough to be worth the quota,
# the waits, and the rate-limit failures. Gemini is still used for
# transcript summaries — see summary.py.)
TRANSLATE_CUES_PER_REQUEST = 25   # cues per Google Translate request
_CUE_SEP = "\n|||\n"


def _google_translate_srt_text(raw: str, log: LogFn = _default_log) -> Optional[str]:
    """Translate raw SRT text to Arabic with Google Translate (free, via
    deep-translator — no API key needed). Keeps index/timestamp lines
    untouched, translates cue text only, in small batches."""
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


def _arabic_dst(src: Path) -> Path:
    name = src.name
    return src.parent / (name[:-7] + ".ar.srt" if name.lower().endswith(".en.srt") else src.stem + ".ar.srt")


def translate_srt_to_arabic(src: Path, log: LogFn = _default_log) -> Optional[Path]:
    """Translate an English .srt file to Arabic with Google Translate —
    see _google_translate_srt_text for the actual translation logic."""
    try:
        raw = src.read_bytes().lstrip(UTF8_BOM).decode("utf-8", errors="replace").replace("\r\n", "\n")
    except Exception:
        return None

    result = _google_translate_srt_text(raw, log)
    if result is None:
        return None

    dst = _arabic_dst(src)
    dst.write_bytes(UTF8_BOM + (result + "\n").encode("utf-8"))
    return dst


# ─────────────────────────────────────────────
#  Arabic subtitle discovery on YouTube (manual vs auto-translated)
# ─────────────────────────────────────────────
_AR_PRIORITY = ["ar", "ar-orig", "ar-SA", "ar-EG", "ar-AE", "ar-IQ"]


def arabic_langs_from_info(info: dict) -> tuple:
    """(manual_lang, auto_lang) from an already-extracted info dict:
      manual_lang — best real, human-authored Arabic subtitle language,
                    or None.
      auto_lang   — best YouTube-auto-translated/auto-generated Arabic
                    caption language, or None.
    Manual is always preferred over auto — a human translation beats
    any machine translation, YouTube's or ours."""
    def _best(pool: set) -> Optional[str]:
        for lang in _AR_PRIORITY:
            if lang in pool:
                return lang
        for lang in sorted(pool):
            if is_arabic_lang(lang):
                return lang
        return None

    manual = set((info or {}).get("subtitles") or {})
    auto   = set((info or {}).get("automatic_captions") or {})
    return _best(manual), _best(auto)


def arabic_lang_options(url: str) -> tuple:
    """arabic_langs_from_info for a URL, in a single request."""
    try:
        with yt_dlp.YoutubeDL({**base_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return arabic_langs_from_info(info) if info else (None, None)
    except Exception:
        return None, None


def is_youtube(url: str) -> bool:
    """Return True only for YouTube URLs — subtitles only make sense there."""
    return is_youtube_url(url)


# ─────────────────────────────────────────────
#  Main entry point — the full Arabic subtitle priority chain
# ─────────────────────────────────────────────
ENGINES = ("auto", "manual", "youtube", "google")


def _engine_order(engine: str) -> list:
    return ["manual", "youtube", "google"] if engine == "auto" else [engine]


def _backup(files) -> list:
    """Move existing Arabic subtitles (and their .source sidecars) aside
    so a fresh attempt is judged on what *it* produced — not on a file
    that was already sitting there. Returns [(original, backup)]."""
    moved = []
    for f in files:
        if not is_arabic_subtitle(f):
            continue
        for p in (f, Path(str(f) + ".source")):
            if p.exists():
                bak = Path(str(p) + ".bak")
                try:
                    p.replace(bak)
                    moved.append((p, bak))
                except OSError:
                    pass
    return moved


def _restore(moved: list):
    for orig, bak in moved:
        try:
            bak.replace(orig)
        except OSError:
            pass


def _discard(moved: list):
    for _, bak in moved:
        try:
            bak.unlink()
        except OSError:
            pass


def fetch_subtitles(url: str, output_dir: Path, log: LogFn = _default_log,
                     should_stop: Optional[Callable[[], bool]] = None,
                     mode: Optional[str] = None, engine: str = "auto") -> Optional[str]:
    """
    Fetch subtitles for one YouTube video into output_dir. Returns the
    source label of the Arabic subtitle produced (also written to its
    .source sidecar), "English" for mode="en", or None if nothing was
    produced. Never raises except Cancelled — every step is best-effort.

    mode (default: the "subtitle_mode" setting):
      ar     — Arabic, via the priority chain below
      ar_en  — the same, plus an English subtitle kept alongside
      en     — English only, no translation
      none   — nothing

    Arabic priority chain (engine="auto"):
      1. Real, human-authored Arabic subtitle — used as-is, nothing beats it.
      2. YouTube's own auto-translated Arabic captions — instant and free.
      3. Google Translate (deep-translator) on the English text — always
         free, no key, last resort so a translation always happens.
    engine="manual" | "youtube" | "google" runs just that one step
    instead — e.g. to re-translate a video whose current Arabic subtitle
    reads badly. An Arabic subtitle that was already there is kept unless
    the new attempt actually produces a replacement.

    should_stop(), if given, is checked before each step and raises
    Cancelled to stop the whole chain (e.g. mid-translation) early.
    Silently skips non-YouTube URLs (Twitter, Instagram, etc.)
    """
    mode = mode or settings.get("subtitle_mode")
    if mode == "none" or not is_youtube(url):
        return None
    if engine not in ENGINES:
        engine = "auto"

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
        return {f for f in output_dir.iterdir()
                if f.suffix.lower() in SUB_EXTS and (tag is None or tag in f.name)}

    def _english_subs() -> list:
        return [f for f in _own_subs() if f.name.lower().endswith(".en.srt")]

    def _download(langs: list):
        try:
            with yt_dlp.YoutubeDL(build_subtitle_opts(output_dir, langs)) as ydl:
                ydl.download([url])
        except Exception:
            pass
        fix_subtitle_bom(output_dir, tag)

    def _ensure_english() -> list:
        # Looked up by this video's own tag (not a before/after diff) so a
        # retry still finds it even if an English subtitle with the same
        # filename was already sitting there from an earlier attempt.
        en = _english_subs()
        if not en:
            log("Downloading English subtitle...", "info")
            _download(SUBTITLES_EN)
            en = _english_subs()
        return en

    if mode in ("en", "ar_en"):
        _check_stop()
        en = _ensure_english()
        if mode == "en":
            if en:
                log(f"English subtitle saved: {en[0].name}", "success")
                return "English"
            log("No English subtitle available for this video.", "warn")
            return None
        if not en:
            log("No English subtitle available for this video.", "warn")

    moved = _backup(_own_subs())
    source = None
    try:
        source = _arabic_chain(url, engine, log, _check_stop, _own_subs, _download, _ensure_english)
    finally:
        if source:
            _discard(moved)
        else:
            _restore(moved)
    return source


def _arabic_chain(url, engine, log, _check_stop, _own_subs, _download, _ensure_english) -> Optional[str]:
    langs = None
    for tier in _engine_order(engine):
        _check_stop()

        if tier in ("manual", "youtube"):
            if langs is None:
                langs = arabic_lang_options(url)
                _check_stop()
            lang = langs[0] if tier == "manual" else langs[1]
            if not lang:
                if engine != "auto":
                    log("YouTube has no " + ("human-made Arabic subtitle" if tier == "manual"
                                             else "Arabic auto-translation") + " for this video.", "warn")
                continue
            if tier == "manual":
                log(f"Subtitle: {lang} (manual)", "info")
                label = "Manual (real Arabic subtitle on YouTube)"
            else:
                log(f"Trying YouTube's own Arabic translation ({lang})...", "info")
                label = "YouTube auto-translate"
            _download([lang])
            ar = _find_arabic_subtitle(_own_subs())
            if ar:
                _mark_subtitle_source(ar, label)
                if tier == "youtube":
                    log(f"Arabic subtitle saved (YouTube translation): {ar.name}", "success")
                return label
            continue

        # google — translates the English subtitle
        if engine == "auto":
            log("No Arabic subtitle from YouTube — translating the English one "
                "with Google Translate...", "info")
        en_files = _ensure_english()
        if not en_files:
            log("No English subtitle to translate from.", "warn")
            continue
        _check_stop()
        out = translate_srt_to_arabic(en_files[0], log)
        if out:
            label = "Google Translate" if engine == "google" else "Google Translate (fallback)"
            _mark_subtitle_source(out, label)
            log(f"Arabic translation saved (Google Translate): {out.name}", "success")
            return label

    if engine == "auto":
        log("Could not get an Arabic subtitle for this video.", "warn")
    return None


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
    from .config import VALID_VIDEO_EXTS

    results = []
    if not download_dir.exists():
        return results
    for f in download_dir.rglob("*"):
        if f.suffix.lower() not in VALID_VIDEO_EXTS or re.search(r"\.f\d+$", f.stem):
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
