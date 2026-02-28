"""Merge meetings from multiple calendar sources.

When Google Calendar is added, sources = [ms_meetings, google_meetings].
"""

from __future__ import annotations


def merge_meetings(
    sources: list[list[dict]],
    *,
    limit: int = 5,
) -> list[dict]:
    """Merge meetings from multiple calendar sources, sorted by start, limited.

    Each source may be a list of BLE-format meeting dicts, or None/empty.
    Deduplication is best-effort (same start+title treated as duplicate).
    """
    meetings: list[dict] = []
    seen: set[tuple[str, int, int, str]] = set()

    for source in sources:
        if not source:
            continue
        for m in source:
            key = (
                m.get("date", ""),
                m.get("start_hour", 0),
                m.get("start_minute", 0),
                m.get("title", "")[:20],
            )
            if key in seen:
                continue
            seen.add(key)
            meetings.append(m)

    meetings.sort(
        key=lambda x: (x.get("date", ""), x.get("start_hour", 0), x.get("start_minute", 0))
    )
    return meetings[:limit]
