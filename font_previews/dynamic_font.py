"""Dynamic font that renders glyphs on-the-fly from a TTF using freetype-py.

Exposes the same API as the generated font modules produced by font_to_py.py,
so it can be plugged directly into the Writer class without changes.

Uses the exact same FreeType flags (FT_LOAD_RENDER | FT_LOAD_TARGET_MONO) and
the same multi-pass height calibration algorithm as font_to_py.py, so the
output is pixel-identical to what you'd get by running the full font generation
pipeline.
"""

import freetype


class DynamicFont:
    """Drop-in replacement for generated font modules.

    Usage:
        font = DynamicFont("/path/to/font.ttf", 14)
        font.height()      # 14
        font.get_ch("A")   # (bytes, height, width)
    """

    def __init__(self, ttf_path: str, target_height: int, charset: str | None = None):
        self._face = freetype.Face(ttf_path)
        self._target_height = target_height
        if charset is None:
            charset = "".join(chr(i) for i in range(32, 127)) + "\u00b0"
        self._charset = charset
        self._cache: dict[str, tuple[bytes, int, int]] = {}

        self._actual_height = 0
        self._max_ascent = 0
        self._max_descent = 0
        self._max_width = 0
        self._calibrate(target_height)

    def _calibrate(self, required_height: int):
        """Multi-pass algorithm matching font_to_py.py get_dimensions()."""
        error = 0
        height = required_height
        for _ in range(10):
            height += error
            self._face.set_pixel_sizes(0, height)
            max_descent = 0
            max_width = 0
            max_ascent = 0
            for ch in self._charset:
                if self._face.get_char_index(ch) == 0:
                    continue
                self._face.load_char(ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO)
                slot = self._face.glyph
                bmp = slot.bitmap
                top = slot.bitmap_top
                glyph_h = bmp.rows
                glyph_w = bmp.width
                ascent = max(0, max(top, glyph_h) - max(0, glyph_h - top))
                descent = max(0, glyph_h - top)
                advance = slot.advance.x / 64
                left = slot.bitmap_left
                if left >= 0:
                    cw = int(max(advance, glyph_w + left))
                else:
                    cw = int(max(advance - left, glyph_w))
                max_ascent = max(max_ascent, ascent)
                max_descent = max(max_descent, descent)
                max_width = max(max_width, cw)

            new_error = required_height - (max_ascent + max_descent)
            if new_error == 0 or abs(new_error) - abs(error) == 0:
                break
            error = new_error

        self._actual_height = int(max_ascent + max_descent)
        self._max_ascent = int(max_ascent)
        self._max_descent = int(max_descent)
        self._max_width = int(max_width)

    def _render_glyph(self, ch: str) -> tuple[bytes, int, int]:
        """Render a single character and return (packed_bytes, height, width)."""
        if self._face.get_char_index(ch) == 0:
            ch = "?"
            if self._face.get_char_index(ch) == 0:
                return self._blank_glyph(1)

        self._face.load_char(ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO)
        slot = self._face.glyph
        bmp = slot.bitmap
        glyph_h = bmp.rows
        glyph_w = bmp.width
        top = slot.bitmap_top
        advance = slot.advance.x / 64
        glyph_left = slot.bitmap_left

        ascent = max(0, max(top, glyph_h) - max(0, glyph_h - top))
        descent = max(0, glyph_h - top)

        if glyph_left >= 0:
            char_width = int(max(advance, glyph_w + glyph_left))
            left = glyph_left
        else:
            char_width = int(max(advance - glyph_left, glyph_w))
            left = 0

        if char_width == 0:
            return self._blank_glyph(max(1, int(advance)))

        h = self._actual_height
        row_offset = h - int(ascent) - self._max_descent

        unpacked = bytearray(bmp.rows * bmp.width)
        for row in range(bmp.rows):
            for byte_index in range(bmp.pitch):
                byte_value = bmp.buffer[row * bmp.pitch + byte_index]
                num_bits_done = byte_index * 8
                rowstart = row * bmp.width + byte_index * 8
                for bit_index in range(min(8, bmp.width - num_bits_done)):
                    bit = byte_value & (1 << (7 - bit_index))
                    unpacked[rowstart + bit_index] = 1 if bit else 0

        # Place into full-height output bitmap and pack HLSB
        bytes_per_row = (char_width + 7) // 8
        packed = bytearray(bytes_per_row * h)
        for gy in range(glyph_h):
            dy = row_offset + gy
            if dy < 0 or dy >= h:
                continue
            for gx in range(glyph_w):
                dx = left + gx
                if dx < 0 or dx >= char_width:
                    continue
                if unpacked[gy * glyph_w + gx]:
                    byte_idx = dy * bytes_per_row + dx // 8
                    packed[byte_idx] |= 0x80 >> (dx % 8)

        return bytes(packed), h, char_width

    def _blank_glyph(self, width: int) -> tuple[bytes, int, int]:
        h = self._actual_height
        bytes_per_row = (width + 7) // 8
        return bytes(bytes_per_row * h), h, width

    # -- Public API matching generated font modules --------------------------

    def height(self) -> int:
        return self._actual_height

    def baseline(self) -> int:
        return self._actual_height - self._max_descent

    def max_width(self) -> int:
        return self._max_width

    def hmap(self) -> bool:
        return True

    def reverse(self) -> bool:
        return False

    def monospaced(self) -> bool:
        return False

    def min_ch(self) -> int:
        return min(ord(c) for c in self._charset)

    def max_ch(self) -> int:
        return max(ord(c) for c in self._charset)

    def get_ch(self, ch: str):
        if ch not in self._cache:
            self._cache[ch] = self._render_glyph(ch)
        return self._cache[ch]
