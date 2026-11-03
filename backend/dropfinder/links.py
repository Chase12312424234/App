"""Streaming links for an identified track, built without any API keys.

Spotify and SoundCloud links are search URLs: they open the service's search
page for "artist title", which lands on the track in almost every case and
never needs credentials. Shazam's own track page is included when known.
"""

from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

_VERSION_NOISE = re.compile(
    r"\s*[\(\[]\s*(original mix|extended mix|radio edit|remaster(ed)?( \d{4})?|\d{4} remaster(ed)?|"
    r"official (audio|video)|explicit|clean)\s*[\)\]]", re.I)
_FEAT = re.compile(r"\s*[\(\[]\s*(feat\.?|ft\.?|featuring)\s+[^\)\]]*[\)\]]", re.I)


def search_query(artist: str, title: str) -> str:
    title = _FEAT.sub("", _VERSION_NOISE.sub("", title)).strip()
    # first credited artist searches best ("A, B & C" -> "A")
    main_artist = re.split(r",| & | x | feat\.? | ft\.? ", artist, maxsplit=1, flags=re.I)[0].strip()
    return f"{main_artist} {title}".strip()


def track_links(artist: str, title: str, extra: dict | None = None) -> dict[str, str]:
    q = search_query(artist, title)
    links = {
        "spotify": f"https://open.spotify.com/search/{quote(q, safe='')}",
        "soundcloud": f"https://soundcloud.com/search/sounds?q={quote_plus(q)}",
        "youtube": f"https://www.youtube.com/results?search_query={quote_plus(q)}",
    }
    if extra and extra.get("shazam_url"):
        links["shazam"] = extra["shazam_url"]
    return links
