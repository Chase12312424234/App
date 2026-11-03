"""SQLite storage for jobs and cached results."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    settings_key  TEXT NOT NULL,
    status        TEXT NOT NULL,          -- queued | running | done | error
    stage         TEXT NOT NULL DEFAULT 'queued',
    message       TEXT NOT NULL DEFAULT '',
    samples_done  INTEGER NOT NULL DEFAULT 0,
    samples_total INTEGER NOT NULL DEFAULT 0,
    tracks_found  INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_video ON jobs(video_id, settings_key, status);
CREATE TABLE IF NOT EXISTS results (
    video_id      TEXT NOT NULL,
    settings_key  TEXT NOT NULL,
    title         TEXT NOT NULL,
    track_count   INTEGER NOT NULL,
    result_json   TEXT NOT NULL,
    created_at    REAL NOT NULL,
    PRIMARY KEY (video_id, settings_key)
);
"""

JOB_FIELDS = ("id", "url", "video_id", "settings_key", "status", "stage", "message",
              "samples_done", "samples_total", "tracks_found", "error", "created_at", "updated_at")


class DB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # jobs -------------------------------------------------------------
    def create_job(self, url: str, video_id: str, settings_key: str, status: str = "queued",
                   **fields) -> dict:
        now = time.time()
        job = {"id": uuid.uuid4().hex[:12], "url": url, "video_id": video_id,
               "settings_key": settings_key, "status": status, "stage": fields.pop("stage", status),
               "message": fields.pop("message", "Waiting in queue…"), "samples_done": 0,
               "samples_total": 0, "tracks_found": 0, "error": None,
               "created_at": now, "updated_at": now, **fields}
        self._q(f"INSERT INTO jobs ({','.join(JOB_FIELDS)}) VALUES ({','.join('?' * len(JOB_FIELDS))})",
                tuple(job[f] for f in JOB_FIELDS))
        return job

    def get_job(self, job_id: str) -> dict | None:
        rows = self._q("SELECT * FROM jobs WHERE id=?", (job_id,))
        return dict(rows[0]) if rows else None

    def update_job(self, job_id: str, **fields) -> None:
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._q(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def active_job(self, video_id: str, settings_key: str) -> dict | None:
        rows = self._q("SELECT * FROM jobs WHERE video_id=? AND settings_key=? AND status IN ('queued','running') "
                       "ORDER BY created_at LIMIT 1", (video_id, settings_key))
        return dict(rows[0]) if rows else None

    def next_queued(self) -> dict | None:
        rows = self._q("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1")
        return dict(rows[0]) if rows else None

    def queue_position(self, job_id: str) -> int:
        job = self.get_job(job_id)
        if not job or job["status"] != "queued":
            return 0
        return self._q("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND created_at < ?",
                       (job["created_at"],))[0][0]

    def requeue_interrupted(self) -> int:
        """Jobs left 'running' by a crash/restart go back in the queue (sample cache makes this cheap)."""
        with self._lock:
            cur = self._conn.execute("UPDATE jobs SET status='queued', stage='queued', "
                                     "message='Resuming after restart…' WHERE status='running'")
            return cur.rowcount

    # results ----------------------------------------------------------
    def save_result(self, video_id: str, settings_key: str, result: dict) -> None:
        known = sum(1 for e in result["entries"] if e.get("title"))
        self._q("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?)",
                (video_id, settings_key, result["info"]["title"], known, json.dumps(result), time.time()))

    def get_result(self, video_id: str, settings_key: str) -> dict | None:
        rows = self._q("SELECT result_json FROM results WHERE video_id=? AND settings_key=?",
                       (video_id, settings_key))
        return json.loads(rows[0][0]) if rows else None

    def recent_results(self, limit: int = 8) -> list[dict]:
        rows = self._q("SELECT video_id, title, track_count, created_at FROM results "
                       "ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def usage_totals(self) -> dict:
        rows = self._q("SELECT result_json FROM results")
        req = sum(json.loads(r[0])["usage"].get("requests", 0) for r in rows)
        return {"sets": len(rows), "requests": req}
