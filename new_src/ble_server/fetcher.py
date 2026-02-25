"""Background weather fetcher that writes to disk cache."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path

from . import open_meteo

log = logging.getLogger(__name__)


class WeatherFetcher:
    """Fetches weather from Open-Meteo and writes server_data to cache."""

    def __init__(
        self,
        *,
        latitude: float,
        longitude: float,
        cache_path: Path | str,
        interval_seconds: int = 2700,
        timezone: str = "auto",
    ) -> None:
        self._latitude = latitude
        self._longitude = longitude
        self._cache_path = Path(cache_path)
        self._interval = interval_seconds
        self._timezone = timezone
        self._trigger_immediate = asyncio.Event()
        self._shutdown = asyncio.Event()

    def trigger_immediate(self) -> None:
        """Request an immediate fetch (e.g. when cache is empty on BLE request)."""
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
        log.debug("Fetcher shutdown complete")

    def _do_fetch(self) -> None:
        """Sync HTTP fetch and cache write (runs in executor). Weather only."""
        raw = open_meteo.fetch_weather(
            self._latitude, self._longitude, self._timezone
        )
        if raw is None:
            log.warning("Open-Meteo fetch failed")
            return
        now = datetime.datetime.now(datetime.timezone.utc).astimezone()
        tz_offset_h = int(now.utcoffset().total_seconds()) // 3600

        server_data = open_meteo.build_weather_data(raw, tz_offset_h)

        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cache_path, "w") as f:
            json.dump(server_data, f, separators=(",", ":"))
        log.info("Cached weather to %s", self._cache_path)
