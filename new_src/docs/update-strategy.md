# Update Strategy — Data Fetching, Scheduling & Power

## Core Principle

The display updates 8 times per hour. **Not every update fetches every data
source.** Each data source has its own refresh cadence based on how quickly it
changes and how expensive (in power) it is to fetch. The `update()` function
runs on every wake, but it must check *what* needs refreshing and only do that
work.

This is the single most important architectural point. Getting this wrong (e.g.,
connecting to WiFi on every wake) will kill battery life.

## Wake Schedule

The BM8563 RTC alarm wakes the ESP32 from deep sleep at these minutes past
every hour:

| Minute | Purpose |
|---|---|
| **0** | Quarter boundary — display update + calendar + maybe weather/NTP |
| **13** | Ring transition (thin → thick for Q1) — display update only |
| **15** | Quarter boundary — display update + calendar |
| **28** | Ring transition (thin → thick for Q2) — display update only |
| **30** | Quarter boundary — display update + calendar + maybe weather/NTP |
| **43** | Ring transition (thin → thick for Q3) — display update only |
| **45** | Quarter boundary — display update + calendar |
| **58** | Ring transition (thin → thick for Q4) — display update only |

That's **8 wakes per hour**. Four of them are "quarter boundary" wakes (0, 15,
30, 45) where we may fetch data over WiFi. Four are "ring transition" wakes
(13, 28, 43, 58) that only redraw the display from cached data — no WiFi
needed.

## Data Source Refresh Cadence

| Source | When | WiFi? | Notes |
|---|---|---|---|
| **Battery voltage** | Every wake (8×/hr) | No | Local ADC read, essentially free |
| **Server endpoint** | Quarter boundaries (4×/hr): 0, 15, 30, 45 | Yes | One HTTP call returns meetings + weather + utc_offset |
| **NTP time sync** | Once/day: at 1:30 AM | Yes | RTC drift is ~seconds/day; more frequent is wasteful |

### Single Server Endpoint

The watch calls **one URL** and gets back a single JSON blob with everything:
meetings, current weather, +1h weather, and the current UTC offset. See
`design-overview.md § Server Endpoint` for the response schema.

This means we don't need to decide on the watch which data sources to fetch
on which wake — the server always returns the full picture. The watch either
calls the endpoint (quarter boundary wakes) or doesn't (ring transition wakes).
Simple.

The server is responsible for rate-limiting its own upstream API calls (e.g.,
caching weather for 30 min server-side, only querying Google Calendar when
needed). The watch doesn't need to care — it can call the endpoint as often
as it wants.

### WiFi Session Flow

```
wake at minute 0 (quarter boundary):
    1. WiFi connect
    2. Hit server endpoint → get JSON
    3. NTP sync if 1:30 AM
    4. WiFi disconnect
    5. Cache server response to flash
    6. Render display from fresh data
    7. Deep sleep until minute 13

wake at minute 13 (ring transition):
    1. (no WiFi)
    2. Render display from cached data (only ring state changes)
    3. Deep sleep until minute 15

wake at minute 15 (quarter boundary):
    1. WiFi connect
    2. Hit server endpoint → get JSON
    3. WiFi disconnect
    4. Cache server response to flash
    5. Render display from fresh data
    6. Deep sleep until minute 28
```

Ring-transition wakes (13, 28, 43, 58) never touch WiFi. They read cached
data from flash, update only the ring state, render, and go back to sleep.
These should be very fast (~1–2 seconds awake).

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

Each cached data source should track when it was last updated. If data is stale
beyond a threshold, the renderer should indicate this subtly (e.g., a small dot
or marker near the weather zone, or dimmed text). The display should never show
*nothing* just because a fetch failed — stale data is better than no data.

**Staleness thresholds (suggested):**

| Source | "Stale" after | "Very stale / unavailable" after |
|---|---|---|
| Calendar | 30 min (missed 2 fetches) | 2 hours |
| Weather | 2 hours | 6 hours |
| NTP | 48 hours | 1 week |

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
    minute = now[5]  # current minute
    hour = now[4]

    # Always: read battery (free, local ADC)
    battery = read_battery_voltage()

    # Quarter-boundary wake → fetch from server
    is_quarter = minute in (0, 15, 30, 45)
    if is_quarter:
        wifi_connect()
        try:
            server_data = fetch_server_endpoint()
            cache_write("server", server_data)
        except:
            pass  # render from stale cache

        # NTP: once/day at 1:30 AM
        if minute == 30 and hour == 1:
            try:
                sync_ntp()
            except:
                pass

        wifi_disconnect()

    # Load data (fresh if just fetched, cached otherwise)
    data = cache_read("server")

    # Render all zones from current RTC time + data + battery
    render_display(
        time=rtc.datetime(),
        battery=battery,
        data=data,
    )

    # Schedule next wake
    next_minute = compute_next_wake(minute)
    rtc.set_alarm_at_minute(next_minute)

    # Sleep
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

### Server Proxy (not yet built)

The watch assumes a single HTTP endpoint returning a combined JSON payload
(see `design-overview.md § Server Endpoint` for schema). The server must:

- **Talk to Google Calendar** (OAuth, recurring event expansion, filtering to
  today's remaining meetings). The ESP32 can't do OAuth or handle complex TLS
  flows — this is the main reason the proxy exists.
- **Talk to a weather API** (e.g., OpenWeatherMap free tier — up to 1000
  calls/day, plenty of headroom). Return current conditions + 1h forecast.
  The server can cache weather for 30+ minutes to stay well within rate limits.
- **Return the current UTC offset** for the user's timezone, solving DST
  automatically. The watch applies this offset when rendering; no hardcoded
  `UTC_OFFSET` in `secrets.py` needed.
- **Keep the response small.** The ESP32 buffers the full HTTP response in
  RAM (`urequests`). A few hundred bytes of JSON is ideal. The server trims
  fields, truncates long meeting titles, and returns only what the watch needs.

**Protocol:** Plain HTTP on the local network is strongly preferred over HTTPS.
TLS handshakes on MicroPython consume ~30–50 KB of heap, which is tight
alongside the framebuffer and font data. A local-network proxy avoids this
entirely and also centralizes API keys server-side (the watch only needs the
proxy URL + optionally a simple shared secret).

**For now:** The server doesn't exist yet and doesn't need to. We develop
against a **mock JSON** file with the same schema (either hardcoded on-device
or served by a one-liner local HTTP server). The mock is both the development
fixture and the integration contract. See `design-overview.md § Server
Endpoint`.

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
