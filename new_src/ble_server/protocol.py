"""CPython shim that re-exports the watch-side ble_protocol module.

MicroPython treats ``const()`` as a compile-time builtin.  We inject a
no-op ``const`` into ``builtins`` so the same source file works
unmodified on CPython, keeping a single source of truth for the framing
protocol.
"""

import builtins
import sys
from pathlib import Path

if not hasattr(builtins, "const"):
    builtins.const = lambda x: x  # type: ignore[attr-defined]

_WATCH_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _WATCH_SRC not in sys.path:
    sys.path.insert(0, _WATCH_SRC)

from ble_protocol import (  # noqa: E402  — path must be set first
    HEADER_SIZE,
    MSG_SYNC_REQUEST,
    MSG_SYNC_RESPONSE,
    MSG_TIME_SYNC,
    MSG_EXTRA,
    MSG_ACK,
    MSG_ERROR,
    ERR_UNKNOWN,
    ERR_BAD_FRAME,
    ERR_TIMEOUT,
    ERR_NOT_READY,
    ERR_AUTH_FAILED,
    frame_header,
    parse_header,
    chunk_message,
    make_sync_request,
    make_ack,
    make_error,
    ChunkedReceiver,
)

__all__ = [
    "HEADER_SIZE",
    "MSG_SYNC_REQUEST",
    "MSG_SYNC_RESPONSE",
    "MSG_TIME_SYNC",
    "MSG_EXTRA",
    "MSG_ACK",
    "MSG_ERROR",
    "ERR_UNKNOWN",
    "ERR_BAD_FRAME",
    "ERR_TIMEOUT",
    "ERR_NOT_READY",
    "ERR_AUTH_FAILED",
    "frame_header",
    "parse_header",
    "chunk_message",
    "make_sync_request",
    "make_ack",
    "make_error",
    "ChunkedReceiver",
]
