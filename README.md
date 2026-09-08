# ytarabic

Download videos from YouTube, Instagram, and X (Twitter), with automatic
Arabic subtitles — even for videos that never had Arabic captions to begin
with.

Built as a personal tool for watching English-language technical/educational
content (engineering courses, market analysis, tutorials) in Arabic, and for
extracting clean transcripts to feed into an LLM for analysis.

## Features

- **YouTube video & playlist download** — resumable, quality selection
  (360p–4K or audio-only), automatic retry on network failures.
- **Arabic subtitles, always** — a 4-tier priority chain finds the best
  Arabic subtitle available, and translates one itself if YouTube has none:
  1. Real, human-authored Arabic subtitle (if YouTube has one).
  2. [Gemini](https://aistudio.google.com/apikey) (free tier) — reads the
     whole subtitle file for a natural, context-aware translation instead
     of translating cue-by-cue in isolation.
  3. YouTube's own auto-translated Arabic captions.
  4. Google Translate — always free, no key, final safety net.
- **Retry a missing subtitle** without re-downloading the video.
- **Instagram Reels** download.
- **Twitter/X thread extraction** — text + images, ready to read or feed
  to an LLM.
- **YouTube transcript extraction** — plain-text transcript split by
  chapters, for pasting into Claude/ChatGPT for analysis.
- **Two interfaces on the same core logic**: a polished terminal UI, and a
  local web app with live progress streamed over WebSocket.

## Installation

```bash
git clone https://github.com/<your-username>/ytarabic.git
cd ytarabic
pip install -r requirements.txt
```

[FFmpeg](https://ffmpeg.org/) is optional but recommended (needed to merge
separate video/audio streams above 360p, and to extract audio-only MP3s).

## Configuration

Copy `.env.example` to `.env` and fill in what you need — nothing
sensitive is ever hardcoded, and `.env` is git-ignored.

```bash
cp .env.example .env
```

| Variable                 | Required? | Purpose                                                                 |
| ------------------------- | --------- | ------------------------------------------------------------------------ |
| `GEMINI_API_KEY`          | Optional  | Enables the best-quality Arabic translation tier. Free key: [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `YT_COOKIES_FILE`         | Optional  | Path to a YouTube cookies.txt file (fixes bot-detection errors on some videos). Export with the "Get cookies.txt LOCALLY" browser extension. |
| `INSTAGRAM_COOKIES_FILE`  | Optional  | Same idea, for private Instagram accounts.                              |

Plain environment variables work too and take precedence over `.env`.
Without `GEMINI_API_KEY`, Arabic translation still works — it just skips
straight to YouTube's own auto-translation, then Google Translate.

## Usage

**Web interface** (recommended) — live progress, runs on localhost:

```bash
python -m uvicorn webapp.server:app --port 8000
```

then open <http://127.0.0.1:8000>. On Windows, double-click `run_web.bat`
and it opens the browser for you. In VS Code, press <kbd>F5</kbd> and pick
**Web UI**.

**Terminal interface:**

```bash
python cli.py
```

or on Windows, double-click `run.bat`.

## Project structure

```
ytarabic/            core logic — no UI code, reusable by any front-end
  config.py          settings, .env loading
  youtube.py          video/playlist download, size estimation
  subtitles.py         Arabic subtitle priority chain + translation engines
  social.py             Twitter/X extraction
  transcript.py       YouTube transcript extraction
  progress_store.py  resumable-download progress tracking
  utils.py               small formatting helpers
cli.py               terminal interface (rich)
webapp/             local web interface (FastAPI + WebSocket)
  server.py          REST endpoints, job runner, event broadcast
  static/             single-page frontend (no build step)
```

Every core function accepts a `log(message, level)` callback instead of
printing directly, so the CLI and GUI can render progress however they
like (colored terminal output, or a scrolling text widget) without
duplicating any download/translation logic.

## License

MIT — see [LICENSE](LICENSE).
