import asyncio
import wave

from dropfinder import identify as ident
from dropfinder.identify import SampleCache, identify_samples
from dropfinder.recognizers import Match, RateLimited


class Flaky:
    """Rate-limits the first call per sample, then matches; one sample always errors."""
    name = "flaky"

    def __init__(self):
        self.calls = 0

    async def recognize(self, wav_bytes):
        self.calls += 1
        if self.calls == 1:
            raise RateLimited("slow down")
        if self.calls == 3:
            return None
        return Match(title="T", artist="A")

    async def close(self):
        pass


def _wav(path, seconds=60):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000 * seconds)


def test_retry_cache_and_usage(tmp_path, monkeypatch):
    async def no_sleep(*_):
        pass
    monkeypatch.setattr(ident.asyncio, "sleep", no_sleep)
    wav = tmp_path / "a.wav"; _wav(wav)
    cache = SampleCache(tmp_path / "c.json", 12)
    rec = Flaky()
    res, usage = asyncio.run(identify_samples(wav, [0.0, 20.0, 40.0], rec, cache,
                                              sample_len=12, concurrency=1, request_delay=0))
    assert usage.requests == 4 and usage.retries == 1 and usage.rate_limited == 1
    assert usage.matched == 2 and usage.unmatched == 1
    assert [r.match is not None for r in res] == [True, False, True]

    # second run is fully cached: zero calls
    res2, usage2 = asyncio.run(identify_samples(wav, [0.0, 20.0, 40.0], Flaky(),
                                                SampleCache(tmp_path / "c.json", 12),
                                                sample_len=12, request_delay=0))
    assert usage2.requests == 0 and usage2.cached == 3


def test_failures_are_not_cached(tmp_path, monkeypatch):
    async def no_sleep(*_):
        pass
    monkeypatch.setattr(ident.asyncio, "sleep", no_sleep)

    class Broken:
        name = "broken"
        async def recognize(self, b): raise ConnectionError("down")
        async def close(self): pass

    wav = tmp_path / "a.wav"; _wav(wav, 20)
    cache = SampleCache(tmp_path / "c.json", 12)
    res, usage = asyncio.run(identify_samples(wav, [0.0], Broken(), cache, sample_len=12,
                                              max_retries=2, request_delay=0))
    assert usage.failed == 1 and usage.requests == 3 and res[0].error
    assert SampleCache(tmp_path / "c.json", 12).get(0.0) is None
