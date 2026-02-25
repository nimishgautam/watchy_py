# Watchy — Design Overview

## What This Is

A small e-ink status display built on the Watchy platform (ESP32 + 200×200 1-bit
e-ink + BM8563 RTC). It shows three categories of information:

1. **Date & Time** — the current date, hour, and approximate quarter-hour
2. **Weather & Status** — current conditions, near-future forecast, battery level
3. **Meetings** — upcoming calendar entries with timing and type info

The display is *not* a real-time clock. It updates 8 times per hour at specific
minutes aligned to quarter-hour boundaries (see `update-strategy.md`). Between
updates the ESP32 is in deep sleep, drawing near-zero current.

## Hardware Constraints

| Property | Value |
|---|---|
| Display | 200×200 px, 1-bit monochrome (black/white), e-ink |
| MCU | ESP32 (single core used), MicroPython |
| RTC | BM8563 via I2C, supports timed alarm wakeup |
| Connectivity | WiFi 2.4 GHz (high power draw — use sparingly) |
| Battery | LiPo, voltage readable via ADC on pin 33 |
| Buttons | 4 (menu, back, up, down) — wake from deep sleep |
| RAM | ~520 KB SRAM, ~4 MB flash; MicroPython overhead significant |

## Design Principles

1. **E-ink first.** The display doesn't refresh continuously, so every design
   choice should assume the user sees a static image for minutes at a time. High
   contrast, bold visual hierarchy, and glanceability matter more than
   pixel-perfect detail.

2. **Power budget drives architecture.** WiFi is the dominant power cost. Not
   every display refresh needs a network call. Data sources are fetched on
   independent schedules and cached between fetches (see `update-strategy.md`).

3. **Graceful degradation.** WiFi may be unavailable, APIs may fail, the
   calendar endpoint may be down. The display must always render *something*
   useful — stale cached data with an indicator is better than a blank quadrant
   or a traceback.

4. **Look nice.** This is a thing you wear and glance at dozens of times a day.
   Visual quality is a first-class requirement, not an afterthought. Whitespace,
   consistent line weights, and clear hierarchy are non-negotiable.

## High-Level Layout

The 200×200 display is divided into three zones (see `display-layout.md` for
pixel-level detail):

```
┌──────────────────────────────────────┐
│  Feb 24              ████░░░░░ batt  │  ← top strip (~16-20 px)
├──────────────────┬───────────────────┤
│                  │  ☀ 72°            │
│    ┌─────┐       │  🌧 65° (+1h)     │  ← upper section (~80 px)
│    │  3  │       │                   │
│    └─────┘       │                   │
│   (ring clock)   │   (weather)       │
├──────────────────┴───────────────────┤
│  10:30  Standup (30m)                │
│  11:00  Design review (60m)          │  ← bottom half (~100 px)
│  14:00  1:1 with Alex (30m)          │
│  ...                                 │
└──────────────────────────────────────┘
```

- **Top strip:** Date on the left, battery indicator on the right. Thin
  horizontal line below it separates it from the main content.
- **Upper-left (clock):** Large hour number centered inside a segmented ring
  that indicates the current quarter-hour and whether the next quarter is
  imminent.
- **Upper-right (weather):** Current weather icon + temp on one row, forecast
  (+1 hour) icon + temp on the next row.
- **Bottom half (meetings):** A list of upcoming calendar entries. Each entry
  conveys: time until start, duration, and meeting type/nature. The exact
  visual treatment is still open (see `display-layout.md § Meetings`).

## Server Endpoint

The watch talks to **one server endpoint** that returns a single JSON payload
containing everything the watch needs: meetings, weather, and timezone info.

```json
{
    "utc_offset": -5,
    "weather_now":  { "temp": 72, "condition": "sunny" },
    "weather_1h":   { "temp": 65, "condition": "rain" },
    "meetings": [
        { "start_hour": 10, "start_minute": 30, "duration_min": 30,
          "title": "Standup", "type": "meeting" },
        ...
    ]
}
```

The server is responsible for talking to Google Calendar, weather APIs, handling
OAuth, expanding recurring events, resolving timezones, and trimming the
response down to only what the watch needs. The watch just hits one URL, parses
a small JSON blob, and caches the result.

**For development:** we don't need the server yet. We use a **mock JSON file**
(stored on-device or served by a trivial local HTTP server) with the same
schema. This lets us iterate on the renderer and layout independently, then
build the real server later. The mock also serves as the contract / integration
test: if the mock renders correctly, the real server just needs to produce the
same shape.

See `update-strategy.md` for when/how this endpoint is called.

## Key Files (planned)

| File | Responsibility | Status |
|---|---|---|
| `main.py` | Entry point — instantiate Watchy and run | Exists |
| `watchy.py` | Core orchestrator — wake, decide what to update, sleep | Exists |
| `renderer.py` | Drawing logic — layout zones, render each zone | **Done** |
| `clock_ring.py` | Ring clock rendering (arc bitmaps + hour number) | **Done** |
| `data.py` | Server fetch + caching layer (one endpoint, one JSON blob) | Not yet |
| `constants.py` | Pin assignments, colors, layout constants | Exists |
| `secrets.py` | WiFi credentials, server URL | Exists (example) |
| `boot.py` | MicroPython boot (WiFi for debug/webrepl if flagged) | Exists |

This isn't final — the module boundaries may shift — but the separation of
"what to update" (watchy.py), "how to draw" (renderer), and "how to fetch"
(data) should hold.

## Development Order

Implementation should follow this sequence:

1. ~~**Ring clock proof-of-concept.**~~ **Done.** Arc bitmap blitting works on
   hardware. Transparency keying, bitmap format, and visual quality all
   confirmed. `clock_ring.py` is the production implementation.

2. **Static layout with mock data.** Render all four zones with hardcoded /
   mock data. Tune pixel positions, font sizes, whitespace. No WiFi, no
   server, no deep sleep — just get the screen looking right.
   - **Top half done** (top strip + clock + weather zone). `renderer.py` is
     live; `test_top_half.py` can be used to evaluate layout on hardware.
   - **Bottom half (meetings) still pending.**

3. **Wake / sleep cycle.** Wire up the BM8563 alarm-driven wake schedule and
   deep sleep. Verify the 8-wakes-per-hour cadence works reliably.

4. **Data fetching.** Connect to WiFi, hit the server endpoint, parse and cache
   the response. Integrate with the renderer.

5. **Server.** Build the real endpoint (calendar + weather + timezone). The mock
   JSON from step 2 is the spec.

## Font Pipeline

Bitmap fonts are generated offline using `font_to_py.py` (located at
`scripts/font_to_py.py` — this is Peter Hinch's tool that produces Python
modules compatible with the `Writer` class in `lib/writer.py`).

**Directory structure:**

```
assets/
  FiraSans-Regular.ttf        ← source TTF (Regular)
scripts/
  font_to_py.py               ← the generator tool
new_src/
  build/
    generate_fonts.py         ← generates any missing fonts; run with poetry
  src/assets/fonts/           ← generated Python font modules (output)
```

Run `poetry run python3 new_src/build/generate_fonts.py` to generate any
missing fonts. Use `--force` to regenerate all. Add new entries to the `FONTS`
list in that script as new sizes are needed.

**Note:** `FiraSans-Bold.ttf` is not currently in `assets/`. The existing
`fira_sans_bold_58.py` was generated from a Bold TTF that is no longer in the
repo. To generate bold fonts at other sizes, add `FiraSans-Bold.ttf` to
`assets/` and add entries for it in `generate_fonts.py`.
