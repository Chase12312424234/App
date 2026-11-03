"""Get a set's audio as mono 16 kHz WAV, from a YouTube URL or a local file."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import yt_dlp

from .config import SAMPLE_RATE

_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")


class DownloadError(Exception):
    """A user-facing download failure (private video, age gate, etc.)."""


@dataclass
class VideoInfo:
    video_id: str
    title: str
    uploader: str | None
    duration: float | None
    webpage_url: str


def extract_video_id(url: str) -> str | None:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    m = _ID_RE.search(url)
    return m.group(1) if m else None


def _friendly(msg: str) -> DownloadError | None:
    """Map yt-dlp errors that won't be fixed by retrying to a clear message."""
    low = msg.lower()
    if "private video" in low:
        return DownloadError("This video is private, so it can't be processed.")
    if "confirm your age" in low or "age-restricted" in low or "inappropriate for some users" in low:
        return DownloadError("This video is age-restricted; YouTube only serves it to signed-in users.")
    if "members-only" in low or "join this channel" in low:
        return DownloadError("This video is members-only.")
    if "video unavailable" in low or "has been removed" in low or "not available in your country" in low:
        return DownloadError("This video is unavailable (removed, region-locked, or the link is wrong).")
    if "premiere" in low or "live event will begin" in low:
        return DownloadError("This is an upcoming premiere/live stream; try once it has finished.")
    if "is not a valid url" in low or "unsupported url" in low:
        return DownloadError("That doesn't look like a YouTube link.")
    return None


def _blocked_message(last: str) -> DownloadError:
    if "not a bot" in last.lower() or "403" in last:
        return DownloadError(
            "YouTube refused to serve this video to this machine (it often blocks cloud/datacenter IPs). "
            "Run DropFinder on your own computer, or pass the path of an audio file you already have.")
    return DownloadError(f"Download failed: {last}")


def _to_wav(src: Path, dst: Path) -> None:
    tmp = dst.with_suffix(".tmp.wav")
    try:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vn",
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(tmp)],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"ffmpeg couldn't read the audio (exit {e.returncode}).") from None
    tmp.replace(dst)


def _local_file(path: Path, cache_dir: Path, log) -> tuple[VideoInfo, Path]:
    h = hashlib.sha1(f"{path.resolve()}:{path.stat().st_size}:{path.stat().st_mtime_ns}".encode()).hexdigest()[:11]
    out_dir = cache_dir / f"file-{h}"
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / "audio.wav"
    if not wav.exists():
        log(f"Converting {path.name} to mono WAV…")
        _to_wav(path, wav)
    info = VideoInfo(video_id=out_dir.name, title=path.stem, uploader=None, duration=None, webpage_url=str(path))
    (out_dir / "info.json").write_text(json.dumps(asdict(info), indent=2))
    return info, wav


def fetch_audio(source: str, cache_dir: Path, cookies: Path | None = None, log=print) -> tuple[VideoInfo, Path]:
    """Return (info, path to mono WAV). Re-uses cached files when present."""
    if Path(source).is_file():
        return _local_file(Path(source), cache_dir, log)

    vid = extract_video_id(source)
    if vid:
        info_path, wav_path = cache_dir / vid / "info.json", cache_dir / vid / "audio.wav"
        if info_path.exists() and wav_path.exists():
            log("Using cached audio.")
            return VideoInfo(**json.loads(info_path.read_text())), wav_path

    base_opts: dict = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "retries": 3,
    }
    if shutil.which("deno"):
        base_opts["js_runtimes"] = {"deno": {}}
    elif shutil.which("node"):
        base_opts["js_runtimes"] = {"node": {}}
    if cookies:
        base_opts["cookiefile"] = str(cookies)

    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            meta = ydl.extract_info(source, download=False)
            if meta.get("_type") == "playlist":
                raise DownloadError("That's a playlist link; paste the link of a single video.")
            if meta.get("is_live"):
                raise DownloadError("This live stream is still running; try once it has finished.")
            info = VideoInfo(
                video_id=meta["id"],
                title=meta.get("title") or meta["id"],
                uploader=meta.get("uploader"),
                duration=meta.get("duration"),
                webpage_url=meta.get("webpage_url") or source,
            )
            out_dir = cache_dir / info.video_id
            out_dir.mkdir(parents=True, exist_ok=True)
            wav_path = out_dir / "audio.wav"
            if not wav_path.exists():
                for old in out_dir.glob("source.*"):
                    old.unlink()
                log(f"Downloading audio for “{info.title}”…")
                ydl.params["outtmpl"] = {"default": str(out_dir / "source.%(ext)s")}
                ydl.process_info(meta)
                src = next(p for p in out_dir.glob("source.*") if not p.name.endswith(".part"))
                log("Converting to mono WAV…")
                _to_wav(src, wav_path)
                src.unlink()
    except DownloadError:
        raise
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).removeprefix("ERROR: ")
        raise (_friendly(msg) or _blocked_message(msg)) from None

    (out_dir / "info.json").write_text(json.dumps(asdict(info), indent=2))
    return info, wav_path
