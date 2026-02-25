"""On-device test for the ring clock renderer.

Run this directly on the ESP32 to see the clock face rendered at its final
position and size on the 200x200 e-ink display.  Change HOUR and MINUTE
below to test different arc state combinations.

No RTC, no WiFi, no deep sleep — just rendering.
"""

from lib.display import Display
from clock_ring import draw_clock
from constants import WHITE, BLACK

HOUR = 3
MINUTE = 7

display = Display()
display.framebuf.fill(WHITE)

# --- Guide lines for visual context only. ---
# These are NOT part of the final layout; they help judge sizing during
# this proof-of-concept and will be removed.
display.framebuf.hline(0, 17, 200, BLACK)   # top strip bottom edge
display.framebuf.hline(0, 99, 200, BLACK)   # clock zone bottom edge
display.framebuf.vline(100, 18, 81, BLACK)  # clock / weather vertical divider

draw_clock(display.framebuf, hour=HOUR, minute=MINUTE)
display.update()
