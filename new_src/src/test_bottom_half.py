"""On-device test for the meetings zone renderer.

Renders the full watch face with focus on the bottom half — meetings list —
using hardcoded mock data.  No RTC, WiFi, or deep sleep.

Two test scenarios are defined below; swap SERVER_DATA to switch between them.

SCENARIO A — dense / no gap bar (default)
  HOUR=10, MINUTE=20.  First unended meeting starts in <15 min so no gap bar.
  Six meetings in the list; only the first 3 are shown (MEETINGS_MAX_ROWS=3).
  Visual states covered:
    - Row 1: in-progress → inverted
    - Row 2: starts in 10 min → inverted (within-15-min highlight)
    - Row 3: normal
    - Rows 4-6: clipped (verifies MAX_ROWS cap)

SCENARIO B — gap bar visible
  HOUR=9, MINUTE=00.  Next meeting starts at 10:30 → 90 min away → gap bar.
  Only 2 meetings listed so the "3-row cap" is not the binding constraint here;
  both rows render normally below the checkerboard strip.
"""

from lib.display import Display
from renderer import render_all

# --- Scenario A (default) ---
# "Current" time: 10:20
HOUR = 10
MINUTE = 20
WEEK_DAY = 3  # Wednesday

MONTH = 2    # February
DAY = 24

BATTERY_V = 3.8   # ~67% full

# Six meetings; relative to HOUR:MINUTE = 10:20:
#   10:05  live      30 min  in-progress (started 15 min ago, ends 10:35) → inverted
#   10:30  recurring 15 min  starts in 10 min → inverted (within-15)
#   10:45  call      45 min  starts in 25 min → normal
#   11:00  focus     60 min  starts in 40 min → normal (clipped by MAX_ROWS)
#   12:00  personal  90 min  normal, ●◑ duration (clipped)
#   14:00  general  150 min  normal, ●●+ duration (clipped)
SERVER_DATA = {
    "weather_now": {"temp": 72, "condition": "windy_rain"},
    "weather_1h":  {"temp": 65, "condition": "cloudy_thick"},
    "meetings": [
        {
            "start_hour": 10,
            "start_minute": 5,
            "duration_min": 30,
            "title": "Team standup",
            "type": "live",
        },
        {
            "start_hour": 10,
            "start_minute": 30,
            "duration_min": 15,
            "title": "Quick sync",
            "type": "recurring",
        },
        {
            "start_hour": 10,
            "start_minute": 45,
            "duration_min": 45,
            "title": "Client call",
            "type": "call",
        },
        {
            "start_hour": 11,
            "start_minute": 0,
            "duration_min": 60,
            "title": "Deep work: auth refactor",
            "type": "focus",
        },
        {
            "start_hour": 12,
            "start_minute": 0,
            "duration_min": 90,
            "title": "Lunch",
            "type": "personal",
        },
        {
            "start_hour": 14,
            "start_minute": 0,
            "duration_min": 150,
            "title": "Planning — this is a very long title that may clip",
            "type": "general",
        },
    ],
}

# --- Scenario B: gap bar ---
# Uncomment this block and comment out Scenario A above to test the gap bar.

HOUR = 9
MINUTE = 0

SERVER_DATA = {
    "weather_now": {"temp": 68, "condition": "night"},
    "weather_1h":  {"temp": 71, "condition": "night_snow"},
    "meetings": [
        {
            "start_hour": 10,
            "start_minute": 30,
            "duration_min": 30,
            "title": "Standup",
            "type": "recurring",
        },
        {
            "start_hour": 11,
            "start_minute": 0,
            "duration_min": 60,
            "title": "Design review",
            "type": "call",
        },
    ],
}

display = Display()
render_all(
    display.framebuf,
    hour=HOUR,
    minute=MINUTE,
    week_day=WEEK_DAY,
    month=MONTH,
    day=DAY,
    battery_voltage=BATTERY_V,
    server_data=SERVER_DATA,
)
display.update()
