import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dropfinder import pipeline
from dropfinder.config import Settings
from dropfinder.download import DownloadError, VideoInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    wav = tmp_path / "set.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        rng = np.random.default_rng(0)
        w.writeframes((rng.normal(0, 0.1, 16000 * 600) * 32767).astype(np.int16).tobytes())

    def fake_fetch(source, cache_dir, cookies=None, log=print):
        if "PRIVATEVIDX" in source:
            raise DownloadError("This video is private, so it can't be processed.")
        vid = source.split("v=")[-1]
        (cache_dir / vid).mkdir(parents=True, exist_ok=True)
        return VideoInfo(vid, "Test Set", "DJ", 600, source), wav

    monkeypatch.setattr(pipeline, "fetch_audio", fake_fetch)
    from dropfinder.web.app import create_app
    settings = Settings(provider="mock", request_delay=0, data_dir=tmp_path / "data")
    with TestClient(create_app(settings)) as c:
        yield c


def wait_done(c, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_full_flow_and_cache(client):
    r = client.post("/api/jobs", json={"url": "https://youtu.be/abcdefghijk"})
    assert r.status_code == 200 and r.json()["cached"] is False
    job = wait_done(client, r.json()["id"])
    assert job["status"] == "done", job
    entries = job["result"]["entries"]
    assert len([e for e in entries if e["title"]]) >= 3
    assert entries[0]["links"]["spotify"].startswith("https://open.spotify.com/search/")

    # same video again -> instant, from cache
    r2 = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"}).json()
    assert r2["cached"] is True and r2["status"] == "done" and r2["result"]

    txt = client.get("/api/sets/abcdefghijk.txt?drops=1")
    assert txt.status_code == 200 and "01. [00:00] Mock Artist - Track 1" in txt.text
    assert client.get("/api/recent").json()[0]["video_id"] == "abcdefghijk"


def test_sse_stream_ends_with_done(client):
    job = client.post("/api/jobs", json={"url": "https://youtu.be/zzzzzzzzzzz"}).json()
    with client.stream("GET", f"/api/jobs/{job['id']}/events") as s:
        events = [line for line in s.iter_lines() if line.startswith("data:")]
    assert '"status": "done"' in events[-1]


def test_errors(client):
    assert client.post("/api/jobs", json={"url": "not a link"}).status_code == 400
    job = client.post("/api/jobs", json={"url": "https://youtu.be/PRIVATEVIDX"}).json()
    j = wait_done(client, job["id"])
    assert j["status"] == "error" and "private" in j["error"]
    assert client.get("/api/jobs/nope").status_code == 404
