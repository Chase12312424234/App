"""HTTP API + static frontend.

POST /api/jobs                 {url, force?}  -> job (cached sets finish instantly)
GET  /api/jobs/{id}            job status, plus the result when done
GET  /api/jobs/{id}/events     Server-Sent Events stream of progress
GET  /api/sets/{video_id}.txt  plain-text tracklist export
GET  /api/recent               recently processed sets
GET  /api/config               the server's sampling settings
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import Settings
from ..download import extract_video_id
from ..export import tracklist_text
from ..pipeline import entries_from_result, settings_key
from .db import DB
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

FRONTEND_DIST = Path(os.environ.get("DROPFINDER_FRONTEND_DIST",
                                    Path(__file__).resolve().parents[3] / "frontend" / "dist"))


class JobIn(BaseModel):
    url: str
    force: bool = False


def create_app(settings: Settings | None = None, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    db = DB(settings.data_dir / "dropfinder.sqlite3")
    worker = Worker(db, settings)
    key = settings_key(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="DropFinder", lifespan=lifespan)
    app.state.db, app.state.worker, app.state.settings = db, worker, settings

    def job_view(job: dict, with_result: bool = True) -> dict:
        out = {k: job[k] for k in ("id", "video_id", "status", "stage", "message", "samples_done",
                                   "samples_total", "tracks_found", "error")}
        out["queue_position"] = db.queue_position(job["id"])
        if with_result and job["status"] == "done":
            out["result"] = db.get_result(job["video_id"], job["settings_key"])
        return out

    @app.post("/api/jobs")
    def create_job(body: JobIn) -> dict:
        url = body.url.strip()
        vid = extract_video_id(url)
        if not vid:
            raise HTTPException(400, "That doesn't look like a YouTube video link.")
        clean_url = f"https://www.youtube.com/watch?v={vid}"
        if not body.force and db.get_result(vid, key):
            job = db.create_job(clean_url, vid, key, status="done", stage="done", message="Loaded from cache.")
            return {**job_view(job), "cached": True}
        existing = db.active_job(vid, key)
        if existing:
            return {**job_view(existing), "cached": False}
        job = db.create_job(clean_url, vid, key)
        worker.notify()
        return {**job_view(job), "cached": False}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found.")
        return job_view(job)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str):
        if not db.get_job(job_id):
            raise HTTPException(404, "Job not found.")

        async def stream():
            last = None
            idle = 0
            while True:
                job = db.get_job(job_id)
                view = job_view(job, with_result=False)
                snapshot = json.dumps(view, sort_keys=True)
                if snapshot != last:
                    last, idle = snapshot, 0
                    yield f"data: {snapshot}\n\n"
                else:
                    idle += 1
                    if idle % 30 == 0:
                        yield ": keep-alive\n\n"
                if job["status"] in ("done", "error"):
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/sets/{video_id}.txt", response_class=PlainTextResponse)
    def export_txt(video_id: str, drops: bool = Query(False), links: bool = Query(False)):
        result = db.get_result(video_id, key)
        if not result:
            raise HTTPException(404, "No tracklist for that video yet.")
        info = result["info"]
        text = tracklist_text(entries_from_result(result), info["title"], info["webpage_url"],
                              drops=drops, links=links)
        return PlainTextResponse(text, headers={
            "Content-Disposition": f'attachment; filename="tracklist-{video_id}.txt"'})

    @app.get("/api/recent")
    def recent() -> list[dict]:
        return db.recent_results()

    @app.get("/api/config")
    def config() -> dict:
        return {"interval": settings.interval, "sample_len": settings.sample_len,
                "provider": settings.provider, "max_samples": settings.max_samples,
                "usage": db.usage_totals()}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = FRONTEND_DIST / path
            if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
