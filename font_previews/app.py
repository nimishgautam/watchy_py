"""Font Preview Tool — Flask app for interactive watch-face font evaluation.

Run with:  poetry run python -m font_previews.app
"""

import io
import sys
from pathlib import Path

# Must happen before any device code imports.
from font_previews.bridge import setup, REPO_ROOT, SRC_DIR
setup()

import framebuf  # noqa: E402  — this is our shim after setup()
from renderer import render_all  # noqa: E402
import renderer  # noqa: E402
import clock_ring  # noqa: E402

from flask import Flask, request, jsonify, send_file, render_template
from PIL import Image

from font_previews.dynamic_font import DynamicFont

app = Flask(__name__)

# Directories to scan for TTF files.
FONT_DIRS = [
    REPO_ROOT / "assets",
    REPO_ROOT / "font_previews" / "fonts",
]
# Also check system DejaVu (used for symbol glyphs).
_DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

DEFAULT_TTF = str(REPO_ROOT / "assets" / "FiraSans-Regular.ttf")

# Default mock data matching test_top_half.py / test_bottom_half.py.
DEFAULT_DATA = {
    "hour": 10,
    "minute": 25,
    "week_day": 3,
    "month": 2,
    "day": 24,
    "battery_v": 3.8,
    "weather_now": {"temp": 72, "condition": "sunny"},
    "weather_1h": {"temp": 65, "condition": "cloudy_thin"},
    "meetings": [
        {"start_hour": 10, "start_minute": 5, "duration_min": 30,
         "title": "Team standup", "type": "live"},
        {"start_hour": 10, "start_minute": 30, "duration_min": 15,
         "title": "Quick sync", "type": "recurring"},
        {"start_hour": 10, "start_minute": 45, "duration_min": 45,
         "title": "Client call", "type": "call"},
    ],
}

DEFAULT_FONTS = {
    "hour": {"ttf": DEFAULT_TTF, "size": 28},
    "temp": {"ttf": DEFAULT_TTF, "size": 20},
    "small": {"ttf": DEFAULT_TTF, "size": 14},
    "meeting_time": {"ttf": DEFAULT_TTF, "size": 16},
}


def _available_fonts() -> list[dict]:
    """Scan font directories and return [{name, path}, ...]."""
    found = {}
    for d in FONT_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.ttf")):
            found[f.name] = str(f)
        for f in sorted(d.glob("*.TTF")):
            found[f.name] = str(f)
    if _DEJAVU.exists():
        found[_DEJAVU.name] = str(_DEJAVU)
    return [{"name": k, "path": v} for k, v in sorted(found.items())]


def _make_dynamic_font(cfg: dict) -> DynamicFont:
    ttf = cfg.get("ttf", DEFAULT_TTF)
    size = int(cfg.get("size", 14))
    size = max(6, min(size, 80))
    return DynamicFont(ttf, size)


def _render_watchface(font_cfgs: dict, data: dict) -> Image.Image:
    """Render the watch face and return a PIL Image."""
    renderer.font_small = _make_dynamic_font(font_cfgs.get("small", DEFAULT_FONTS["small"]))
    renderer.font_mid = _make_dynamic_font(font_cfgs.get("meeting_time", DEFAULT_FONTS["meeting_time"]))
    renderer.font_medium = _make_dynamic_font(font_cfgs.get("temp", DEFAULT_FONTS["temp"]))
    clock_ring.hour_font = _make_dynamic_font(font_cfgs.get("hour", DEFAULT_FONTS["hour"]))

    buf = bytearray(200 * 200 // 8)
    fb = framebuf.FrameBuffer(buf, 200, 200, framebuf.MONO_HLSB)

    render_all(
        fb,
        hour=data.get("hour", 10),
        minute=data.get("minute", 25),
        week_day=data.get("week_day", 3),
        month=data.get("month", 2),
        day=data.get("day", 24),
        battery_voltage=data.get("battery_v", 3.8),
        server_data={
            "weather_now": data.get("weather_now", DEFAULT_DATA["weather_now"]),
            "weather_1h": data.get("weather_1h", DEFAULT_DATA["weather_1h"]),
            "meetings": data.get("meetings", DEFAULT_DATA["meetings"]),
        },
    )

    return fb.to_image()


def _render_specimen(ttf: str, size: int, text: str | None = None) -> Image.Image:
    """Render a character specimen grid and return a PIL Image."""
    font = DynamicFont(ttf, max(6, min(size, 80)))
    if text is None:
        text = "".join(chr(i) for i in range(32, 127))

    glyphs = []
    total_w = 0
    for ch in text:
        data, h, w = font.get_ch(ch)
        glyphs.append((ch, data, h, w))
        total_w += w

    if not glyphs:
        return Image.new("1", (1, 1), 1)

    fh = font.height()
    img = Image.new("1", (total_w, fh), 1)
    x = 0
    for ch, data, h, w in glyphs:
        bytes_per_row = (w + 7) // 8
        for row in range(h):
            for col in range(w):
                byte_idx = row * bytes_per_row + col // 8
                bit_mask = 0x80 >> (col % 8)
                if data[byte_idx] & bit_mask:
                    img.putpixel((x + col, row), 1)
                else:
                    img.putpixel((x + col, row), 0)
        x += w

    return img


def _image_to_png_bytes(img: Image.Image, scale: int = 1) -> bytes:
    if scale > 1:
        img = img.resize(
            (img.width * scale, img.height * scale),
            Image.NEAREST,
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/fonts")
def fonts():
    return jsonify(_available_fonts())


@app.route("/render", methods=["POST"])
def render():
    body = request.get_json(force=True)
    font_cfgs = body.get("fonts", DEFAULT_FONTS)
    data = body.get("data", DEFAULT_DATA)
    scale = int(body.get("scale", 1))
    scale = max(1, min(scale, 8))

    img = _render_watchface(font_cfgs, data)
    png = _image_to_png_bytes(img, scale)
    return send_file(io.BytesIO(png), mimetype="image/png")


@app.route("/specimen", methods=["POST"])
def specimen():
    body = request.get_json(force=True)
    ttf = body.get("ttf", DEFAULT_TTF)
    size = int(body.get("size", 14))
    text = body.get("text")
    scale = int(body.get("scale", 4))
    scale = max(1, min(scale, 12))

    img = _render_specimen(ttf, size, text)
    png = _image_to_png_bytes(img, scale)
    return send_file(io.BytesIO(png), mimetype="image/png")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
