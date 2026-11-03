"""Offline fake provider for tests and dry runs. Makes no network calls."""

from __future__ import annotations

import hashlib

from .base import Match


class MockRecognizer:
    name = "mock"

    def __init__(self) -> None:
        self._n = 0

    async def recognize(self, wav_bytes: bytes) -> Match | None:
        # Pretend each "track" lasts 4 samples and every 7th sample is unmatched.
        self._n += 1
        if self._n % 7 == 0:
            return None
        idx = (self._n - 1) // 4 + 1
        return Match(title=f"Track {idx}", artist="Mock Artist",
                     isrc=hashlib.md5(str(idx).encode()).hexdigest()[:12].upper())

    async def close(self) -> None:
        pass
