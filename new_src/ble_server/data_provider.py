"""Data providers that supply the server_data JSON payload.

``DataProvider`` is the abstract interface.  ``DummyDataProvider`` returns
hard-coded weather and meetings anchored to the current local time so the
watch always renders something plausible during development.
``CacheBackedDataProvider`` reads from disk caches (weather + calendar) and merges.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from . import open_meteo

if TYPE_CHECKING:
    from .fetcher import WeatherFetcher

log = logging.getLogger(__name__)

# Max age (minutes) before weather cache is considered stale. If exceeded,
# trigger a refetch and return None so the watch gets ERR_NOT_READY.
WEATHER_CACHE_MAX_AGE_MINUTES = 60


class DataProvider(ABC):
    @abstractmethod
    def get_server_data(self) -> dict | None:
        """Return a ``server_data`` dict matching the BLE protocol schema.

        Returns None if data is unavailable (e.g. cache empty).
        """
        ...


class DummyDataProvider(DataProvider):
    """Returns static weather and meetings relative to *now*."""

    def get_server_data(self) -> dict:
        now = datetime.datetime.now(datetime.timezone.utc).astimezone()
        utc_offset = int(now.utcoffset().total_seconds()) // 3600

        h = now.hour
        m = now.minute

        meetings: list[dict] = []
        templates = [
            (0, 15, 30, "Standup", "recurring"),
            (1, 0, 60, "Design Review", "general"),
            (2, 30, 25, "1:1 w/ Alex", "call"),
        ]
        for dh, dm, dur, title, mtype in templates:
            start_h = (h + dh) % 24
            start_m = (m + dm) % 60
            meetings.append(
                {
                    "start_hour": start_h,
                    "start_minute": start_m,
                    "duration_min": dur,
                    "title": title,
                    "type": mtype,
                }
            )

        return {
            "utc_offset": utc_offset,
            "weather_now": {"temp": 4, "condition": "windy_rain"},
            "weather_later": {"temp": 6, "condition": "severe_weather"},
            "later_hour": (h + 4) % 24,
            "fetch_hour": h,
            "fetch_minute": m,
            "meetings": meetings,
        }


class CacheBackedDataProvider(DataProvider):
    """Reads server_data from disk caches (weather + calendar) and merges."""

    def __init__(
        self,
        weather_cache_path: Path | str,
        calendar_cache_path: Path | str,
        weather_fetcher: "WeatherFetcher",
        user_timezone: str | None = None,
    ) -> None:
        self._weather_cache_path = Path(weather_cache_path)
        self._calendar_cache_path = Path(calendar_cache_path)
        self._weather_fetcher = weather_fetcher
        self._user_timezone = user_timezone

    def get_server_data(self) -> dict | None:
        """Read both caches and merge. If weather missing/invalid, trigger fetch and return None."""
        try:
            if not self._weather_cache_path.exists():
                log.debug("Weather cache missing, triggering fetch")
                self._weather_fetcher.trigger_immediate()
                return None
            with open(self._weather_cache_path) as f:
                weather_data = json.load(f)
            if not isinstance(weather_data, dict) or "weather_now" not in weather_data:
                log.warning("Weather cache invalid, triggering fetch")
                self._weather_fetcher.trigger_immediate()
                return None

            # Staleness check: if cache has a timestamp and is too old, trigger
            # refetch and return None so the watch gets ERR_NOT_READY.
            # Use same timezone as fetcher so fetch_hour/fetch_minute compare correctly.
            fh = weather_data.get("fetch_hour")
            fm = weather_data.get("fetch_minute")
            if fh is not None and fm is not None:
                if self._user_timezone:
                    now = datetime.datetime.now(ZoneInfo(self._user_timezone))
                else:
                    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
                fetch_mins = fh * 60 + fm
                now_mins = now.hour * 60 + now.minute
                age_mins = now_mins - fetch_mins
                if age_mins < 0:
                    age_mins += 24 * 60
                if age_mins > WEATHER_CACHE_MAX_AGE_MINUTES:
                    log.debug(
                        "Weather cache stale (%d min old), triggering fetch",
                        age_mins,
                    )
                    self._weather_fetcher.trigger_immediate()
                    return None

            # Merge calendar (or use dummy if unavailable)
            meetings = open_meteo._dummy_meetings()
            if self._calendar_cache_path.exists():
                try:
                    with open(self._calendar_cache_path) as f:
                        cal_data = json.load(f)
                    if isinstance(cal_data, dict) and "meetings" in cal_data:
                        cal_meetings = cal_data["meetings"]
                        if isinstance(cal_meetings, list):
                            meetings = cal_meetings
                except (OSError, json.JSONDecodeError) as e:
                    log.debug("Calendar cache read failed: %s, using dummy", e)

            return {**weather_data, "meetings": meetings}
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Weather cache read failed: %s, triggering fetch", e)
            self._weather_fetcher.trigger_immediate()
            return None
