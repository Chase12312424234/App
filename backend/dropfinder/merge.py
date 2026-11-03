"""Turn per-sample matches into a tracklist.

Rules:
1. Consecutive samples with the same track become one entry.
2. A short interruption (<= gap_tolerance samples of "no match" or a different
   track) between two runs of the same track is absorbed: mixing, filters and
   vocals over the top often confuse a single sample.
3. A track heard in only one sample is kept but flagged `uncertain`.
4. Runs of unmatched samples at least `min_unknown_samples` long become an
   "ID - ID" entry. Shorter ones are treated as transitions.
5. Start time is refined with the provider's offset-in-track when available
   (start ~ sample_time - offset), clamped so it can't go before the previous
   track's last confirmed sample or after this track's first one.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .identify import SampleResult
    from .recognizers import Match

_NOISE = re.compile(
    r"\s*[\(\[]\s*(original mix|extended mix|extended|radio edit|club mix|remaster(ed)?( \d{4})?|"
    r"\d{4} remaster(ed)?|official (audio|video)|explicit|clean)\s*[\)\]]",
    re.I,
)
_FEAT = re.compile(r"\s*[\(\[]?\s*\b(feat\.?|ft\.?|featuring)\s+[^\)\]]*[\)\]]?", re.I)


def _norm(s: str) -> str:
    s = _NOISE.sub("", s)
    s = _FEAT.sub("", s)
    s = re.sub(r"\s+-\s+(original mix|extended mix|radio edit)$", "", s, flags=re.I)
    s = re.sub(r"[^\w]+", " ", s.lower())
    return " ".join(s.split())


def track_key(m: "Match") -> str:
    """Identity of a track. Title+artist, not ISRC: the same song often has several
    ISRCs (single, album, compilation), while a remix gets a different title."""
    artist = _norm(m.artist.split(",")[0].split("&")[0].split(" x ")[0])
    return f"{artist}|{_norm(m.title)}"


@dataclass
class Entry:
    start: float
    end: float
    title: str | None = None   # None = unknown
    artist: str | None = None
    isrc: str | None = None
    hits: int = 0              # samples that matched this track
    uncertain: bool = False
    first_hit: float | None = None
    last_hit: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def unknown(self) -> bool:
        return self.title is None


@dataclass
class _Run:
    key: str | None
    samples: list  # list[SampleResult]


def _runs(samples: list["SampleResult"]) -> list[_Run]:
    runs: list[_Run] = []
    for s in samples:
        k = track_key(s.match) if s.match else None
        if runs and runs[-1].key == k:
            runs[-1].samples.append(s)
        else:
            runs.append(_Run(k, [s]))
    return runs


def _absorb_gaps(runs: list[_Run], tolerance: int) -> list[_Run]:
    """Merge A, <short stuff>, A  ->  A."""
    if tolerance <= 0:
        return runs
    out: list[_Run] = []
    i = 0
    while i < len(runs):
        cur = runs[i]
        if cur.key is None:
            out.append(cur)
            i += 1
            continue
        merged = _Run(cur.key, list(cur.samples))
        j = i + 1
        while j < len(runs):
            # look for the same key again within `tolerance` interrupting samples
            gap, k = 0, j
            while k < len(runs) and runs[k].key != merged.key and gap + len(runs[k].samples) <= tolerance:
                gap += len(runs[k].samples)
                k += 1
            if k < len(runs) and k > j and runs[k].key == merged.key:
                # interrupting samples are just dropped; only real hits are kept
                merged.samples.extend(runs[k].samples)
                j = k + 1
            else:
                break
        out.append(merged)
        i = j
    # absorbing can leave two neighbouring runs with the same key
    joined: list[_Run] = []
    for r in out:
        if joined and joined[-1].key == r.key:
            joined[-1].samples.extend(r.samples)
        else:
            joined.append(r)
    return joined


def merge_samples(
    samples: list["SampleResult"],
    *,
    sample_len: float,
    duration: float,
    gap_tolerance: int = 1,
    min_unknown_samples: int = 2,
) -> list[Entry]:
    samples = sorted(samples, key=lambda s: s.time)
    runs = _absorb_gaps(_runs(samples), gap_tolerance)
    entries: list[Entry] = []

    for run in runs:
        if run.key is None:
            if len(run.samples) >= min_unknown_samples:
                entries.append(Entry(start=run.samples[0].time, end=0.0))
            continue
        hits = [s for s in run.samples if s.match]
        first = hits[0].match
        # most common title/artist spelling in the run wins
        best = max(hits, key=lambda s: sum(h.match.title == s.match.title for h in hits)).match
        entries.append(Entry(
            start=hits[0].time, end=0.0,
            title=best.title, artist=best.artist,
            isrc=next((h.match.isrc for h in hits if h.match.isrc), None),
            hits=len(hits), uncertain=len(hits) == 1,
            first_hit=hits[0].time, last_hit=hits[-1].time,
            extra=dict(first.extra),
        ))
        estimates = [h.time - h.match.offset_in_track for h in hits if h.match.offset_in_track is not None]
        if estimates:
            entries[-1].extra["_est_start"] = statistics.median(estimates)

    # refine starts, then fill ends
    prev_floor = 0.0
    for e in entries:
        est = e.extra.pop("_est_start", None)
        if est is not None and not e.unknown:
            e.start = max(prev_floor, min(e.start, est))
        if e.unknown:
            prev_floor = e.start
        else:
            prev_floor = e.last_hit + sample_len
    for a, b in zip(entries, entries[1:]):
        if b.start < a.start:  # can only happen with overlapping estimates
            b.start = a.start
        a.end = b.start
    if entries:
        entries[-1].end = duration
    if entries and entries[0].start < 1.0:
        entries[0].start = 0.0
    return entries
