"""Ring clock renderer — draws the segmented ring and centered hour number.

Blits pre-rendered arc bitmaps and renders the hour digit(s) in the center.
Designed for the upper-left zone (x=0-99, y=18-98) of the 200x200 display.
"""

import framebuf
from lib.writer import Writer
from constants import WHITE, BLACK, RING_CENTER_X, RING_CENTER_Y

# TODO: replace with a bold ~28-32px font once generated.
import assets.fonts.fira_sans_regular_28 as hour_font

import assets.arcs.q1_thin as q1_thin
import assets.arcs.q1_thick as q1_thick
import assets.arcs.q2_thin as q2_thin
import assets.arcs.q2_thick as q2_thick
import assets.arcs.q3_thin as q3_thin
import assets.arcs.q3_thick as q3_thick
import assets.arcs.q4_thin as q4_thin
import assets.arcs.q4_thick as q4_thick

DISPLAY_W = 200
DISPLAY_H = 200

_THIN = 1
_THICK = 2

_ARC_MODULES = (
    (q1_thin, q1_thick),
    (q2_thin, q2_thick),
    (q3_thin, q3_thick),
    (q4_thin, q4_thick),
)


def _quarter_states(minute: int) -> tuple:
    """Return (q1, q2, q3, q4) states for the given minute.

    Each state is 0 (empty), _THIN, or _THICK per the state table in
    display-layout.md.
    """
    q = minute // 15           # which quarter we're currently in (0-3)
    pos_in_q = minute % 15     # position within the current quarter

    states = [0, 0, 0, 0]
    for i in range(q):
        states[i] = _THICK
    if q < 4:
        states[q] = _THICK if pos_in_q >= 13 else _THIN
    return tuple(states)


def _blit_arc(fb, arc_mod):
    """Blit one arc bitmap onto the framebuffer using white as transparency."""
    arc_fb = framebuf.FrameBuffer(
        bytearray(arc_mod.DATA), arc_mod.WIDTH, arc_mod.HEIGHT,
        framebuf.MONO_HLSB,
    )
    fb.blit(arc_fb, arc_mod.OFFSET_X, arc_mod.OFFSET_Y, WHITE)


def _text_width(font, text: str) -> int:
    """Compute the pixel width of a string in the given font."""
    w = 0
    for ch in text:
        _, _, char_w = font.get_ch(ch)
        w += char_w
    return w


def draw_clock(fb, hour: int, minute: int):
    """Draw the ring clock into the upper-left zone.

    Args:
        fb: framebuf.FrameBuffer for the full 200x200 display.
        hour: 0-23.
        minute: 0-59.
    """
    states = _quarter_states(minute)

    for i, state in enumerate(states):
        if state == 0:
            continue
        thin_mod, thick_mod = _ARC_MODULES[i]
        _blit_arc(fb, thick_mod if state == _THICK else thin_mod)

    # 24-hour display, no leading zero.
    hour_str = str(hour)

    text_w = _text_width(hour_font, hour_str)
    text_h = hour_font.height()
    x = RING_CENTER_X - text_w // 2
    y = RING_CENTER_Y - text_h // 2

    wri = Writer(fb, hour_font, DISPLAY_W, DISPLAY_H, WHITE, BLACK, verbose=False)
    wri.set_textpos(fb, y, x)
    wri.printstring(hour_str)
