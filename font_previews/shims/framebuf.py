"""CPython shim for micropython framebuf module.

Provides a FrameBuffer implementation for MONO_HLSB format that is
byte-compatible with MicroPython's built-in framebuf. Used by the font
preview tool to run the device rendering code on the host.
"""

from PIL import Image

MONO_VLSB = 0
MONO_HLSB = 3
MONO_HMSB = 4


class FrameBuffer:
    """MONO_HLSB framebuffer: each byte holds 8 horizontal pixels, bit 7 = leftmost."""

    def __init__(self, buf, width, height, fmt):
        if fmt not in (MONO_HLSB, MONO_HMSB):
            raise ValueError(f"Only MONO_HLSB and MONO_HMSB are supported, got {fmt}")
        self._buf = buf
        self._width = width
        self._height = height
        self._fmt = fmt
        self._stride = (width + 7) // 8  # bytes per row

    # -- pixel access --------------------------------------------------------

    def pixel(self, x, y, color=None):
        if x < 0 or x >= self._width or y < 0 or y >= self._height:
            return 0 if color is None else None
        byte_idx = y * self._stride + x // 8
        if self._fmt == MONO_HLSB:
            bit_mask = 0x80 >> (x % 8)
        else:
            bit_mask = 1 << (x % 8)

        if color is None:
            return 1 if (self._buf[byte_idx] & bit_mask) else 0

        if color:
            self._buf[byte_idx] |= bit_mask
        else:
            self._buf[byte_idx] &= ~bit_mask & 0xFF

    # -- fill ----------------------------------------------------------------

    def fill(self, color):
        val = 0xFF if color else 0x00
        for i in range(len(self._buf)):
            self._buf[i] = val

    # -- rectangles ----------------------------------------------------------

    def fill_rect(self, x, y, w, h, color):
        for row in range(max(0, y), min(self._height, y + h)):
            for col in range(max(0, x), min(self._width, x + w)):
                self.pixel(col, row, color)

    def rect(self, x, y, w, h, color):
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

    # -- lines ---------------------------------------------------------------

    def hline(self, x, y, w, color):
        if y < 0 or y >= self._height:
            return
        for col in range(max(0, x), min(self._width, x + w)):
            self.pixel(col, y, color)

    def vline(self, x, y, h, color):
        if x < 0 or x >= self._width:
            return
        for row in range(max(0, y), min(self._height, y + h)):
            self.pixel(x, row, color)

    # -- blit ----------------------------------------------------------------

    def blit(self, source, x, y, key=-1):
        """Copy pixels from source FrameBuffer. If key is given, skip pixels
        of that color (transparency)."""
        for sy in range(source._height):
            dy = y + sy
            if dy < 0 or dy >= self._height:
                continue
            for sx in range(source._width):
                dx = x + sx
                if dx < 0 or dx >= self._width:
                    continue
                px = source.pixel(sx, sy)
                if key != -1 and px == key:
                    continue
                self.pixel(dx, dy, px)

    # -- scroll --------------------------------------------------------------

    def scroll(self, xstep, ystep):
        if ystep > 0:
            for row in range(self._height - 1, ystep - 1, -1):
                for col in range(self._width):
                    self.pixel(col, row, self.pixel(col, row - ystep))
        elif ystep < 0:
            for row in range(-ystep, self._height):
                for col in range(self._width):
                    self.pixel(col, row + ystep, self.pixel(col, row))

    # -- conversion helpers (not in MicroPython) -----------------------------

    def to_image(self) -> Image.Image:
        """Convert the framebuffer contents to a PIL Image.

        In the watch's 1-bit scheme, 0 = BLACK and 1 = WHITE.
        """
        img = Image.new("1", (self._width, self._height))
        for y in range(self._height):
            for x in range(self._width):
                img.putpixel((x, y), self.pixel(x, y))
        return img
