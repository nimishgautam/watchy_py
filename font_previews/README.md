Files created:
font_previews/__init__.py — package marker
font_previews/app.py — Flask app with /render, /specimen, and /fonts endpoints
font_previews/bridge.py — injects MicroPython shims and wires up imports from new_src/src/
font_previews/dynamic_font.py — renders glyphs on-the-fly from any TTF using the exact same FreeType flags as font_to_py.py
font_previews/shims/ — CPython-compatible stubs for framebuf, micropython, uctypes, machine, esp32
font_previews/templates/index.html — web UI with font role controls, mock data inputs, and multi-zoom preview
font_previews/fonts/ — empty directory where you can drop extra .ttf files
Modified:
pyproject.toml — added flask to dev dependencies
How to run:
poetry run python -m font_previews.app
Then open http://127.0.0.1:5001/. The UI auto-renders on every change — pick a font, change a size, and see the result immediately at 1x and 3x magnification, plus a character specimen strip at the bottom. The rendering uses the actual renderer.py and clock_ring.py code from new_src/src/ (imported directly, not copied), so it stays in sync with device changes.