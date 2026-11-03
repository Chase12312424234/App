import wave

import numpy as np

from dropfinder.drop import find_drop, find_drop_in_audio
from dropfinder.links import search_query, track_links

SR = 16000


def synth_track(intro=20.0, breakdown=16.0, drop_len=30.0, seed=0):
    """intro (kick+bass) -> breakdown (no bass, rising hats) -> drop (kick+bass, louder)."""
    rng = np.random.default_rng(seed)

    def beats(sec, bass_amp):
        t = np.arange(int(sec * SR)) / SR
        kick_env = np.exp(-((t % 0.5) * 30))          # 120 bpm kick
        kick = np.sin(2 * np.pi * 55 * t) * kick_env
        bass = np.sin(2 * np.pi * 45 * t) * 0.5
        hats = np.diff(rng.normal(0, 1, len(t) + 1)) * 0.03
        return (kick + bass) * bass_amp + hats

    t = np.arange(int(breakdown * SR)) / SR
    riser = np.diff(rng.normal(0, 1, len(t) + 1)) * (0.01 + 0.05 * t / breakdown)
    y = np.concatenate([beats(intro, 0.4), riser, beats(drop_len, 0.6)])
    return (y / np.max(np.abs(y)) * 0.8).astype(np.float32), intro + breakdown


def test_finds_synthetic_drop():
    y, expected = synth_track()
    t, score = find_drop_in_audio(y, SR)
    assert abs(t - expected) < 1.0, (t, expected)
    assert score > 6


def test_short_segment_returns_none():
    y, _ = synth_track(intro=5, breakdown=5, drop_len=5)
    assert find_drop_in_audio(y, SR) is None


def test_find_drop_uses_set_time(tmp_path):
    silence = np.zeros(SR * 60, dtype=np.float32)
    y, expected = synth_track()
    full = np.concatenate([silence, y])
    p = tmp_path / "set.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((full * 32767).astype(np.int16).tobytes())
    d = find_drop(p, 60.0, 60.0 + len(y) / SR)
    assert abs(d.time - (60 + expected)) < 1.0
    assert 0 < d.confidence <= 1


def test_links():
    assert search_query("Fred again.., Skrillex & Four Tet", "Baby Again (Original Mix)") == "Fred again.. Baby Again"
    links = track_links("Daft Punk", "One More Time", {"shazam_url": "https://shazam.com/x"})
    assert links["spotify"] == "https://open.spotify.com/search/Daft%20Punk%20One%20More%20Time"
    assert links["soundcloud"] == "https://soundcloud.com/search/sounds?q=Daft+Punk+One+More+Time"
    assert links["shazam"] == "https://shazam.com/x"
