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
| Connectivity | BLE (primary — data sync with laptop); WiFi 2.4 GHz (debug/webrepl only) |
| Battery | LiPo, voltage readable via ADC on pin 33 |
| Buttons | 4 — MENU (debug toggle), BACK (BLE sync / pairing), UP, DOWN — all wake from deep sleep |
| RAM | ~520 KB SRAM, ~4 MB flash; MicroPython overhead significant |

## Design Principles

1. **E-ink first.** The display doesn't refresh continuously, so every design
   choice should assume the user sees a static image for minutes at a time. High
   contrast, bold visual hierarchy, and glanceability matter more than
   pixel-perfect detail.

2. **Power budget drives architecture.** BLE is used for data sync (much
   lower power than WiFi). Not every display refresh needs a radio call.
   Data is fetched on quarter-boundary wakes and cached between fetches
   (see `update-strategy.md`).

3. **Graceful degradation.** The laptop may be asleep, out of range, or
   the BLE service may not be running. The display must always render
   *something* useful — stale cached data with an "X" indicator and
   hour-based weather labels is better than a blank quadrant or a
   traceback.

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

## Data Transport — BLE

The watch syncs data over **BLE** with a laptop running a GATT peripheral
service. The watch is the BLE Central (client); the laptop is the Peripheral
(server). The link is encrypted via LE Secure Connections bonding.

On each quarter-boundary wake (or manual BACK-button press), the watch:

1. Connects to the bonded laptop.
2. Sends a SYNC_REQUEST.
3. Receives a TIME_SYNC (UTC datetime) + SYNC_RESPONSE (chunked JSON).
4. Sends an ACK and disconnects.

The JSON payload schema:

```json
{
    "utc_offset": -5,
    "fetch_hour": 14,
    "fetch_minute": 30,
    "weather_now":  { "temp": 72, "condition": "sunny" },
    "weather_1h":   { "temp": 65, "condition": "rain" },
    "meetings": [
        { "date": "2025-02-28", "start_hour": 10, "start_minute": 30,
          "duration_min": 30, "title": "Standup", "type": "meeting" },
        ...
    ]
}
```

The laptop service is responsible for talking to Google Calendar, weather
APIs, handling OAuth, expanding recurring events, resolving timezones, and
trimming the response. The watch just sends a BLE request, parses the JSON
response, and caches the result.

The `fetch_hour` and `fetch_minute` fields (local time) indicate when the
weather was fetched. The watch uses these to display correct hour labels
(e.g. `14h` / `15h`) when data is stale, instead of the sync time.

**For development:** set `DUMMY_DATA = True` in `constants.py` to use
hardcoded mock data without touching BLE.

See `ble-protocol.md` for the full wire-level specification and
`update-strategy.md` for when/how syncs happen.

## Key Files

| File | Responsibility | Status |
|---|---|---|
| `main.py` | Entry point — instantiate Watchy and run | Exists |
| `watchy.py` | Core orchestrator — wake, button handling, BLE sync, cache, sleep | Exists |
| `renderer.py` | Drawing logic — layout zones, render each zone, stale indicators | **Done** |
| `clock_ring.py` | Ring clock rendering (arc bitmaps + hour number) | **Done** |
| `ble_client.py` | BLE Central client — scan, connect, pair, request sync, disconnect | **Done** |
| `ble_protocol.py` | Chunked message framing, message types, reassembly | **Done** |
| `constants.py` | Pin assignments, colors, layout constants, BLE UUIDs/timeouts | Exists |
| `secrets.py` | WiFi credentials (debug only) | Exists (example) |
| `boot.py` | MicroPython boot (WiFi for debug/webrepl if flagged) | Exists |

The separation is: "what to update" (`watchy.py`), "how to draw"
(`renderer.py`), "how to communicate" (`ble_client.py` + `ble_protocol.py`).

## Development Order

Implementation should follow this sequence:

1. ~~**Ring clock proof-of-concept.**~~ **Done.** Arc bitmap blitting works on
   hardware. Transparency keying, bitmap format, and visual quality all
   confirmed. `clock_ring.py` is the production implementation.

2. ~~**Static layout with mock data.**~~ **Done.** All four zones rendered with
   mock data. `renderer.py` is live; `test_top_half.py` and
   `test_bottom_half.py` can be used to evaluate layout on hardware.

3. **Wake / sleep cycle.** Wire up the BM8563 alarm-driven wake schedule and
   deep sleep. Verify the 8-wakes-per-hour cadence works reliably.

4. ~~**BLE data transport (watch side).**~~ **Done.** `ble_client.py` and
   `ble_protocol.py` implement the watch-side Central client with chunked
   message protocol, bonding, and cache. `watchy.py` integrates BLE sync
   into the wake cycle with BACK button for manual sync and pairing.
   Stale-data rendering (X indicator, hour-based weather labels) is
   implemented in `renderer.py`.

5. **Laptop BLE service.** Build the GATT peripheral on macOS/Linux that
   responds to SYNC_REQUEST with weather + meetings + time. The
   `ble-protocol.md` spec is the contract.

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
