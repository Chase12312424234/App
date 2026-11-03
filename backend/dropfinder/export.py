"""Text tracklist output, 1001Tracklists style."""

from __future__ import annotations

from .merge import Entry


def fmt_time(seconds: float, force_hours: bool = False) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h or force_hours:
        return f"{h:d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def tracklist_text(entries: list[Entry], title: str | None = None, url: str | None = None,
                   drops: bool = False, links: bool = False) -> str:
    long_set = bool(entries) and entries[-1].end >= 3600
    lines = []
    if title:
        lines.append(title)
    if url:
        lines.append(url)
    if lines:
        lines.append("")
    for n, e in enumerate(entries, 1):
        ts = fmt_time(e.start, long_set)
        if e.unknown:
            line = f"{n:02d}. [{ts}] ID - ID"
        else:
            line = f"{n:02d}. [{ts}] {e.artist} - {e.title}" + (" (?)" if e.uncertain else "")
        if drops and e.drop:
            line += f"  · drop @ {fmt_time(e.drop['time'], long_set)}"
        lines.append(line)
        if links and e.links:
            for k in ("spotify", "soundcloud"):
                if k in e.links:
                    lines.append(f"      {k}: {e.links[k]}")
    lines.append("")
    lines.append("Tracklist by DropFinder")
    return "\n".join(lines) + "\n"
