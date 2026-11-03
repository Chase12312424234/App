"""Run recognition over every sample, with retries, resume-able caching and usage stats."""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .chunker import read_sample
from .merge import track_key
from .recognizers import Match, RateLimited, Recognizer


@dataclass
class SampleResult:
    time: float
    match: Match | None = None
    error: str | None = None  # set when every retry failed


@dataclass
class Usage:
    provider: str
    requests: int = 0        # every HTTP call actually made, retries included
    cached: int = 0          # samples answered from a previous run, no call made
    matched: int = 0
    unmatched: int = 0
    failed: int = 0
    rate_limited: int = 0
    retries: int = 0
    by_reason: dict = field(default_factory=dict)


ProgressFn = Callable[[int, int, int], None]  # (samples done, samples total, distinct tracks so far)


class SampleCache:
    """Per-video JSON cache of sample results, so reruns and crashes don't re-spend calls."""

    def __init__(self, path: Path, sample_len: float) -> None:
        self.path = path
        self.sample_len = sample_len
        self.data: dict = json.loads(path.read_text()) if path.exists() else {}

    def _key(self, t: float) -> str:
        return f"{t:.3f}@{self.sample_len:g}"

    def get(self, t: float) -> SampleResult | None:
        raw = self.data.get(self._key(t))
        if raw is None:
            return None
        m = raw.get("match")
        return SampleResult(time=t, match=Match(**m) if m else None)

    def put(self, r: SampleResult) -> None:
        if r.error:  # don't cache failures, retry them next time
            return
        self.data[self._key(r.time)] = {"match": asdict(r.match) if r.match else None}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data))
        tmp.replace(self.path)


async def identify_samples(
    wav: Path,
    times: list[float],
    recognizer: Recognizer,
    cache: SampleCache,
    *,
    sample_len: float,
    concurrency: int = 2,
    request_delay: float = 0.5,
    max_retries: int = 4,
    progress: ProgressFn | None = None,
) -> tuple[list[SampleResult], Usage]:
    usage = Usage(provider=recognizer.name)
    results: dict[float, SampleResult] = {}
    seen_tracks: set[str] = set()
    queue: asyncio.Queue[float] = asyncio.Queue()
    lock = asyncio.Lock()

    def record(r: SampleResult) -> None:
        results[r.time] = r
        if r.match:
            usage.matched += 1
            seen_tracks.add(track_key(r.match))
        elif r.error:
            usage.failed += 1
        else:
            usage.unmatched += 1
        if progress:
            progress(len(results), len(times), len(seen_tracks))

    for t in times:
        hit = cache.get(t)
        if hit is not None:
            usage.cached += 1
            record(hit)
        else:
            queue.put_nowait(t)

    async def recognize_with_retry(t: float) -> SampleResult:
        audio = read_sample(wav, t, sample_len)
        last_err = ""
        for attempt in range(max_retries + 1):
            usage.requests += 1
            if attempt:
                usage.retries += 1
            try:
                return SampleResult(time=t, match=await recognizer.recognize(audio))
            except RateLimited as e:
                usage.rate_limited += 1
                last_err = f"rate limited: {e}"
                wait = min(60, 5 * 2 ** attempt)
            except Exception as e:  # network blips, bad responses, etc.
                last_err = f"{type(e).__name__}: {e}"
                wait = min(30, 2 ** attempt)
            usage.by_reason[last_err[:60]] = usage.by_reason.get(last_err[:60], 0) + 1
            if attempt < max_retries:
                await asyncio.sleep(wait + random.uniform(0, 1))
        return SampleResult(time=t, error=last_err)

    async def worker() -> None:
        while True:
            try:
                t = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            r = await recognize_with_retry(t)
            async with lock:
                cache.put(r)
                record(r)
                if len(results) % 10 == 0:
                    cache.save()
            await asyncio.sleep(request_delay)

    try:
        await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    finally:
        cache.save()
        await recognizer.close()

    return [results[t] for t in sorted(results)], usage
