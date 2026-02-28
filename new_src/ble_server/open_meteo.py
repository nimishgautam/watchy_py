"""Open-Meteo API client and WMO-to-canonical-condition mapping."""

from __future__ import annotations

import datetime
from typing import Any

import requests

WIND_SPEED_THRESHOLD_KMH = 35
WIND_GUST_THRESHOLD_KMH = 50
API_URL = "https://api.open-meteo.com/v1/forecast"


def wmo_to_condition(
    weather_code: int,
    is_day: int,
    wind_speed: float,
    wind_gusts: float,
) -> str:
    """Map Open-Meteo WMO code + is_day + wind to canonical condition."""
    is_windy = (
        wind_speed >= WIND_SPEED_THRESHOLD_KMH or wind_gusts >= WIND_GUST_THRESHOLD_KMH
    )

    # Base condition from WMO code (without wind override)
    if weather_code in (95, 96, 99):
        return "severe_weather"
    if weather_code in (66, 67):
        return "severe_weather"
    if weather_code in (56, 57):
        return "severe_weather"
    if weather_code in (71, 73, 75, 77):
        base = "snow" if is_day else "night_snow"
    elif weather_code in (85, 86):
        base = "snow" if is_day else "night_snow"
    elif weather_code in (51, 53, 55, 61, 63, 65, 81, 82):
        base = "rain" if is_day else "night_rain"
    elif weather_code == 80:
        base = "sunny_rain" if is_day else "night_rain"
    elif weather_code in (45, 48):
        base = "cloudy_thick"
    elif weather_code == 0:
        base = "sunny" if is_day else "night"
    elif weather_code == 1:
        base = "cloudy_light" if is_day else "night"
    elif weather_code == 2:
        base = "cloudy_thin" if is_day else "night"
    elif weather_code == 3:
        base = "cloudy_thick" if is_day else "night"
    else:
        base = "cloudy_thick"

    # Wind override
    if not is_windy:
        return base
    if base in ("rain", "sunny_rain", "night_rain"):
        return "windy_rain"
    if base in ("snow", "night_snow"):
        return "snow_storm"
    if base in ("sunny", "cloudy_light", "cloudy_thin", "cloudy_thick", "night"):
        return "windy"
    return base


def fetch_weather(lat: float, lon: float, timezone: str = "auto") -> dict[str, Any] | None:
    """Fetch weather from Open-Meteo. Returns raw API response or None on failure."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        "temperature_unit": "celsius",
        "current": "temperature_2m,weather_code,is_day,wind_speed_10m,wind_gusts_10m",
        "hourly": "temperature_2m,weather_code,is_day,wind_speed_10m,wind_gusts_10m",
    }
    try:
        r = requests.get(API_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _dummy_meetings() -> list[dict[str, Any]]:
    """Placeholder meetings anchored to current local time."""
    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    today = now.strftime("%Y-%m-%d")
    h, m = now.hour, now.minute
    templates = [
        (0, 15, 30, "Standup", "recurring"),
        (1, 0, 60, "Design Review", "general"),
        (2, 30, 25, "1:1 w/ Alex", "call"),
    ]
    meetings: list[dict[str, Any]] = []
    for dh, dm, dur, title, mtype in templates:
        start_h = (h + dh) % 24
        start_m = (m + dm) % 60
        meetings.append(
            {
                "date": today,
                "start_hour": start_h,
                "start_minute": start_m,
                "duration_min": dur,
                "title": title,
                "type": mtype,
            }
        )
    return meetings


def build_weather_data(api_response: dict[str, Any], tz_offset_h: int) -> dict[str, Any]:
    """Build weather-only dict (utc_offset, weather_now, weather_1h). No meetings."""
    return _build_weather_from_response(api_response, tz_offset_h)


def build_server_data(
    api_response: dict[str, Any],
    tz_offset_h: int,
    *,
    meetings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build full server_data dict from Open-Meteo API response and optional meetings."""
    data = _build_weather_from_response(api_response, tz_offset_h)
    data["meetings"] = meetings if meetings is not None else _dummy_meetings()
    return data


def _build_weather_from_response(
    api_response: dict[str, Any], tz_offset_h: int
) -> dict[str, Any]:
    """Build weather-only dict from Open-Meteo API response."""
    current = api_response.get("current", {})
    hourly = api_response.get("hourly", {})

    temp_now = current.get("temperature_2m")
    code_now = current.get("weather_code", 0)
    is_day_now = current.get("is_day", 1)
    wind_now = current.get("wind_speed_10m", 0) or 0
    gusts_now = current.get("wind_gusts_10m", 0) or 0

    weather_now = {
        "temp": int(round(temp_now)) if temp_now is not None else 0,
        "condition": wmo_to_condition(code_now, is_day_now, wind_now, gusts_now),
    }

    # weather_1h: next full hour from hourly arrays
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    codes = hourly.get("weather_code", [])
    is_days = hourly.get("is_day", [])
    winds = hourly.get("wind_speed_10m", [])
    gusts = hourly.get("wind_gusts_10m", [])

    now_local = datetime.datetime.now(datetime.timezone.utc).astimezone()
    target = (now_local + datetime.timedelta(hours=1)).replace(
        minute=0, second=0, microsecond=0
    )
    target_str = target.strftime("%Y-%m-%dT%H:%M")

    idx_1h = 0
    for i, t in enumerate(times):
        if str(t) >= target_str:
            idx_1h = i
            break

    temp_1h = temps[idx_1h] if idx_1h < len(temps) else temp_now
    code_1h = codes[idx_1h] if idx_1h < len(codes) else code_now
    is_day_1h = is_days[idx_1h] if idx_1h < len(is_days) else 1
    wind_1h = winds[idx_1h] if idx_1h < len(winds) else 0
    gusts_1h = gusts[idx_1h] if idx_1h < len(gusts) else 0

    weather_1h = {
        "temp": int(round(temp_1h)) if temp_1h is not None else 0,
        "condition": wmo_to_condition(
            code_1h, is_day_1h, wind_1h or 0, gusts_1h or 0
        ),
    }

    return {
        "utc_offset": tz_offset_h,
        "weather_now": weather_now,
        "weather_1h": weather_1h,
        "fetch_hour": now_local.hour,
        "fetch_minute": now_local.minute,
    }
