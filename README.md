# DropFinder

Paste a YouTube link to a DJ set and get a timestamped tracklist. No accounts or API keys needed.

**Status:** milestone 1 (CLI tracklist). Next: Spotify/SoundCloud links → drop detection → web UI → polish.

## Setup

Requires Python 3.11+, `ffmpeg`, and a JavaScript runtime (Node or Deno; yt-dlp needs one for YouTube).

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
```

## Usage

```bash
.venv/bin/dropfinder identify "https://www.youtube.com/watch?v=VIDEO_ID"
.venv/bin/dropfinder identify my_set.mp3            # local files work too
.venv/bin/dropfinder identify URL -o tracklist.txt  # also save as text
```

Output:

```
01. [0:00:00] Artist - Title
02. [0:03:45] Artist - Title (?)    <- heard in only one sample, double-check it
03. [0:07:30] ID - ID               <- nothing matched here
```

Useful options (`dropfinder identify -h` for all):

| Option | Default | What it does |
|---|---|---|
| `--interval` | 45 | Seconds between samples. Lower = more accurate start times, more requests. |
| `--sample-len` | 12 | Seconds of audio per sample. |
| `--max-samples` | none | Cap on samples, handy for quick tests. |
| `--concurrency` / `--delay` | 2 / 0.5 | Request pacing. Turn down if you see rate limiting. |
| `--gap-tolerance` | 1 | Unmatched samples allowed inside one track before it's split. |
| `--min-unknown` | 2 | Unmatched samples in a row before an `ID - ID` row appears. |
| `--provider` | shazam | `mock` runs offline with fake results. |

A 2-hour set at the defaults is ~160 requests.

## How it works

1. **Download**: yt-dlp fetches the audio; ffmpeg converts it to mono 16 kHz WAV (`backend/data/<video_id>/audio.wav`).
2. **Sample**: a `--sample-len` clip every `--interval` seconds.
3. **Recognize**: each clip goes to Shazam's public recognition endpoint (via `shazamio`). Errors and rate limits retry with exponential backoff.
4. **Merge**: consecutive hits collapse into one entry; short glitches inside a track are absorbed; start times are refined using where in the track Shazam found the clip.

**Caching:** every sample result is cached per video. Re-running a set, or resuming after a crash, makes zero requests for samples already done; failed samples are retried. Each run appends its request counts to `backend/data/usage.jsonl`.

## Caveats

- Shazam's endpoint is free but unofficial. It can rate-limit or change without notice. Recognizers are swappable (`backend/dropfinder/recognizers/`).
- YouTube often blocks cloud/datacenter IPs ("Sign in to confirm you're not a bot", HTTP 403). Run from your own computer, or pass a local audio file.
- Unreleased IDs and heavy edits won't match any database; they show as `ID - ID`.
- Downloading from YouTube is against YouTube's Terms of Service; keep this to personal use.

## Tests

```bash
cd backend && ../.venv/bin/pytest -q
```
