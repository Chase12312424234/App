"""Common interface every recognition provider implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class RateLimited(Exception):
    """Provider asked us to slow down; the caller retries with backoff."""


@dataclass
class Match:
    title: str
    artist: str
    isrc: str | None = None
    confidence: float | None = None       # 0..1 when the provider reports one
    offset_in_track: float | None = None  # where in the track the sample was found (s)
    provider_id: str | None = None
    extra: dict = field(default_factory=dict)  # provider-specific bits (cover art, links…)


class Recognizer(Protocol):
    name: str

    async def recognize(self, wav_bytes: bytes) -> Match | None:
        """Return a Match, None for "no match", or raise on errors."""
        ...

    async def close(self) -> None: ...
