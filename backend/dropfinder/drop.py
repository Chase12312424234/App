"""Find "the drop" inside a stretch of the set.

A drop is where the bass (and overall loudness) jumps after a build-up, which
usually has the kick and bassline removed. For every moment t in the segment we
compare the bass energy just after t with the energy in the build-up window
before it, add a bonus when that build-up is quieter than the track's typical
level, then snap to the exact frame where the bass comes back in.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np

N_FFT = 2048
HOP = 800             # 50 ms at 16 kHz
BASS_HZ = (30, 150)
PRE_S = 8.0           # build-up window before a candidate drop
POST_S = 4.0          # window after it
MIN_SEGMENT_S = 30.0


@dataclass
class Drop:
    time: float        # seconds from the start of the set
    score: float       # dB jump, roughly; bigger = more obvious drop
    confidence: float  # 0..1


def load_segment(wav_path: Path, start: float, end: float) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        a = max(0, int(start * sr))
        b = min(w.getnframes(), int(end * sr))
        w.setpos(a)
        raw = w.readframes(max(0, b - a))
    y = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return y, sr


def _smooth(x: np.ndarray, frames: int) -> np.ndarray:
    if frames <= 1:
        return x
    k = np.ones(frames, dtype=np.float32) / frames
    return np.convolve(np.pad(x, (frames // 2, frames - 1 - frames // 2), mode="edge"), k, mode="valid")


def _window_means(x: np.ndarray, pre: int, post: int) -> tuple[np.ndarray, np.ndarray]:
    """Mean of x[i-pre:i] and x[i:i+post] for every i (NaN where they don't fit)."""
    c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    n = len(x)
    i = np.arange(n)
    pre_m = np.full(n, np.nan)
    post_m = np.full(n, np.nan)
    ok = (i >= pre) & (i + post <= n)
    pre_m[ok] = (c[i[ok]] - c[i[ok] - pre]) / pre
    post_m[ok] = (c[i[ok] + post] - c[i[ok]]) / post
    return pre_m, post_m


def find_drop_in_audio(y: np.ndarray, sr: int) -> tuple[float, float] | None:
    """Return (seconds into y, score) of the most drop-like moment, or None."""
    if len(y) < sr * MIN_SEGMENT_S:
        return None
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    band = (freqs >= BASS_HZ[0]) & (freqs <= BASS_HZ[1])
    eps = 1e-10
    bass_db = 10 * np.log10(S[band].sum(axis=0) + eps)
    rms_db = 20 * np.log10(librosa.feature.rms(S=np.sqrt(S), frame_length=N_FFT, hop_length=HOP)[0] + eps)

    fps = sr / HOP
    bass_s = _smooth(bass_db, int(fps))   # 1 s smoothing for the window comparison
    rms_s = _smooth(rms_db, int(fps))
    pre, post = int(PRE_S * fps), int(POST_S * fps)

    b_pre, b_post = _window_means(bass_s, pre, post)
    r_pre, r_post = _window_means(rms_s, pre, post)
    typical = float(np.median(bass_s))
    buildup = np.clip(typical - b_pre, 0, None)       # quieter-than-usual bass before
    payoff = np.clip(b_post - typical, -6, None)      # and properly loud after
    score = (b_post - b_pre) + 0.5 * (r_post - r_pre) + 0.3 * buildup + 0.3 * payoff
    if np.all(np.isnan(score)):
        return None
    i = int(np.nanargmax(score))

    # snap to the frame where bass actually comes back (largest short-term rise near i)
    lightly = _smooth(bass_db, max(1, int(0.2 * fps)))
    rise = np.diff(lightly, prepend=lightly[0])
    lo, hi = max(0, i - int(1.5 * fps)), min(len(rise), i + int(1.5 * fps))
    j = lo + int(np.argmax(rise[lo:hi]))
    return j / fps, float(score[i])


def find_drop(wav_path: Path, start: float, end: float) -> Drop | None:
    y, sr = load_segment(wav_path, start, end)
    hit = find_drop_in_audio(y, sr)
    if not hit:
        return None
    offset, score = hit
    return Drop(time=round(start + offset, 2), score=round(score, 2),
                confidence=round(float(np.clip(score / 15.0, 0, 1)), 2))
