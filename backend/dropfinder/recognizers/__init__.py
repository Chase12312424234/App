from .base import Match, RateLimited, Recognizer


def get_recognizer(name: str) -> Recognizer:
    if name == "shazam":
        from .shazam import ShazamRecognizer
        return ShazamRecognizer()
    if name == "mock":
        from .mock import MockRecognizer
        return MockRecognizer()
    raise ValueError(f"unknown provider {name!r} (choose: shazam, mock)")


__all__ = ["Match", "RateLimited", "Recognizer", "get_recognizer"]
