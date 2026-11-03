"""Tunable settings. Every value can be overridden from the CLI."""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Shazam resamples to 16 kHz mono internally; 16 kHz still keeps everything
# below 8 kHz, which is plenty for bass/RMS drop detection later.
SAMPLE_RATE = 16_000


@dataclass
class Settings:
    interval: float = 45.0          # seconds between sample starts
    sample_len: float = 12.0        # length of each sample sent for recognition
    provider: str = "shazam"
    concurrency: int = 2            # parallel recognition requests
    request_delay: float = 0.5      # pause after each request (per worker), be polite
    max_retries: int = 4            # retries per sample on errors / rate limits
    max_samples: int | None = None  # hard cap on API calls (handy while testing)
    gap_tolerance: int = 1          # unmatched/other samples allowed inside one track
    min_unknown_samples: int = 2    # unmatched run this long becomes an "ID - ID" row
    data_dir: Path = DEFAULT_DATA_DIR

    @classmethod
    def from_env(cls) -> "Settings":
        """Web-app settings from DROPFINDER_* environment variables (or a .env file)."""
        import os
        _load_dotenv()
        s = cls()
        env = os.environ.get
        for name, cast in (("interval", float), ("sample_len", float), ("provider", str),
                           ("concurrency", int), ("request_delay", float), ("max_retries", int),
                           ("max_samples", int), ("gap_tolerance", int), ("min_unknown_samples", int)):
            v = env(f"DROPFINDER_{name.upper()}")
            if v not in (None, ""):
                setattr(s, name, cast(v))
        if env("DROPFINDER_DATA_DIR"):
            s.data_dir = Path(env("DROPFINDER_DATA_DIR"))
        return s


def _load_dotenv() -> None:
    """Minimal .env support (KEY=value lines) from the repo root or backend/."""
    import os
    for p in (DEFAULT_DATA_DIR.parent.parent / ".env", DEFAULT_DATA_DIR.parent / ".env"):
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
