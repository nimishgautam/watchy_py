"""Chunked BLE message protocol.

Provides a generic, bidirectional framing layer over two GATT
characteristics (TX: write-with-response, RX: notify).  The same frame
format is used in both directions so either side can send multi-chunk
messages.

Frame layout (every chunk, both directions):
    [msg_type: 1B][seq: 1B][total_chunks: 1B][chunk_idx: 1B][payload: N B]

Header is 4 bytes.  Payload size per chunk = negotiated ATT MTU - 3
(ATT overhead) - 4 (header) bytes.  At the default 23-byte MTU that
leaves 16 bytes; at a negotiated 512-byte MTU it leaves 505 bytes.
"""

import struct

# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------

MSG_SYNC_REQUEST  = const(0x01)  # watch → laptop, empty payload
MSG_SYNC_RESPONSE = const(0x02)  # laptop → watch, chunked JSON (server_data)
MSG_TIME_SYNC     = const(0x03)  # laptop → watch, 7 bytes: year,month,day,hour,min,sec (UTC)
MSG_EXTRA         = const(0x10)  # laptop → watch, extensible future use
MSG_ACK           = const(0xFE)  # either direction, confirms receipt
MSG_ERROR         = const(0xFF)  # either direction, 1-byte error code

# Error codes carried in MSG_ERROR payload byte
ERR_UNKNOWN       = const(0x00)
ERR_BAD_FRAME     = const(0x01)
ERR_TIMEOUT       = const(0x02)
ERR_NOT_READY     = const(0x03)
ERR_AUTH_FAILED   = const(0x04)

HEADER_SIZE = const(4)

# ---------------------------------------------------------------------------
# Framing helpers
# ---------------------------------------------------------------------------

def frame_header(msg_type: int, seq: int, total_chunks: int, chunk_idx: int) -> bytes:
    return struct.pack("BBBB", msg_type, seq, total_chunks, chunk_idx)


def parse_header(data) -> tuple:
    """Return (msg_type, seq, total_chunks, chunk_idx, payload)."""
    if len(data) < HEADER_SIZE:
        raise ValueError("frame too short")
    msg_type, seq, total, idx = struct.unpack("BBBB", data[:HEADER_SIZE])
    return (msg_type, seq, total, idx, data[HEADER_SIZE:])


def chunk_message(msg_type: int, payload: bytes, mtu: int, seq: int = 0) -> list:
    """Split *payload* into a list of ready-to-send frame bytes.

    Each frame fits within *mtu* bytes (the usable ATT payload size,
    i.e. negotiated MTU minus 3 bytes of ATT overhead).
    """
    chunk_capacity = mtu - HEADER_SIZE
    if chunk_capacity <= 0:
        raise ValueError("MTU too small for header")

    if not payload:
        return [frame_header(msg_type, seq, 1, 0)]

    total = (len(payload) + chunk_capacity - 1) // chunk_capacity
    if total > 255:
        raise ValueError("payload too large for 8-bit chunk count")

    frames = []
    for idx in range(total):
        start = idx * chunk_capacity
        end = min(start + chunk_capacity, len(payload))
        frames.append(frame_header(msg_type, seq, total, idx) + payload[start:end])
    return frames


def make_sync_request(seq: int = 0, payload: bytes = b"") -> bytes:
    """Build SYNC_REQUEST frame. Optional payload (e.g. AUTH_TOKEN bytes)."""
    return frame_header(MSG_SYNC_REQUEST, seq, 1, 0) + payload


def make_ack(seq: int = 0) -> bytes:
    """Build a single-frame ACK."""
    return frame_header(MSG_ACK, seq, 1, 0)


def make_error(code: int = ERR_UNKNOWN, seq: int = 0) -> bytes:
    """Build a single-frame ERROR with a 1-byte error code."""
    return frame_header(MSG_ERROR, seq, 1, 0) + bytes([code])


# ---------------------------------------------------------------------------
# Reassembly
# ---------------------------------------------------------------------------

class ChunkedReceiver:
    """Collects chunks for one sequence number and reassembles the payload.

    Usage::

        rx = ChunkedReceiver()
        for each notification:
            msg_type, seq, total, idx, payload = parse_header(data)
            done, full_payload = rx.feed(seq, total, idx, payload)
            if done:
                # full_payload is the complete reassembled bytes
                rx.reset()
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._seq = None
        self._total = 0
        self._chunks = {}
        self._received = 0

    def feed(self, seq: int, total: int, idx: int, payload: bytes) -> tuple:
        """Ingest one chunk.  Returns (complete: bool, assembled: bytes|None)."""
        if self._seq is None:
            self._seq = seq
            self._total = total
            self._chunks = {}
            self._received = 0

        if seq != self._seq or total != self._total:
            self.reset()
            self._seq = seq
            self._total = total
            self._chunks = {}
            self._received = 0

        if idx not in self._chunks:
            self._chunks[idx] = payload
            self._received += 1

        if self._received >= self._total:
            parts = []
            for i in range(self._total):
                parts.append(self._chunks.get(i, b""))
            return (True, b"".join(parts))

        return (False, None)
