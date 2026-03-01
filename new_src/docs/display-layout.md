# Display Layout — Pixel-Level Spec

## Display Properties

- **Resolution:** 200 × 200 pixels
- **Color depth:** 1-bit (black = 0, white = 1)
- **Framebuffer format:** `MONO_HLSB`
- **Partial refresh:** Supported via `display.update(partial=True)`

## Zone Map

All coordinates are (x, y) from top-left origin. Widths/heights are approximate
and should be tuned during implementation, but these are the starting targets.

```
y=0   ┌────────────────────────────────────────┐ x=199
      │          TOP STRIP (date + batt)        │
y=23  ├────────────────────────────────────────┤
y=24  │                                        │
      │   CLOCK (ring + hour)  │  WEATHER      │
      │       100 × 103        │  100 × 103    │
      │                        │               │
y=126 │                        │               │
y=127 ├────────────────────────┴───────────────┤
y=128 │  [gap bar — optional checkerboard]      │
      │            MEETINGS LIST               │
      │             200 × 72                   │
      │                                        │
y=199 └────────────────────────────────────────┘
      x=0                                x=199
```

### Zone 1: Top Strip (y: 0–23)

**Purpose:** Date and battery — ambient context you rarely focus on but want
available at a glance.

| Element | Position | Details |
|---|---|---|
| Date text | Left-aligned, ~x=4, vertically centered | Format: `Feb 24` (month abbreviated, day numeric). Small font, ~12–14 px height. |
| Battery bar | Right-aligned, ~x=160–196, vertically centered | A horizontal bar, maybe 30×6 px. Filled portion proportional to charge. Outline always visible so an empty battery still reads as "battery." |
| Separator | Full width at y=23 | 1 px black horizontal line |

**Font:** Fira Sans Regular at a small size (need to generate a ~14 px bitmap
font), or a simple built-in if RAM is tight.

### Zone 2: Clock — Upper Left (x: 0–99, y: 24–127)

**Purpose:** The hero element. Hour number + quarter-ring. This is what you look
at when you raise your wrist.

Available area: 100 × 103 px.

#### Ring Clock

The hour number sits at the center of a circular ring divided into four arcs
(one per quarter-hour). The ring communicates which quarter of the hour we're in
and whether the next quarter boundary is imminent.

**Geometry:**

| Property | Value |
|---|---|
| Ring center | (50, 75) relative to display origin |
| Outer radius | 46 px |
| Inner radius (thick/complete) | 39 px (ring width = 7 px) |
| Inner radius (thin/in-progress) | 43 px (ring width = 3 px) |
| Interior diameter | ~74 px (for the hour number) |

**Quarter positions (clockwise from 12-o'clock):**

| Quarter | Arc | Represents |
|---|---|---|
| Q1 | 12 o'clock → 3 o'clock (top-right) | Minutes 0–14 |
| Q2 | 3 o'clock → 6 o'clock (bottom-right) | Minutes 15–29 |
| Q3 | 6 o'clock → 9 o'clock (bottom-left) | Minutes 30–44 |
| Q4 | 9 o'clock → 12 o'clock (top-left) | Minutes 45–59 |

**Ring segment states:**

| State | Visual | Meaning |
|---|---|---|
| Empty | No arc drawn (background shows through) | This quarter hasn't started |
| Thin | 3 px wide arc | Currently in this quarter (first 13 minutes) |
| Thick | 7 px wide arc (bold, filled) | This quarter is almost over (last 2 minutes) or already complete |

**State table by minute:**

| Minutes past hour | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| 0–12 | thin | — | — | — |
| 13–14 | **thick** | — | — | — |
| 15–27 | **thick** | thin | — | — |
| 28–29 | **thick** | **thick** | — | — |
| 30–42 | **thick** | **thick** | thin | — |
| 43–44 | **thick** | **thick** | **thick** | — |
| 45–57 | **thick** | **thick** | **thick** | thin |
| 58–59 | **thick** | **thick** | **thick** | **thick** |

When all four segments go thick, the user knows: "the hour is about to turn
over." The thin→thick transition is the 2-minute warning.

#### Hour Number

- Centered inside the ring interior (~56 px diameter usable space)
- Bold font, ~28–32 px tall — needs to fit "12" (widest number) comfortably
- 12-hour format, no leading zero (1, 2, ... 12)
- No AM/PM indicator (you always know roughly what time of day it is)

#### Rendering Approach

**Recommended: pre-rendered bitmaps.** Drawing smooth arcs procedurally on a
1-bit framebuffer in MicroPython will produce jagged results and be slow.
Instead:

- Pre-render 3 versions of each quarter-arc: empty (nothing), thin (3 px),
  thick (7 px). That's 8 bitmaps (4 quarters × 2 visible states; empty = don't
  draw).
- Store as raw byte arrays or PBM files in flash.
- Blit the appropriate combination for the current minute.
- Render the hour number on top using the font engine.

This gives pixel-perfect control over how the arcs look, renders fast (just
memcpy), and lets you iterate on the design in a pixel editor rather than in
code.

**Alternative:** if RAM is tight, a lookup-table approach where you store just
the pixel coordinates for each arc segment and fill them at render time. Less
flexible but smaller.

#### Ring Clock — BUILD THIS FIRST

The ring clock is the visual centerpiece and the most technically uncertain
part of the renderer. It should be the **first thing implemented and tested on
real hardware**, before any other zone. Here's why:

1. **Bitmap transparency is unproven.** MicroPython's `framebuf.blit()` accepts
   a color key for transparency. The plan: store each arc segment as a
   rectangular bitmap where white = transparent, black = arc pixels. Call
   `blit(arc_fb, x, y, WHITE)` to overlay only the black pixels onto the main
   framebuffer. This *should* work, but "should" and "does on this specific
   hardware and MicroPython build" aren't always the same. If `blit()`
   transparency doesn't behave, the fallback is pixel-by-pixel iteration from
   the source bitmap — slower but reliable. Either way, we need to know early.

2. **Arc visual quality sets the tone.** If the arcs look jagged or muddy at
   35 px radius on 1-bit e-ink, we may need to adjust radii, ring width, or
   switch to a different visual metaphor (tick marks, pie wedges). Better to
   discover this in week 1 than after the rest of the layout is built.

3. **Bitmap toolchain needs proving.** We need a workflow for: design arc in
   pixel editor → export as 1-bit image → convert to `MONO_HLSB` byte array →
   load in MicroPython → blit onto framebuffer. Each step could have surprises
   (byte order, padding, orientation). A single end-to-end test with one arc
   segment validates the whole pipeline.

**Suggested first task:** Create one thin arc bitmap (Q1, top-right quadrant)
and one thick arc bitmap for the same quadrant. Blit them onto a white
framebuffer with the hour number "3" rendered on top. Push to the e-ink
display. Evaluate: does the transparency work? Do the arcs look clean? Is the
number readable inside the ring? Iterate until it looks good, then replicate
for the other three quadrants.

### Zone 3: Weather — Upper Right (x: 100–199, y: 24–127)

**Purpose:** Current conditions and near-future forecast at a glance.

Available area: 100 × 103 px.

**Layout — two rows, vertically stacked:**

```
  ┌──────────────────────────┐
  │  [icon]  72°  now        │  row 1, ~y=34–69
  │  [icon]  65°  +1h        │  row 2, ~y=80–115
  └──────────────────────────┘
```

| Element | Size | Notes |
|---|---|---|
| Weather icon | 28×28 px | Pre-rendered 1-bit bitmaps generated from curated SVG sources for canonical condition names. |
| Temperature | Numeric + degree symbol | Bold, ~18–22 px font. Fahrenheit or Celsius (configurable in secrets/constants). |
| Label | "now" / "+1h" | Small text or omit if space is too tight — the two-row position implies it. |

**If weather data is unavailable:** Show a placeholder (e.g., `--°` with a
generic icon or a small `?` glyph) so the layout doesn't collapse.

### Zone 4: Meetings — Bottom Half (x: 0–199, y: 128–199)

**Purpose:** Upcoming calendar entries.

Available area: 200 × 72 px.

#### What Each Meeting Entry Needs to Convey

At minimum, each entry communicates three things:

1. **When** — how soon until it starts (or "now" if in progress)
2. **How long** — the duration
3. **What kind** — the nature or type of the meeting

#### Possible Representations (not yet decided)

**Option A — Text rows:**
```
  10:30  Standup (30m)
  11:00  Design review (1h)
  14:00  1:1 w/ Alex (30m)
```
Simple, readable, easy to implement. With a 16 px time font and 14 px title font, fits 3 rows in the 72 px zone. Long titles clip naturally at the display edge.

**Option B — Compact glyphs + text:**
```
  ● 10:30  30m  Standup
  ◐ 11:00  1h   Design review
  ○ 14:00  30m  1:1 w/ Alex
```
A leading glyph encodes meeting type (●/◐/○ for e.g. required/optional/1:1, or
color-coded categories mapped to fill patterns). Duration gets its own column.

**Option C — Timeline bar:**
A visual timeline strip on the left edge showing relative time, with text labels
to the right. More visually interesting but harder to implement and less
information-dense.

#### Design Decisions — Current Choices

- **Visual format:** Option B (compact glyphs + text). Time and glyphs in 16 px font; title in 14 px font.
- **Row count:** Capped at 3 (`MEETINGS_MAX_ROWS = 3`). Row height: 20 px.
- **Column x-positions:** duration glyph(s)=4, time=42, type glyph=93, title=108. Tunable after hardware evaluation.
- **Time format:** Absolute (hour + minute stored; relative offset computed at render time from RTC).
- **Sorting / filtering:** Future meetings only (ended meetings excluded). Sorted by start time. Up to 3 shown.
- **Empty state:** Centered "No meetings" text in `font_small`.
- **In-progress / imminent indicator:** Inverted row (white text on black background) for meetings in progress or starting within 15 minutes.

#### Gap Bar

When the soonest upcoming meeting starts **60 or more minutes** from now, a
7 px tall checkerboard strip is drawn at the top of the meetings zone. The
checkerboard simulates a mid-grey tone on the 1-bit display, giving a visual
signal that there is free time right now. Event rows shift down by 5 px when
the bar is present to accommodate it.

Dynamic layout:

| State | First row y | Last row y | Bottom margin |
|---|---|---|---|
| Gap bar absent | 132 | 172 | 8 px |
| Gap bar present | 137 | 177 | 3 px |

The threshold (`GAP_BAR_THRESHOLD_MIN = 60`) is a device-side constant and can
be tuned without a server change. The server does not need to send a gap flag.

#### Meeting Data Object (preliminary)

Whatever the calendar endpoint returns, the renderer should receive a
normalized list like:

```python
meetings = [
    {
        "start_hour": 10,
        "start_minute": 30,
        "duration_min": 30,
        "title": "Standup",
        "type": "meeting",   # or "focus", "1:1", "external", etc.
    },
    ...
]
```

The renderer doesn't need to know about the server — it just draws from
this list.

> **Why absolute times, not relative.** An earlier draft used `start_min`
> (minutes from now). The problem: "now" changes between display refreshes.
> A meeting cached as "in 25 min" is actually "in 10 min" by the next wake
> but the cached value still says 25. Storing absolute times (hour + minute)
> lets the renderer compute the relative offset at draw time using the
> current RTC value, so the displayed "time until" is always correct even
> with stale cached data.
>
> **This also enables graceful degradation.** If the server is unreachable,
> the watch still has cached meetings with absolute times and a working RTC.
> It can continue to show accurate "starts in X min" / "happening now"
> indicators for hours after the last successful fetch. The meetings won't
> update, but the timing relative to "now" stays correct. This is the key
> benefit of computing relative times at render time rather than caching them.

---

## Visual Design Guidelines

### Whitespace

Leave at minimum 3–4 px of padding inside each zone. Don't let text or icons
touch the zone edges or separator lines. The zones are already small; cramming
content to the edges makes the whole thing feel suffocating.

### Separator Lines

- **Horizontal separator** below the top strip: 1 px, full width, at y=23.
- **Vertical separator** between clock and weather: 1 px, from y=24 to y=127.
- **Horizontal separator** between upper section and meetings: 1 px, full width, at y=127.

These thin structural lines anchor the layout. They should be visually quiet
(1 px, no bold) — scaffolding, not decoration.

### Font Usage

Stick to two weights of one typeface (Fira Sans Bold + Regular):

| Element | Font | Status |
|---|---|---|
| Hour number | Zen Dots 39 px (digits 0-9 only, slashed-zero patched) | `zen_dots_39` — **generated** |
| Temperature | Regular 20 px (Bold preferred — needs Bold TTF) | `fira_sans_regular_20` — **generated** |
| Date, weather labels | Regular 14 px | `fira_sans_regular_14` — **generated** |
| Meeting time + type/duration glyphs | Regular 20 px | `fira_sans_regular_20`, `symbols_16` — **generated** |
| Meeting title | Regular 14 px | `fira_sans_regular_14` — **generated** |

Fonts are generated via `new_src/build/generate_fonts.py`
(`poetry run python3 new_src/build/generate_fonts.py`). Add new size entries
there as needed. See `design-overview.md § Font Pipeline` for full details.

### Icon Design

All icons (weather, meeting type glyphs) should be pre-rendered 1-bit bitmaps
designed at exact target resolution. Do not try to scale or anti-alias —
embrace the pixel grid. Consistent stroke width across all icons (~2 px) keeps
the visual language coherent.

**Current status:** weather icons are generated at 28×28 from curated external
SVGs via `new_src/build/generate_icons.py`. The script stages canonical SVG
filenames under `new_src/src/assets/icons/svgs/` and regenerates
`new_src/src/assets/icons/__init__.py` to expose the canonical condition
modules.
