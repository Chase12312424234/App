"""Cut short WAV samples out of a long mono WAV without loading it all."""

from __future__ import annotations

import io
import wave
from pathlib import Path


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def sample_times(duration: float, interval: float, sample_len: float) -> list[float]:
    """Start times for each sample. The last one is pulled back to fit the audio."""
    if duration <= 0:
        return []
    if duration <= sample_len:
        return [0.0]
    times = []
    t = 0.0
    while t + sample_len <= duration:
        times.append(round(t, 3))
        t += interval
    last = round(duration - sample_len, 3)
    if times and last - times[-1] > interval / 2:
        times.append(last)
    return times


def read_sample(path: Path, start: float, length: float) -> bytes:
    """Return a standalone WAV file (bytes) for [start, start+length)."""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        w.setpos(min(int(start * rate), w.getnframes()))
        frames = w.readframes(int(length * rate))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(w.getnchannels())
            out.setsampwidth(w.getsampwidth())
            out.setframerate(rate)
            out.writeframes(frames)
    return buf.getvalue()
