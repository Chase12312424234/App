# DropFinder

Paste a YouTube link to a DJ set. DropFinder identifies every track, timestamps it, links it on Spotify and SoundCloud, and gives each track a **Play drop** button that plays the 15 seconds around its drop from the YouTube video.

No accounts, sign-ins or API keys needed.

## Setup (once)

You need Python 3.11+, Node 18+, and `ffmpeg` (`brew install ffmpeg` on a Mac, `sudo apt install ffmpeg` on Linux).

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
cd frontend && npm install && npm run build && cd ..
```

## Run the web app

```bash
.venv/bin/dropfinder serve
```

Open http://127.0.0.1:8000, paste a YouTube link and press **Find tracks**.

- **Live progress:** "Identified 14 tracks so far…" while it works. A 2-hour set takes a few minutes.
- **Click a timestamp** to jump the player there. **Play drop** plays 15 seconds starting 3 seconds before the drop.
- **Copy tracklist / .txt:** 1001Tracklists-style text, with drop times if you tick the box.
- **Share a set:** links look like `/?v=VIDEO_ID`. Processed sets are cached, so they load instantly.

Frontend development with hot reload: run `dropfinder serve` and `cd frontend && npm run dev`, then open http://localhost:5173.

## Command line

```bash
.venv/bin/dropfinder identify "https://www.youtube.com/watch?v=VIDEO_ID"
.venv/bin/dropfinder identify my_set.mp3 --links -o tracklist.txt   # local files work too
```

```
01. [0:00:00] Artist - Title  · drop @ 0:01:32
02. [0:03:45] Artist - Title (?)  · drop @ 0:05:10   <- heard in only one sample, double-check it
03. [0:07:30] ID - ID                                 <- nothing matched here
```

## Settings and cost

| CLI option | Web app setting (env var or `.env`) | Default | What it does |
|---|---|---|---|
| `--interval` | `DROPFINDER_INTERVAL` | 45 | Seconds between samples. Lower = finer timestamps, more requests. |
| `--sample-len` | `DROPFINDER_SAMPLE_LEN` | 12 | Seconds of audio per sample. |
| `--max-samples` | `DROPFINDER_MAX_SAMPLES` | none | Hard cap on requests per set. |
| `--concurrency` / `--delay` | `DROPFINDER_CONCURRENCY` / `DROPFINDER_REQUEST_DELAY` | 2 / 0.5 | Request pacing. Lower these if you see rate limiting. |
| `--gap-tolerance` | `DROPFINDER_GAP_TOLERANCE` | 1 | Unmatched samples allowed inside one track before it's split. |
| `--min-unknown` | `DROPFINDER_MIN_UNKNOWN_SAMPLES` | 2 | Unmatched samples in a row before an `ID - ID` row appears. |
| `--provider` | `DROPFINDER_PROVIDER` | shazam | `mock` gives fake results offline (for testing). |

See `.env.example`. A 2-hour set at the defaults is about 160 recognition requests. Every run's counts are appended to `backend/data/usage.jsonl`.

## How it works

1. **Download:** yt-dlp gets the audio; ffmpeg converts it to mono 16 kHz WAV.
2. **Sample:** a 12 s clip every 45 s.
3. **Identify:** each clip goes to Shazam's recognition service. Errors and rate limits retry with exponential backoff.
4. **Merge:** consecutive hits become one track; one-sample glitches inside a track are ignored; start times are refined using where in the song Shazam found the clip.
5. **Links:** Spotify, SoundCloud and YouTube search links built from artist + title (no keys).
6. **Drops:** within each track's part of the set, librosa measures bass (30–150 Hz) and loudness; the drop is the biggest jump after a quieter build-up.

**Background jobs:** the web server runs one set at a time on a background thread. Jobs and results are stored in SQLite (`backend/data/dropfinder.sqlite3`). Every sample result is cached per video, so a crash or restart resumes where it left off without repeating requests.

Code: `backend/dropfinder/` (pipeline, `web/` for the API) and `frontend/src/` (React UI).

## Caveats

- **Shazam access is unofficial.** The endpoint is free but undocumented and can rate-limit or change. Recognizers are swappable (`backend/dropfinder/recognizers/`).
- **YouTube blocks many cloud servers** ("Sign in to confirm you're not a bot", HTTP 403). Run DropFinder on your own computer. If a video still won't download, use the CLI with a local audio file.
- **Unreleased IDs, bootlegs and heavy edits** won't match and show as `ID - ID`.
- **Drop detection is a heuristic** tuned for electronic music. Expect it to be less meaningful for tracks without a classic build-up and drop.
- **Disk space:** each processed set keeps a ~230 MB WAV per 2 hours in `backend/data/` for drop analysis. Delete that folder anytime; it only costs a re-download.
- Downloading from YouTube is against YouTube's Terms of Service; keep this to personal use.

## Tests

```bash
cd backend && ../.venv/bin/pytest -q
```
