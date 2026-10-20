# ytarabic

Download videos from YouTube, Instagram, and X (Twitter), with automatic
Arabic subtitles — even for videos that never had Arabic captions to begin
with.

Built as a personal tool for watching English-language technical/educational
content (engineering courses, market analysis, tutorials) in Arabic, and for
extracting clean transcripts to feed into an LLM for analysis.

## Features

- **One box for every link** — paste a YouTube, Instagram or X link (or
  several, one per line) and it shows a preview first: thumbnail, title,
  duration, the size of each quality, and which Arabic subtitle you'll get.
  Several links are queued one after another.
- **YouTube video & playlist download** — resumable, quality selection
  (360p–4K or MP3), automatic retry on network failures, an optional speed
  limit, and a **Stop button** that cancels cleanly mid-download or
  mid-translation. For a playlist, **pick which videos** to download
  (checkboxes, or a range like `1-10, 15`); Resume remembers the selection.
- **Arabic subtitles, always** — a priority chain finds the best Arabic
  subtitle available, and translates one itself if YouTube has none:
  1. Real, human-authored Arabic subtitle (if YouTube has one).
  2. YouTube's own auto-translated Arabic captions, or
     [Gemini](https://aistudio.google.com/apikey) (free tier) — which one
     goes first is a setting. Gemini reads the whole subtitle file for a
     natural, context-aware translation instead of cue-by-cue.
  3. Google Translate — always free, no key, final safety net.

  Subtitles can be Arabic, Arabic + English, English only, or none — and
  can be **embedded into the video file** as a switchable track.
- **Library** — every downloaded video with its subtitles (and which engine
  made the Arabic one), a **built-in player** with Arabic subtitles,
  "show in folder", and per-video actions: re-translate with Gemini / Google
  / YouTube, fetch English, embed subtitles, extract the transcript.
- **Clean up leftovers** — finds the partial files interrupted downloads
  leave behind (often hundreds of MB) and frees them; resumable ones are
  kept unless you say otherwise.
- **Transcripts** — plain text split by chapters, in the video's own
  language, English, or Arabic, optionally with timestamps. View and copy
  them in the app, or **summarize in Arabic (or English) with Gemini**.
- **Twitter/X thread extraction** — text + images.
- **Instagram Reels** download.
- **History** — every download, transcript, and extraction is logged, with
  search, filters, and one-click retry.
- **Settings in the UI** — default quality, subtitles, translation order,
  Gemini model, speed limit, transcript language; no code edits needed.
- **English or Arabic interface** (full right-to-left layout), desktop
  notifications when a download finishes.
- **Two interfaces on the same core logic**: a polished terminal UI, and a
  local web app with live progress streamed over WebSocket. The web app
  only answers to your own browser — other websites can't drive it.

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

Preferences you change in the web UI's **Settings** tab are saved to
`settings.json` in the project folder (git-ignored); the terminal interface
uses the same file.

## Tests

```bash
python -m unittest discover -s tests -t .
```

The tests use a throwaway downloads folder and settings file, never your
real ones, and make no network requests.

## Project structure

```
ytarabic/              core logic — no UI code, reusable by any front-end
  config.py            fixed config, .env loading
  settings.py          user preferences (settings.json), editable from the UI
  youtube.py           link preview, video/playlist download, size estimation
  subtitles.py         Arabic subtitle priority chain + translation engines
  gemini.py            shared Gemini client + retry policy
  media.py             FFmpeg helpers: embed subtitles, SRT → WebVTT
  library.py           downloaded files, leftovers cleanup, saved transcripts
  transcript.py        YouTube transcript extraction
  summary.py           Gemini summaries of transcripts
  social.py            Twitter/X extraction
  progress_store.py    resume progress, history, completed-video index
  utils.py             URL + formatting helpers
cli.py                 terminal interface (rich)
webapp/                local web interface (FastAPI + WebSocket)
  server.py            REST endpoints, local-only guard, event broadcast
  jobs.py              job queue + live progress events
  static/              single-page frontend (no build step), English/Arabic
tests/                 unit tests (python -m unittest)
```

Every core function accepts a `log(message, level)` callback instead of
printing directly, so the CLI and GUI can render progress however they
like (colored terminal output, or a scrolling text widget) without
duplicating any download/translation logic.

## License

MIT — see [LICENSE](LICENSE).
