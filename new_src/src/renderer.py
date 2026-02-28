"""Display renderer — draws all zones onto the 200x200 framebuffer.

Call render_all() once per wake.  Each zone function writes only to its
designated area and does not touch neighbouring zones.

Zone map (pixel coords):
    y=0-16   Top strip  — date left, battery bar right
    y=17     Separator line
    y=18-98  Upper section — clock (x=0-99) | weather (x=100-199)
    y=99     Separator line
    y=100-199 Meetings — upcoming calendar entries
"""

import framebuf

from lib.writer import Writer
from clock_ring import draw_clock
from utils import month_to_short_string, week_day_to_short_string
from constants import (
    WHITE,
    BLACK,
    DISPLAY_W,
    DISPLAY_H,
    TOP_STRIP_H,
    CLOCK_ZONE_TOP,
    WEATHER_X,
    MEETINGS_Y,
    MEETINGS_ROW_H,
    MEETINGS_MAX_ROWS,
    GAP_BAR_H,
    GAP_BAR_THRESHOLD_MIN,
    MEETINGS_COL_TIME,
    MEETINGS_COL_TYPE,
    MEETINGS_COL_DUR,
    MEETINGS_COL_TITLE,
    BATT_MAX_V,
    BATT_MIN_V,
    BATT_BAR_W,
    BATT_BAR_H,
)

import assets.fonts.fira_sans_regular_14 as font_small   # date, labels, meeting titles
import assets.fonts.fira_sans_regular_16 as font_mid     # meeting start time
import assets.fonts.fira_sans_regular_20 as font_medium  # temperature
import assets.fonts.symbols_16 as font_glyphs            # meeting type + duration glyphs

import assets.icons as icons
import assets.icons.placeholder as _icon_placeholder

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Meeting type → single unicode glyph
# ---------------------------------------------------------------------------

_TYPE_GLYPHS = {
    "recurring": "\u25ce",   # ◎ bullseye — implies cycle/repeat
    "call":      "\u25c6",   # ◆ black diamond
    "live":      "\u25cf",   # ● solid circle — "live" dot
    "focus":     "\u25a0",   # ■ solid square — blocked time
    "personal":  "\u25c7",   # ◇ open diamond — lighter feel
    "general":   "\u25aa",   # ▪ small black square — minimal default
}
_TYPE_GLYPH_DEFAULT = "\u25aa"   # ▪ fallback for unknown types

# ---------------------------------------------------------------------------
# Duration → unicode glyph string (clockwise-fill series, up to 2 chars)
# ---------------------------------------------------------------------------

_DUR_FULL  = "\u25cf"   # ●
_DUR_QTR   = "\u25d4"   # ◔
_DUR_HALF  = "\u25d1"   # ◑
_DUR_3QTR  = "\u25d5"   # ◕

_DURATION_GLYPHS = [
    (15,  _DUR_QTR),
    (30,  _DUR_HALF),
    (45,  _DUR_3QTR),
    (60,  _DUR_FULL),
    (75,  _DUR_FULL + _DUR_QTR),
    (90,  _DUR_FULL + _DUR_HALF),
    (105, _DUR_FULL + _DUR_3QTR),
    (120, _DUR_FULL + _DUR_FULL),
]

_DURATION_OVER_2H = _DUR_FULL + _DUR_FULL + "+"


def _duration_glyph(duration_min: int) -> str:
    for threshold, glyph in _DURATION_GLYPHS:
        if duration_min <= threshold:
            return glyph
    return _DURATION_OVER_2H


_WEATHER_ROW_HEIGHT = 44   # px per weather row (28 px icon + text)
_WEATHER_ICON_X = 104      # icon left edge (4 px from WEATHER_X)
_WEATHER_TEMP_X = 136      # temp text left edge (4 px gap after 28 px icon)
_WEATHER_LABEL_X = 170     # short label ("now"/"+1h") right of temperature

# Battery icon geometry (body + positive-terminal bump)
# Total width == BATT_BAR_W so bar_x positioning is unchanged.
_BATT_BODY_W = BATT_BAR_W - 2   # 28 px — main body
_BATT_BUMP_W = 2                 # 2 px wide positive terminal
_BATT_BUMP_H = 2                 # 2 px tall, centered in body height


def render_all(
    fb,
    hour: int,
    minute: int,
    week_day: int,
    month: int,
    day: int,
    battery_voltage: float,
    server_data: dict,
    stale_since_hour: int = None,
    has_valid_weather: bool = True,
    data_is_fresh: bool = True,
):
    """Render the complete watch face into fb.

    Args:
        fb: 200x200 MONO_HLSB framebuffer.
        hour: 0-23.
        minute: 0-59.
        week_day: 1-7 (Mon-Sun).
        month: 1-12.
        day: 1-31.
        battery_voltage: volts (e.g. 3.8).
        server_data: dict matching the server schema (see design-overview.md).
        stale_since_hour: None when data is fresh.  When stale, the hour
            at which the data was last fetched — used to show an "X"
            indicator and hour-based weather labels.
        has_valid_weather: True if we have synced at least once (weather zone
            drawn). False leaves weather zone blank.
        data_is_fresh: True if data is from a recent sync. Used to decide
            whether to show "No meetings" when the meetings list is empty.
    """
    fb.fill(WHITE)
    _render_top_strip(fb, week_day, month, day, battery_voltage, stale_since_hour)
    draw_clock(fb, hour, minute)
    _render_weather(fb, server_data, stale_since_hour, has_valid_weather)
    _render_meetings(fb, server_data, hour, minute, data_is_fresh)


# ---------------------------------------------------------------------------
# Zone renderers
# ---------------------------------------------------------------------------

def _render_top_strip(fb, week_day: int, month: int, day: int,
                      battery_voltage: float, stale_since_hour: int = None):
    """Top strip: date left, stale indicator + battery bar right."""
    # --- Date text — vertically centered in the strip ---
    date_str = (
        week_day_to_short_string(week_day)
        + " "
        + str(day)
        + " "
        + month_to_short_string(month)
    )
    text_y = (TOP_STRIP_H - font_small.height()) // 2
    _write_text(fb, font_small, date_str, x=4, y=text_y)

    # --- Battery icon — right-aligned, vertically centered ---
    # Layout: [  body (28 px)  ][bump (2 px)]  total = BATT_BAR_W = 30 px
    pct = min(1.0, max(0.0, (battery_voltage - BATT_MIN_V) / (BATT_MAX_V - BATT_MIN_V)))
    bar_x = DISPLAY_W - BATT_BAR_W - 4
    bar_y = (TOP_STRIP_H - BATT_BAR_H) // 2

    # Body outline
    fb.rect(bar_x, bar_y, _BATT_BODY_W, BATT_BAR_H, BLACK)

    # Positive terminal bump — solid black, right of body, vertically centered
    bump_x = bar_x + _BATT_BODY_W
    bump_y = bar_y + (BATT_BAR_H - _BATT_BUMP_H) // 2
    fb.fill_rect(bump_x, bump_y, _BATT_BUMP_W, _BATT_BUMP_H, BLACK)

    # Fill level — grows left-to-right inside the body
    fill_w = int(pct * (_BATT_BODY_W - 2))
    if fill_w > 0:
        fb.fill_rect(bar_x + 1, bar_y + 1, fill_w, BATT_BAR_H - 2, BLACK)

    # --- Stale-data indicator — "X" just left of battery ---
    if stale_since_hour is not None:
        _write_text(fb, font_small, "X", x=bar_x - 14, y=text_y)


def _render_separators(fb):
    """Draw the three structural 1 px separator lines."""
    fb.hline(0, TOP_STRIP_H, DISPLAY_W, BLACK)           # below top strip
    fb.vline(WEATHER_X, CLOCK_ZONE_TOP, 81, BLACK)       # clock | weather divider
    fb.hline(0, MEETINGS_Y - 1, DISPLAY_W, BLACK)        # above meetings


def _render_weather(fb, server_data: dict, stale_since_hour: int = None,
                    has_valid_weather: bool = True):
    """Weather zone: two rows (now / +1h).  Zone: x=100-199, y=18-98."""
    if not has_valid_weather:
        return

    weather_now = server_data.get("weather_now", {})
    weather_1h = server_data.get("weather_1h", {})

    if stale_since_hour is not None:
        label_now = "{}h".format(stale_since_hour)
        label_1h  = "{}h".format((stale_since_hour + 1) % 24)
    else:
        label_now = "now"
        label_1h  = "+1h"

    _render_weather_row(fb, weather_now, label=label_now, row_top=34)
    _render_weather_row(fb, weather_1h,  label=label_1h,  row_top=80)


def _render_weather_row(fb, weather: dict, label: str, row_top: int):
    """Render one weather row: [icon] [temp°] [label].

    Args:
        weather: dict with keys "temp" (int) and "condition" (str).
        label: short label drawn to the right of the temperature ("now"/"+1h").
        row_top: y coordinate for the top of the icon and temperature text.
    """
    temp = weather.get("temp")
    condition = weather.get("condition", "")

    # Icon (28x28 bitmap, top-left at (WEATHER_ICON_X, row_top))
    icon_mod = _condition_to_icon(condition)
    _blit_icon(fb, icon_mod, x=_WEATHER_ICON_X, y=row_top)

    # Temperature ("72°")
    if temp is not None:
        temp_str = str(temp) + "\xb0"   # U+00B0 degree symbol
        _write_text(fb, font_medium, temp_str, x=_WEATHER_TEMP_X, y=row_top)

    # Condition label ("now" / "+1h") — vertically centered within the 20 px row height
    label_y = row_top + (font_medium.height() - font_small.height()) // 2
    _write_text(fb, font_small, label, x=_WEATHER_LABEL_X, y=label_y)


def _render_meetings(fb, server_data: dict, hour: int, minute: int,
                    data_is_fresh: bool = True):
    """Meetings zone: upcoming calendar entries.  Zone: x=0-199, y=128-199.

    Each row shows: [duration glyph(s)] [time] [type glyph] [title]

    Time and glyphs use font_mid (16px); titles use font_small (14px).

    Rows for in-progress meetings or meetings starting within 15 minutes are
    rendered inverted (white text on black background).  Meetings that have
    already ended are excluded.  Up to MEETINGS_MAX_ROWS entries are shown,
    sorted by start time.

    Gap bar: when the next event starts >= GAP_BAR_THRESHOLD_MIN minutes from
    now, a 7px checkerboard strip is drawn at the top of the zone and the event
    rows shift down to accommodate it.  The gap is computed from device-side
    data only — no separate flag from the server is needed.
    """
    now_total = hour * 60 + minute
    meetings = server_data.get("meetings", [])

    # Filter out meetings that have already ended, then sort by start time.
    visible = []
    for m in meetings:
        start_total = m["start_hour"] * 60 + m["start_minute"]
        end_total = start_total + m["duration_min"]
        if end_total > now_total:
            visible.append((start_total, m))
    visible.sort(key=lambda x: x[0])
    visible = [m for _, m in visible[:MEETINGS_MAX_ROWS]]

    zone_h = DISPLAY_H - MEETINGS_Y   # 72 px

    if not visible:
        if data_is_fresh:
            _write_text(
                fb, font_small, "No meetings",
                x=(DISPLAY_W - 11 * 8) // 2,   # rough center; tunable after hardware eval
                y=MEETINGS_Y + (zone_h - font_small.height()) // 2,
            )
        return

    # Gap bar — checkerboard strip when next event is far enough away.
    first_start = visible[0]["start_hour"] * 60 + visible[0]["start_minute"]
    show_gap_bar = (first_start - now_total) >= GAP_BAR_THRESHOLD_MIN

    if show_gap_bar:
        bar_y = MEETINGS_Y + 1
        for row in range(GAP_BAR_H):
            for col in range(DISPLAY_W):
                if (row + col) % 2 == 0:
                    fb.pixel(col, bar_y + row, BLACK)
        first_row_y = MEETINGS_Y + 1 + GAP_BAR_H + 1   # 137
    else:
        first_row_y = MEETINGS_Y + 4                     # 132

    for i, m in enumerate(visible):
        row_y = first_row_y + i * MEETINGS_ROW_H
        start_total = m["start_hour"] * 60 + m["start_minute"]
        minutes_until = start_total - now_total

        in_progress = minutes_until <= 0 and minutes_until > -m["duration_min"]
        highlight = in_progress or (0 <= minutes_until <= 15)

        if highlight:
            fb.fill_rect(0, row_y, DISPLAY_W, MEETINGS_ROW_H, BLACK)
            fg = WHITE
        else:
            fg = BLACK

        # Duration glyph(s) — leftmost column
        dur_str = _duration_glyph(m["duration_min"])
        _write_text(fb, font_glyphs, dur_str, x=MEETINGS_COL_DUR, y=row_y, color=fg)

        # Time column: 24-hour, no leading zero in hour, e.g. "9:05" or "13:30"
        time_str = str(m["start_hour"]) + ":" + "{:02d}".format(m["start_minute"])
        _write_text(fb, font_mid, time_str, x=MEETINGS_COL_TIME, y=row_y, color=fg)

        # Type glyph — rendered with symbols_16 (Fira Sans lacks Geometric Shapes)
        type_glyph = _TYPE_GLYPHS.get(m.get("type", ""), _TYPE_GLYPH_DEFAULT)
        _write_text(fb, font_glyphs, type_glyph, x=MEETINGS_COL_TYPE, y=row_y, color=fg)

        # Title — no truncation; clip naturally at display edge
        _write_text(fb, font_small, m["title"], x=MEETINGS_COL_TITLE, y=row_y, color=fg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _condition_to_icon(condition: str):
    """Map a condition string to its icon module.  Falls back to placeholder."""
    icon = getattr(icons, condition, None)
    if icon is None:
        return _icon_placeholder
    return icon


def _blit_icon(fb, icon_mod, x: int, y: int):
    """Blit an icon bitmap onto fb using white as the transparency key."""
    icon_fb = framebuf.FrameBuffer(
        bytearray(icon_mod.DATA),
        icon_mod.WIDTH,
        icon_mod.HEIGHT,
        framebuf.MONO_HLSB,
    )
    fb.blit(icon_fb, x + icon_mod.OFFSET_X, y + icon_mod.OFFSET_Y, WHITE)


def _write_text(fb, font, text: str, x: int, y: int, color: int = BLACK):
    """Render text at pixel position (x, y) using the given font.

    Args:
        color: BLACK (default) = normal black-on-white rendering.
               WHITE = inverted white-on-black (row background must already
               be filled BLACK before calling).

    The Writer.printstring `invert` flag controls this: invert=True flips
    every bit in the glyph bitmap before blitting, producing black ink pixels
    on white background (normal).  invert=False blits the raw bitmap, which
    has lit (WHITE) pixels for the character shape and dark (BLACK) for the
    cell background — giving white text on a black row.  The bg/fg_color
    fields on Writer are unused in the monochrome blit path.
    """
    wri = Writer(fb, font, DISPLAY_W, DISPLAY_H, verbose=False)
    wri.set_textpos(fb, y, x)
    wri.printstring(text, invert=(color == BLACK))
