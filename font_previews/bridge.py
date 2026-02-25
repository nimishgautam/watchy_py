"""Bridge between CPython and the MicroPython device code.

Injects shim modules for MicroPython-only imports, adds new_src/src/ to
sys.path, and registers synthetic packages for directories that lack
__init__.py (MicroPython doesn't need them, CPython does).

Call setup() once at process startup, before importing any device code.
"""

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "new_src" / "src"
SHIMS_DIR = Path(__file__).resolve().parent / "shims"

_setup_done = False


def setup():
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    _inject_shims()
    _add_src_to_path()
    _register_packages()


def _inject_shims():
    """Put CPython-compatible shim modules into sys.modules so that
    `import framebuf`, `from micropython import const`, etc. resolve
    to our shims instead of failing with ModuleNotFoundError."""
    from font_previews.shims import framebuf as _framebuf
    from font_previews.shims import micropython as _micropython
    from font_previews.shims import uctypes as _uctypes
    from font_previews.shims import machine as _machine
    from font_previews.shims import esp32 as _esp32

    sys.modules["framebuf"] = _framebuf
    sys.modules["micropython"] = _micropython
    sys.modules["uctypes"] = _uctypes
    sys.modules["machine"] = _machine
    sys.modules["esp32"] = _esp32


def _add_src_to_path():
    """Prepend new_src/src so it wins over the old src/ directory (which is
    also on sys.path via the installed package).

    The device tree contains a secrets.py (WiFi creds) that would shadow
    the stdlib secrets module, breaking Flask/werkzeug.  We pre-import the
    real one so it's already cached in sys.modules before the path change.
    """
    import secrets  # noqa: F401  — force stdlib secrets into sys.modules cache
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)


def _register_packages():
    """Create synthetic package entries for directories that exist in
    new_src/src/ but don't have __init__.py. CPython needs these to
    resolve dotted imports like `assets.arcs.q1_thin`."""
    packages = ["assets", "assets.arcs", "assets.fonts", "lib"]
    for pkg in packages:
        if pkg in sys.modules:
            continue
        pkg_dir = SRC_DIR / pkg.replace(".", "/")
        if not pkg_dir.is_dir():
            continue
        mod = types.ModuleType(pkg)
        mod.__path__ = [str(pkg_dir)]
        mod.__package__ = pkg
        sys.modules[pkg] = mod
