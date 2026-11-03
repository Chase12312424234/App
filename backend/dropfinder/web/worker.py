"""Background worker: runs one set at a time so long sets never block a request
and we never hammer the recognition service with parallel sets."""

from __future__ import annotations

import logging
import threading
import time
import traceback

from ..config import Settings
from ..download import DownloadError
from ..pipeline import Progress, run, settings_key
from .db import DB

log = logging.getLogger("dropfinder.worker")


class Worker:
    def __init__(self, db: DB, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.key = settings_key(settings)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="dropfinder-worker", daemon=True)

    def start(self) -> None:
        n = self.db.requeue_interrupted()
        if n:
            log.info("re-queued %d interrupted job(s)", n)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.db.next_queued()
            if not job:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._process(job)

    def _process(self, job: dict) -> None:
        jid = job["id"]
        self.db.update_job(jid, status="running", stage="downloading", message="Starting…", error=None)
        last = [0.0]

        def progress(p: Progress) -> None:
            now = time.monotonic()
            # throttle DB writes during identification; always write stage changes
            if p.stage == "identifying" and now - last[0] < 0.4 and p.samples_done != p.samples_total:
                return
            last[0] = now
            self.db.update_job(jid, stage=p.stage, message=p.message, samples_done=p.samples_done,
                               samples_total=p.samples_total, tracks_found=p.tracks_found)

        try:
            result = run(job["url"], self.settings, progress=progress, log=lambda m: log.info(m))
            self.db.save_result(result["info"]["video_id"], self.key, result)
            known = sum(1 for e in result["entries"] if e.get("title"))
            self.db.update_job(jid, status="done", stage="done", tracks_found=known,
                               message=f"Done: {known} track{'s' * (known != 1)} identified.")
        except DownloadError as e:
            self.db.update_job(jid, status="error", stage="error", error=str(e), message=str(e))
        except Exception as e:  # never let one bad set kill the worker
            log.error("job %s failed:\n%s", jid, traceback.format_exc())
            self.db.update_job(jid, status="error", stage="error",
                               error=f"Something went wrong while processing this set ({type(e).__name__}: {e}).",
                               message="Failed.")
