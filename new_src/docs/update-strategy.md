# Update Strategy — Data Fetching, Scheduling & Power

## Core Principle

The display updates 8 times per hour. **Not every update fetches every data
source.** Each data source has its own refresh cadence based on how quickly it
changes and how expensive (in power) it is to fetch. The `update()` function
runs on every wake, but it must check *what* needs refreshing and only do that
work.

This is the single most important architectural point. Getting this wrong (e.g.,
activating BLE on every wake) will kill battery life.

## Wake Schedule

The BM8563 RTC alarm wakes the ESP32 from deep sleep at these minutes past
every hour:

| Minute | Purpose |
|---|---|
| **0** | Quarter boundary — display update + BLE sync (weather + meetings + time) |
| **13** | Ring transition (thin → thick for Q1) — display update only |
| **15** | Quarter boundary — display update + BLE sync |
| **28** | Ring transition (thin → thick for Q2) — display update only |
| **30** | Quarter boundary — display update + BLE sync |
| **43** | Ring transition (thin → thick for Q3) — display update only |
| **45** | Quarter boundary — display update + BLE sync |
| **58** | Ring transition (thin → thick for Q4) — display update only |

That's **8 wakes per hour**. Four of them are "quarter boundary" wakes (0, 15,
30, 45) where we sync data over BLE. Four are "ring transition" wakes
(13, 28, 43, 58) that only redraw the display from cached data — no BLE
needed.

## Data Source Refresh Cadence

| Source | When | BLE? | Notes |
|---|---|---|---|
| **Battery voltage** | Every wake (8×/hr) | No | Local ADC read, essentially free |
| **BLE sync** | Quarter boundaries (4×/hr): 0, 15, 30, 45 | Yes | One BLE exchange returns meetings + weather + utc_offset + time sync |
| **Time sync** | Every BLE sync (via TIME_SYNC message) | Yes | Replaces NTP — laptop sends UTC datetime (YMDHMS) over BLE. NTP kept as manual fallback. |

### BLE Sync

The watch connects to a bonded laptop running a GATT peripheral service
and exchanges a single request/response that provides everything:
meetings, current weather, ~4h-ahead weather, the current UTC offset, and a
UTC datetime for RTC drift correction. See `ble-protocol.md` for the full
wire-level specification and `design-overview.md § Data Transport` for
the JSON schema.

The watch either syncs (quarter boundary wakes or manual BACK-button
press) or doesn't (ring transition wakes). Simple.

The laptop service is responsible for talking to upstream APIs (Google
Calendar, weather, etc.), caching, and trimming the response. The watch
doesn't need to care — it just sends a SYNC_REQUEST and processes the
response.

### BLE Session Flow

```
wake at minute 0 (quarter boundary):
    1. BLE scan + connect to bonded laptop
    2. Write SYNC_REQUEST
    3. Receive TIME_SYNC + SYNC_RESPONSE (+ optional EXTRA)
    4. Write ACK, disconnect BLE
    5. Apply time correction from TIME_SYNC datetime
    6. Cache server_data to flash
    7. Render display from fresh data
    8. Deep sleep until minute 13

wake at minute 13 (ring transition):
    1. (no BLE)
    2. Render display from cached data (only ring state changes)
    3. Deep sleep until minute 15

wake at minute 15 (quarter boundary):
    1. BLE scan + connect to bonded laptop
    2. Write SYNC_REQUEST
    3. Receive TIME_SYNC + SYNC_RESPONSE
    4. Write ACK, disconnect BLE
    5. Cache server_data to flash
    6. Render display from fresh data
    7. Deep sleep until minute 28
```

Ring-transition wakes (13, 28, 43, 58) never touch BLE. They read cached
data from flash, update only the ring state, render, and go back to sleep.
These should be very fast (~1–2 seconds awake).

### Manual Sync (BACK Button)

A short press of the BACK button forces a BLE sync regardless of the wake
schedule. This lets the user recover from a missed sync without waiting
for the next quarter boundary.

### Stale Data Handling

If a BLE sync fails (laptop asleep, out of range, service not running),
the watch sets a `_server_data_stale` flag and renders from cached data:

- An "X" indicator appears on the top strip left of the battery icon.
- Weather labels switch from "now"/"+1h" to the hour they were fetched
  (e.g. "17h"/"18h").
- Ended meetings (start + duration in the past) are removed naturally
  by the existing render-time filter.
- The watch retries at the next quarter boundary or on manual BACK press.

## What Gets Redrawn When

Not every zone needs to be redrawn on every wake. However, because e-ink
retains its image, we can choose to do a full redraw every time (simplest) or
optimize with partial redraws:

| Wake type | What changes on screen |
|---|---|
| Quarter boundary (0, 15, 30, 45) | Ring (quarter goes from thick to next thin), possibly weather, possibly meetings |
| Ring transition (13, 28, 43, 58) | Ring only (current quarter thin → thick) |

**Recommendation:** Always do a full-frame render into the framebuffer (it's
fast — just filling a 5 KB buffer). For ring-transition wakes, consider using
**partial e-ink refresh** (`display.update(partial=True)`) since only the ring
changes. This avoids the full-screen flash and is faster. For quarter-boundary
wakes, use a **full refresh** to clear any e-ink ghosting artifacts.

Periodic full refresh is good for e-ink health anyway — prevents burn-in of
static elements (separator lines, etc.).

## Data Caching

Between fetches, the display renders from cached data. The cache must survive
deep sleep.

### Storage Options

| Option | Pros | Cons |
|---|---|---|
| **RTC memory** (512 bytes on ESP32) | Survives deep sleep, fast access | Very small; only fits a few values |
| **File on flash** | Plenty of space | Slower; flash wear if written too often |
| **Global variables** | Fastest | Lost on deep sleep (ESP32 resets) |

**Recommended approach:**

- **RTC memory** for small critical values: last NTP sync timestamp, last
  weather fetch timestamp, flags.
- **JSON file on flash** for structured data: cached weather response, cached
  meeting list. Written only when data actually changes (not on every wake).
  At 8 wakes/hour, that's up to 4 file writes/hour for calendar — acceptable
  for flash endurance.

### Cache Freshness

The cache tracks the hour and minute of the last successful BLE sync.
Data is considered stale immediately after a failed sync attempt.  The
renderer shows an "X" indicator and switches weather labels from relative
("now"/"+4h") to absolute (e.g. "17h"/"21h") using the cached fetch hour and later_hour.

The display should never show *nothing* just because a sync failed —
stale data is better than no data.

## RTC Alarm Programming

After each wake, before entering deep sleep, the system must program the
BM8563's alarm for the next wake time.

The next-wake-minute lookup given the current minute:

```
current → next
0–12   → 13
13–14  → 15
15–27  → 28
28–29  → 30
30–42  → 43
43–44  → 45
45–57  → 58
58–59  → 0 (next hour)
```

**Implementation note:** The BM8563 alarm on the current Watchy codebase is set
to "next minute" (`set_alarm_next_minute()`). This needs to be replaced with a
`set_alarm_at_minute(target_minute)` function that sets the alarm to fire when
the RTC minute register matches `target_minute`. If the target is 0 and the
current minute is 58+, the alarm fires at the top of the next hour.

If the BM8563 only supports minute-match alarms (not "minutes from now"), this
should work naturally — set minute alarm to the target, it fires when the
minute register rolls to that value.

## Wake → Sleep Flow (pseudocode)

```python
def update():
    now = rtc.datetime()
    minute = now[5]
    hour = now[4]

    battery = read_battery_voltage()

    should_sync = minute in (0, 15, 30, 45) or force_sync_flag
    force_sync_flag = False

    if should_sync:
        if DUMMY_DATA:
            server_data = build_mock_data()
            stale = False
        else:
            try:
                client = BLEClient()
                client.scan_and_connect()
                result = client.request_sync()  # returns data + datetime
                client.disconnect()
                server_data = result["data"]
                apply_time_sync(result["datetime"])
                cache_write(server_data, hour, minute)
                stale = False
            except:
                stale = True  # render from stale cache

    data = cache_read()
    stale_since_hour = cached_fetch_hour if stale else None

    render_display(
        time=rtc.datetime(),
        battery=battery,
        data=data,
        stale_since_hour=stale_since_hour,
    )

    next_minute = compute_next_wake(minute)
    rtc.set_alarm_at_minute(next_minute)
    deep_sleep()
```

Note how `render_display` receives the current RTC time. It uses that to
compute relative meeting times ("starts in X min") from the absolute
`start_hour`/`start_minute` in the cached data. This means even stale cached
meetings show correct timing as long as the RTC is accurate.

## Fallback: No BM8563

If the BM8563 is not detected (I2C scan fails), the system currently falls back
to `machine.RTC()` and disables deep sleep. In this mode, the update loop
should run on a timer instead of alarm-driven wakes. The same update logic
applies — just driven by `uasyncio` or a `machine.Timer` instead of deep sleep
cycles.

---

## Open Issues

### Laptop BLE Service (not yet built)

The watch connects over BLE to a laptop running a GATT peripheral that
provides the same JSON payload previously envisioned for an HTTP server.
See `ble-protocol.md` for the full wire-level specification.

The laptop service must:

- **Advertise** the custom service UUID and accept encrypted connections
  from the bonded watch.
- **Talk to Google Calendar** (OAuth, recurring event expansion, filtering
  to today's remaining meetings).
- **Talk to a weather API** (e.g., OpenWeatherMap free tier). Return
  current conditions + 1h forecast.
- **Return the current UTC offset** for the user's timezone, solving DST
  automatically.
- **Send a TIME_SYNC** message with the current UTC datetime so the watch
  can correct RTC drift (replaces NTP).
- **Keep the response small.** The chunked protocol handles arbitrary
  payload sizes, but a few hundred bytes of JSON is ideal.

**For development:** set `DUMMY_DATA = True` in `constants.py` to use
hardcoded mock data without touching BLE.

### BM8563 Alarm Feasibility (confirmed)

The existing `set_alarm_next_minute()` writes a target minute to the
`MINUTE_ALARM_REG` and disables hour/day/weekday matching. Adapting this to
`set_alarm_at_minute(target)` is a one-line change. The alarm fires whenever
the RTC's minute register rolls to the target value, regardless of hour —
exactly the behavior we need. No driver changes beyond renaming/parameterizing
the existing method.

### Font Pipeline

The existing font assets (58, 38, 28, 24 px) don't cover all the sizes the
new layout needs. New fonts must be generated using `scripts/font_to_py.py`
(Peter Hinch's tool). Required sizes are listed in `display-layout.md § Font
Usage`. A `scripts/generate_all_fonts.sh` script should be created to
regenerate all fonts in one command. See `design-overview.md § Font Pipeline`
for full details.
