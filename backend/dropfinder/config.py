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
