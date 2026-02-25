"""Google Calendar event fetcher. Placeholder for future integration.

TODO: OAuth + Google Calendar API (e.g. gcsa). When implemented, this module
will return the same BLE meeting format as microsoft_calendar for merging.
"""

from __future__ import annotations


def get_meetings(google_creds: object) -> list[dict] | None:
    """Fetch upcoming events from Google Calendar. Not yet implemented."""
    return None  # TODO: add when Google Calendar integration is implemented
