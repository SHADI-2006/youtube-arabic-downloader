"""
Thin wrapper around the Gemini API (google-genai, free tier), used for
transcript summaries: one place for the client, the model choice, and the
429/transient-error retry policy.
"""

import os
import re
import time
from typing import Callable, Optional

from . import settings
from .config import GEMINI_RETRIES, GEMINI_RETRY_WAIT, GEMINI_TIMEOUT

LogFn = Callable[[str, str], None]

_RETRY_DELAY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


def _default_log(msg: str, level: str = "info") -> None:
    print(msg)


def unavailable_reason() -> Optional[str]:
    """Why Gemini can't be used right now, or None if it can."""
    try:
        from google import genai  # noqa: F401
    except ImportError:
        return "the google-genai package isn't installed — run: pip install google-genai"
    if not os.environ.get("GEMINI_API_KEY"):
        return "GEMINI_API_KEY not set"
    return None


def make_client():
    from google import genai
    return genai.Client()


def error_detail(e: Exception) -> str:
    """The real message Google sent back (which quota metric, its limit,
    how long to wait) instead of guessing at the cause."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        msg = body.get("error", {}).get("message")
        if msg:
            return msg
    return str(e)


def retry_delay(e: Exception) -> Optional[float]:
    """Seconds until the quota that tripped this 429 resets, if Google's
    error message states one (it does for the short per-minute burst
    limit, not for a fully exhausted daily quota)."""
    m = _RETRY_DELAY_RE.search(error_detail(e))
    return float(m.group(1)) if m else None


def generate(client, prompt: str, log: LogFn = _default_log,
             timeout: float = GEMINI_TIMEOUT, what: str = "Gemini request") -> Optional[str]:
    """One request with the shared retry policy. Returns the response
    text, or None if it failed (the reason is already logged)."""
    model = settings.get("gemini_model")
    for attempt in range(1, GEMINI_RETRIES + 2):
        try:
            interaction = client.interactions.create(model=model, input=prompt, timeout=timeout)
            return (interaction.output_text or "").strip()
        except Exception as e:
            status_code = getattr(e, "status_code", None) or getattr(e, "code", None)

            if status_code == 429:
                delay = retry_delay(e)
                # A short stated delay means this is the per-minute burst
                # limit resetting, not the daily quota — worth one retry
                # instead of giving up on a request that would otherwise
                # succeed a few seconds later.
                if delay is not None and delay <= 30 and attempt <= GEMINI_RETRIES:
                    wait = delay + 1
                    log(f"Gemini rate limit hit — resets in {wait:.0f}s, retrying "
                        f"({attempt}/{GEMINI_RETRIES})...", "warn")
                    time.sleep(wait)
                    continue
                log(f"GEMINI LIMIT REACHED (HTTP 429): {error_detail(e)}", "error")
                return None

            if status_code == 404:
                log(f"Gemini model \"{model}\" not found — check the model name in Settings. "
                    f"({error_detail(e)})", "error")
                return None

            is_transient = status_code is None or (isinstance(status_code, int) and status_code >= 500)
            if is_transient and attempt <= GEMINI_RETRIES:
                log(f"Gemini busy ({e}) — retry {attempt}/{GEMINI_RETRIES} "
                    f"in {GEMINI_RETRY_WAIT}s...", "warn")
                time.sleep(GEMINI_RETRY_WAIT)
                continue

            log(f"{what} failed: {e}", "warn")
            return None
    return None


def strip_code_fence(text: str) -> str:
    """Models sometimes wrap the whole answer in ``` fences despite being
    told not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
