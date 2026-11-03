"""dropfinder identify <youtube-url>  ->  prints a timestamped tracklist."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .chunker import sample_times, wav_duration
from .config import Settings
from .download import DownloadError, fetch_audio
from .export import fmt_time, tracklist_text
from .identify import SampleCache, identify_samples
from .merge import merge_samples
from .recognizers import get_recognizer


def _parser() -> argparse.ArgumentParser:
    d = Settings()
    p = argparse.ArgumentParser(prog="dropfinder", description="Identify the tracks in a YouTube DJ set.")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("identify", help="build a tracklist for a YouTube URL")
    i.add_argument("url")
    i.add_argument("--interval", type=float, default=d.interval, help=f"seconds between samples (default {d.interval:g})")
    i.add_argument("--sample-len", type=float, default=d.sample_len, help=f"sample length in seconds (default {d.sample_len:g})")
    i.add_argument("--provider", default=d.provider, choices=["shazam", "mock"])
    i.add_argument("--concurrency", type=int, default=d.concurrency)
    i.add_argument("--delay", type=float, default=d.request_delay, help="pause after each request, per worker")
    i.add_argument("--max-retries", type=int, default=d.max_retries)
    i.add_argument("--max-samples", type=int, default=d.max_samples, help="cap on samples recognized (cost/testing guard)")
    i.add_argument("--gap-tolerance", type=int, default=d.gap_tolerance)
    i.add_argument("--min-unknown", type=int, default=d.min_unknown_samples, help="unmatched samples in a row before an 'ID - ID' row")
    i.add_argument("--cookies", type=Path, help="cookies.txt for age-restricted videos")
    i.add_argument("--data-dir", type=Path, default=d.data_dir)
    i.add_argument("-o", "--out", type=Path, help="also write the tracklist to this text file")
    i.add_argument("--json", action="store_true", help="print JSON instead of text")
    return p


def _progress_printer():
    last = [0.0]

    def show(done: int, total: int, tracks: int) -> None:
        now = time.monotonic()
        if done == total or now - last[0] > 0.5:
            last[0] = now
            sys.stderr.write(f"\r  Sample {done}/{total} · identified {tracks} track{'s' if tracks != 1 else ''} so far…   ")
            if done == total:
                sys.stderr.write("\n")
            sys.stderr.flush()
    return show


def run_identify(a: argparse.Namespace) -> int:
    log = lambda m: print(m, file=sys.stderr)
    data_dir: Path = a.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        info, wav = fetch_audio(a.url, data_dir, cookies=a.cookies, log=log)
    except DownloadError as e:
        log(f"Error: {e}")
        return 2

    duration = wav_duration(wav)
    times = sample_times(duration, a.interval, a.sample_len)
    if a.max_samples is not None:
        times = times[: a.max_samples]
        duration = min(duration, times[-1] + a.interval) if times else 0
    log(f"“{info.title}” · {fmt_time(duration)} · {len(times)} samples "
        f"({a.sample_len:g}s every {a.interval:g}s) via {a.provider}")

    cache = SampleCache(data_dir / info.video_id / f"samples-{a.provider}.json", a.sample_len)
    results, usage = asyncio.run(identify_samples(
        wav, times, get_recognizer(a.provider), cache,
        sample_len=a.sample_len, concurrency=a.concurrency, request_delay=a.delay,
        max_retries=a.max_retries, progress=_progress_printer(),
    ))
    entries = merge_samples(results, sample_len=a.sample_len, duration=duration,
                            gap_tolerance=a.gap_tolerance, min_unknown_samples=a.min_unknown)

    # usage log: one JSON line per run
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "video_id": info.video_id,
              "samples": len(times), "interval": a.interval, "sample_len": a.sample_len, **asdict(usage)}
    with open(data_dir / "usage.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")
    (data_dir / info.video_id / "tracklist.json").write_text(json.dumps(
        {"info": asdict(info), "entries": [asdict(e) for e in entries]}, indent=2))

    text = tracklist_text(entries, info.title, info.webpage_url)
    if a.out:
        a.out.write_text(text)
    if a.json:
        print(json.dumps([asdict(e) for e in entries], indent=2))
    else:
        print(text, end="")

    known = sum(not e.unknown for e in entries)
    log(f"\n{known} tracks identified, {len(entries) - known} unknown. "
        f"API calls: {usage.requests} (retries {usage.retries}, rate-limited {usage.rate_limited}), "
        f"{usage.cached} samples from cache. Matched {usage.matched}/{len(times)} samples"
        + (f", {usage.failed} failed after retries (rerun to retry them)." if usage.failed else "."))
    return 0


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd == "identify":
        return run_identify(a)
    return 1


if __name__ == "__main__":
    sys.exit(main())
