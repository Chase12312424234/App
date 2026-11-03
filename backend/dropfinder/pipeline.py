"""The full DropFinder pipeline: source -> tracklist with links and drops.

Used by both the CLI and the web worker.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .chunker import sample_times, wav_duration
from .config import Settings
from .download import fetch_audio
from .drop import find_drop
from .identify import SampleCache, identify_samples
from .links import track_links
from .merge import Entry, merge_samples
from .recognizers import get_recognizer


@dataclass
class Progress:
    stage: str                 # downloading | identifying | analyzing | done
    message: str
    samples_done: int = 0
    samples_total: int = 0
    tracks_found: int = 0


ProgressFn = Callable[[Progress], None]


def settings_key(s: Settings) -> str:
    """What makes two runs of the same video produce the same result."""
    cap = f"-max{s.max_samples}" if s.max_samples else ""
    return f"{s.provider}-i{s.interval:g}-l{s.sample_len:g}-g{s.gap_tolerance}-u{s.min_unknown_samples}{cap}"


def add_drops(entries: list[Entry], wav: Path) -> None:
    for e in entries:
        d = find_drop(wav, e.start, e.end)
        e.drop = asdict(d) if d else None


def add_links(entries: list[Entry]) -> None:
    for e in entries:
        if not e.unknown:
            e.links = track_links(e.artist or "", e.title or "", e.extra)


def run(source: str, settings: Settings, progress: ProgressFn | None = None,
        cookies: Path | None = None, log: Callable[[str], None] = lambda m: None) -> dict:
    """Process a set and return a JSON-serialisable result dict."""
    report = progress or (lambda p: None)
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    report(Progress("downloading", "Downloading audio…"))
    info, wav = fetch_audio(source, data_dir, cookies=cookies, log=log)

    duration = wav_duration(wav)
    times = sample_times(duration, settings.interval, settings.sample_len)
    if settings.max_samples is not None:
        times = times[: settings.max_samples]
        duration = min(duration, times[-1] + settings.interval) if times else 0.0
    report(Progress("identifying", f"Identifying tracks (0/{len(times)} samples)…", 0, len(times)))
    log(f"“{info.title}” · {duration / 60:.0f} min · {len(times)} samples "
        f"({settings.sample_len:g}s every {settings.interval:g}s) via {settings.provider}")

    def on_sample(done: int, total: int, tracks: int) -> None:
        report(Progress("identifying",
                        f"Identified {tracks} track{'s' if tracks != 1 else ''} so far…",
                        done, total, tracks))

    cache = SampleCache(data_dir / info.video_id / f"samples-{settings.provider}.json", settings.sample_len)
    results, usage = asyncio.run(identify_samples(
        wav, times, get_recognizer(settings.provider), cache,
        sample_len=settings.sample_len, concurrency=settings.concurrency,
        request_delay=settings.request_delay, max_retries=settings.max_retries,
        progress=on_sample,
    ))
    entries = merge_samples(results, sample_len=settings.sample_len, duration=duration,
                            gap_tolerance=settings.gap_tolerance,
                            min_unknown_samples=settings.min_unknown_samples)
    known = sum(not e.unknown for e in entries)

    report(Progress("analyzing", f"Finding the drops in {len(entries)} tracks…",
                    len(times), len(times), known))
    add_links(entries)
    add_drops(entries, wav)

    usage_rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "video_id": info.video_id, "samples": len(times),
                 "interval": settings.interval, "sample_len": settings.sample_len, **asdict(usage)}
    with open(data_dir / "usage.jsonl", "a") as f:
        f.write(json.dumps(usage_rec) + "\n")

    result = {
        "info": asdict(info),
        "duration": duration,
        "settings_key": settings_key(settings),
        "entries": [asdict(e) for e in entries],
        "usage": usage_rec,
    }
    (data_dir / info.video_id / "tracklist.json").write_text(json.dumps(result, indent=2))
    report(Progress("done", f"Done: {known} tracks identified.", len(times), len(times), known))
    return result


def entries_from_result(result: dict) -> list[Entry]:
    return [Entry(**e) for e in result["entries"]]
