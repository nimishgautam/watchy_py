"""Background calendar fetcher that writes meetings to a separate disk cache."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from . import calendar_merge
from . import microsoft_calendar

log = logging.getLogger(__name__)

CALENDAR_INTERVAL_SECONDS = 1200  # 20 minutes
CALENDAR_HOURS_AHEAD = 48
CALENDAR_MEETING_LIMIT = 5


class CalendarFetcher:
    """Fetches calendar events from Microsoft (and future: Google) and writes to cache."""

    def __init__(
        self,
        *,
        calendar_cache_path: Path | str,
        token_cache_path: Path | str,
        interval_seconds: int = CALENDAR_INTERVAL_SECONDS,
    ) -> None:
        self._calendar_cache_path = Path(calendar_cache_path)
        self._token_cache_path = Path(token_cache_path)
        self._interval = interval_seconds
        self._trigger_immediate = asyncio.Event()
        self._shutdown = asyncio.Event()

    def trigger_immediate(self) -> None:
        """Request an immediate fetch."""
        self._trigger_immediate.set()

    async def run(self) -> None:
        """Run fetch loop: fetch every interval, or immediately when triggered."""
        loop = asyncio.get_running_loop()
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(
                    self._trigger_immediate.wait(), timeout=self._interval
                )
            except asyncio.TimeoutError:
                pass
            self._trigger_immediate.clear()
            if self._shutdown.is_set():
                break
            await loop.run_in_executor(None, self._do_fetch)
        log.debug("Calendar fetcher shutdown complete")

    def _do_fetch(self) -> None:
        """Sync calendar fetch and cache write (runs in executor)."""
        try:
            from . import secrets
        except ImportError:
            log.debug("No secrets, skipping calendar fetch")
            return

        tenant = getattr(secrets, "MS_TENANT_ID", None)
        client_id = getattr(secrets, "MS_CLIENT_ID", None)
        client_secret = getattr(secrets, "MS_CLIENT_SECRET", None)
        if not tenant or not client_id:
            log.debug("Microsoft calendar not configured, skipping")
            return

        ms_meetings = microsoft_calendar.get_meetings(
            tenant,
            client_id,
            client_secret,
            token_cache_path=str(self._token_cache_path),
            hours_ahead=CALENDAR_HOURS_AHEAD,
            limit=CALENDAR_MEETING_LIMIT,
        )
        # TODO: add google_calendar.get_meetings(secrets.GOOGLE_...) when implemented
        merged = calendar_merge.merge_meetings(
            [ms_meetings] if ms_meetings is not None else [],
            limit=CALENDAR_MEETING_LIMIT,
        )

        self._calendar_cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._calendar_cache_path, "w") as f:
            json.dump({"meetings": merged}, f, separators=(",", ":"))
        log.info("Cached %d meetings to %s", len(merged), self._calendar_cache_path)
