"""On-device test for the full top-half layout.

Renders the top strip (date + battery), separator lines, ring clock, and
weather zone with hardcoded values.  No RTC, WiFi, or deep sleep — just
the complete top half drawn to the e-ink display so the layout and pixel
positions can be evaluated on real hardware.

Adjust the constants below to test different states:
  - BATTERY_V: try 3.0 (empty), 3.6 (half), 4.2 (full)
  - HOUR / MINUTE: any time to exercise different ring arc states
  - MONTH / DAY: date string in the top strip
  - SERVER_DATA: different temps / conditions to check text fitting
"""

from lib.display import Display
from renderer import render_all

HOUR = 3
MINUTE = 7
WEEK_DAY = 3  # Wednesday
YEAR = 2025
MONTH = 2    # February
DAY = 24

BATTERY_V = 3.8   # ~67% full

SERVER_DATA = {
    "weather_now": {"temp": 72, "condition": "sunny_rain"},
    "weather_1h":  {"temp": 65, "condition": "cloudy_thin"},
    "fetch_hour": HOUR,
    "fetch_minute": MINUTE,
    "meetings": [],
}

display = Display()
render_all(
    display.framebuf,
    hour=HOUR,
    minute=MINUTE,
    week_day=WEEK_DAY,
    year=YEAR,
    month=MONTH,
    day=DAY,
    battery_voltage=BATTERY_V,
    server_data=SERVER_DATA,
)
display.update()
