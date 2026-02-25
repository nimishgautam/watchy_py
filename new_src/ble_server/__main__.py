"""Entry point: ``python -m ble_server`` (from the new_src/ directory).

Starts the Watchy BLE sync peripheral with Open-Meteo weather data
(cached to disk, served from cache) and a platform-appropriate pairing agent.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from .agent import register_agent
from .calendar_fetcher import CalendarFetcher
from .data_provider import CacheBackedDataProvider
from .fetcher import WeatherFetcher
from .server import WatchyBLEServer

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ble_server")

BLE_SERVER_DIR = Path(__file__).resolve().parent
WEATHER_CACHE_PATH = BLE_SERVER_DIR / "cache" / "weather.json"
CALENDAR_CACHE_PATH = BLE_SERVER_DIR / "cache" / "calendar.json"
TOKEN_CACHE_PATH = BLE_SERVER_DIR / "cache" / "ms_token.json"


async def main() -> None:
    try:
        from . import secrets
    except ImportError:
        log.error(
            "secrets.py not found. Copy secrets.example.py to secrets.py "
            "and set LATITUDE, LONGITUDE."
        )
        sys.exit(1)

    agent_handle = await register_agent()

    weather_fetcher = WeatherFetcher(
        latitude=secrets.LATITUDE,
        longitude=secrets.LONGITUDE,
        cache_path=WEATHER_CACHE_PATH,
        interval_seconds=2700,
        timezone="auto",
    )
    calendar_fetcher = CalendarFetcher(
        calendar_cache_path=CALENDAR_CACHE_PATH,
        token_cache_path=TOKEN_CACHE_PATH,
        interval_seconds=1200,  # 20 minutes
    )
    provider = CacheBackedDataProvider(
        weather_cache_path=WEATHER_CACHE_PATH,
        calendar_cache_path=CALENDAR_CACHE_PATH,
        weather_fetcher=weather_fetcher,
    )

    weather_task = asyncio.create_task(weather_fetcher.run())
    calendar_task = asyncio.create_task(calendar_fetcher.run())
    if not WEATHER_CACHE_PATH.exists():
        weather_fetcher.trigger_immediate()
    calendar_fetcher.trigger_immediate()  # First calendar fetch right away

    server = WatchyBLEServer(data_provider=provider)

    await server.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    log.info("Server running — press Ctrl+C to stop")
    await stop_event.wait()

    await server.stop()
    weather_task.cancel()
    calendar_task.cancel()
    try:
        await weather_task
    except asyncio.CancelledError:
        pass
    try:
        await calendar_task
    except asyncio.CancelledError:
        pass
    log.info("Shutdown complete")

    # agent_handle (D-Bus MessageBus on Linux) is cleaned up by GC


if __name__ == "__main__":
    asyncio.run(main())
