"""dropfinder identify <url-or-file>   -> prints a timestamped tracklist
dropfinder serve                    -> runs the web app
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import Settings
from .download import DownloadError
from .export import fmt_time, tracklist_text
from .pipeline import Progress, entries_from_result, run


def _parser() -> argparse.ArgumentParser:
    d = Settings()
    p = argparse.ArgumentParser(prog="dropfinder", description="Identify the tracks in a YouTube DJ set.")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("identify", help="build a tracklist for a YouTube URL or local file")
    i.add_argument("url", help="YouTube URL, or a path to a local audio/video file")
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
    i.add_argument("--links", action="store_true", help="print Spotify/SoundCloud links under each track")
    i.add_argument("-o", "--out", type=Path, help="also write the tracklist to this text file")
    i.add_argument("--json", action="store_true", help="print JSON instead of text")

    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    return p


def _progress_printer():
    last = [0.0, ""]

    def show(p: Progress) -> None:
        now = time.monotonic()
        if p.stage != last[1]:
            if last[1] == "identifying":
                sys.stderr.write("\n")
            last[1] = p.stage
            if p.stage != "identifying":
                sys.stderr.write(f"  {p.message}\n")
                return
        if p.stage == "identifying" and (now - last[0] > 0.5 or p.samples_done == p.samples_total):
            last[0] = now
            sys.stderr.write(f"\r  Sample {p.samples_done}/{p.samples_total} · {p.message}   ")
        sys.stderr.flush()
    return show


def run_identify(a: argparse.Namespace) -> int:
    log = lambda m: print(m, file=sys.stderr)
    settings = Settings(
        interval=a.interval, sample_len=a.sample_len, provider=a.provider,
        concurrency=a.concurrency, request_delay=a.delay, max_retries=a.max_retries,
        max_samples=a.max_samples, gap_tolerance=a.gap_tolerance,
        min_unknown_samples=a.min_unknown, data_dir=a.data_dir,
    )
    try:
        result = run(a.url, settings, progress=_progress_printer(), cookies=a.cookies, log=log)
    except DownloadError as e:
        log(f"Error: {e}")
        return 2

    entries = entries_from_result(result)
    info, usage = result["info"], result["usage"]
    text = tracklist_text(entries, info["title"], info["webpage_url"], drops=True, links=a.links)
    if a.out:
        a.out.write_text(text)
    print(json.dumps(result["entries"], indent=2) if a.json else text, end="" if not a.json else "\n")

    known = sum(not e.unknown for e in entries)
    drops = sum(1 for e in entries if e.drop)
    log(f"\n{known} tracks identified, {len(entries) - known} unknown, {drops} drops found. "
        f"API calls: {usage['requests']} (retries {usage['retries']}, rate-limited {usage['rate_limited']}), "
        f"{usage['cached']} samples from cache. Matched {usage['matched']}/{usage['samples']} samples"
        + (f", {usage['failed']} failed after retries (rerun to retry them)." if usage["failed"] else "."))
    return 0


def run_serve(a: argparse.Namespace) -> int:
    import uvicorn
    uvicorn.run("dropfinder.web.app:app", host=a.host, port=a.port, reload=a.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    return {"identify": run_identify, "serve": run_serve}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
