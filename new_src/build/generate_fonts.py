#!/usr/bin/env python3
"""Generate bitmap fonts for the watch.

Run this on the host machine. Requires: freetype-py (pip install freetype-py)

Reads from:  <repo>/assets/FiraSans-Regular.ttf  (text fonts)
             DejaVu Sans from the system          (glyph/symbol font)
Writes to:   <repo>/new_src/src/assets/fonts/

Skips fonts that already exist on disk. Pass --force to regenerate everything.
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TTF_REGULAR = REPO_ROOT / "assets" / "FiraSans-Regular.ttf"
TTF_ZEN_DOTS = REPO_ROOT / "font_previews" / "fonts" / "ZenDots-Regular.ttf"
FONT_TO_PY = REPO_ROOT / "scripts" / "font_to_py.py"
OUTPUT_DIR = REPO_ROOT / "new_src" / "src" / "assets" / "fonts"

# DejaVu Sans has broad Geometric Shapes coverage (Fira Sans does not).
# Used only for the glyph/symbol font; system path is fine for a build-time tool.
TTF_DEJAVU_SANS = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

# Printable ASCII (32-126) plus the degree symbol (U+00B0) for temperature.
# NOTE: Fira Sans Regular does NOT contain the Geometric Shapes block
# (U+25A0-U+25FF), so those glyphs are in a separate font (symbols_14).
_FIRA_CHAR_SET = (
    "".join(chr(i) for i in range(32, 127))
    + "\u00b0"   # ° degree symbol
)

# Minimal character set for the symbols/glyphs font (DejaVu Sans).
# Includes space, the duration overflow marker (+), and the nine geometric
# shape glyphs used for meeting type and duration indicators.
_SYMBOL_CHAR_SET = (
    " +"
    + "\u25ce"   # ◎ focus type
    + "\u266e"   # ♮ general type
    + "\u2605"   # ★ call type
    + "\u2665"   # ♥ personal type
    + "\u25b7"   # ▷ recurring type
    + "\u25c7"   # ◇ live type
    + "\u25cf"   # ● duration full-circle
    + "\u25d1"   # ◑ duration half-circle (30 min)
    + "\u25d4"   # ◔ duration quarter-circle (15 min)
    + "\u25d5"   # ◕ duration three-quarter-circle (45 min)
)

# Clock-face digits only — keeps the large font file small.
_CLOCK_CHAR_SET = " 0123456789"

# (output_stem, size_px, ttf_path, extra_flags)
# Add new entries here as needed.
FONTS = [
    ("fira_sans_regular_14", 14, TTF_REGULAR,     ["-c", _FIRA_CHAR_SET]),
    ("fira_sans_regular_20", 20, TTF_REGULAR,     ["-c", _FIRA_CHAR_SET]),
    ("zen_dots_39",          39, TTF_ZEN_DOTS,    ["-c", _CLOCK_CHAR_SET]),
    ("symbols_14",           14, TTF_DEJAVU_SANS, ["-c", _SYMBOL_CHAR_SET]),
    ("symbols_16",           16, TTF_DEJAVU_SANS, ["-c", _SYMBOL_CHAR_SET]),
]


def generate_font(stem: str, size: int, ttf: Path, extra_flags: list, force: bool) -> bool:
    out_path = OUTPUT_DIR / f"{stem}.py"
    if out_path.exists() and not force:
        print(f"  skip  {out_path.name}  (already exists; use --force to regenerate)")
        return False

    # font_to_py.py validates that the output filename stem is a valid Python
    # identifier, and it won't accept a path with directory separators as the
    # output argument.  Run from OUTPUT_DIR so we can pass just the filename.
    filename = f"{stem}.py"
    cmd = [sys.executable, str(FONT_TO_PY), "-x"] + extra_flags + [str(ttf), str(size), filename]
    print(f"  gen   {filename}  ({size} px from {ttf.name}) ...")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=OUTPUT_DIR)
    if result.returncode != 0:
        print(f"  ERROR generating {filename}:")
        print(result.stderr or result.stdout)
        return False
    print(f"  done  {filename}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate fonts even if the output file already exists.",
    )
    args = parser.parse_args()

    if not TTF_REGULAR.exists():
        print(f"ERROR: TTF not found at {TTF_REGULAR}")
        sys.exit(1)
    if not TTF_DEJAVU_SANS.exists():
        print(f"ERROR: DejaVu Sans not found at {TTF_DEJAVU_SANS}")
        print("       Install it with: sudo apt install fonts-dejavu-core")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {OUTPUT_DIR}")

    generated = 0
    for stem, size, ttf, extra_flags in FONTS:
        if generate_font(stem, size, ttf, extra_flags, args.force):
            generated += 1

    print(f"\nDone. {generated} font(s) generated.")


if __name__ == "__main__":
    main()
