"""Shazam recognition via the `shazamio` library. No account or key needed.

Uses Shazam's public, undocumented app endpoint: free, but it may rate-limit
or change without notice. Keep request rates modest.
"""

from __future__ import annotations

from shazamio import Shazam

from .base import Match, RateLimited


class ShazamRecognizer:
    name = "shazam"

    def __init__(self) -> None:
        self._client = Shazam()

    async def recognize(self, wav_bytes: bytes) -> Match | None:
        try:
            result = await self._client.recognize(wav_bytes)
        except Exception as e:  # shazamio surfaces HTTP errors as generic exceptions
            text = str(e).lower()
            if "429" in text or "too many" in text:
                raise RateLimited(str(e)) from e
            raise
        if not isinstance(result, dict):
            raise RuntimeError(f"unexpected Shazam response: {result!r:.200}")
        if result.get("retryms"):
            raise RateLimited(f"retry after {result['retryms']} ms")

        track = result.get("track")
        if not track:
            return None
        matches = result.get("matches") or [{}]
        images = track.get("images") or {}
        return Match(
            title=track.get("title", "").strip(),
            artist=track.get("subtitle", "").strip(),
            isrc=track.get("isrc"),
            confidence=None,  # Shazam doesn't report one; repeated hits are our signal
            offset_in_track=matches[0].get("offset"),
            provider_id=str(track.get("key")) if track.get("key") else None,
            extra={
                "shazam_url": track.get("url"),
                "cover": images.get("coverart"),
            },
        )

    async def close(self) -> None:
        http = getattr(self._client, "http_client", None)
        for attr in ("close", "aclose"):
            fn = getattr(http, attr, None)
            if fn:
                try:
                    await fn()
                except Exception:
                    pass
                break
