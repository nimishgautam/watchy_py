# BLE Protocol Specification

This document defines the contract between the Watchy watch (BLE Central)
and the laptop service (BLE Peripheral / GATT Server).  The watch-side
implementation lives in `ble_client.py` and `ble_protocol.py`.  The laptop
service must implement the peripheral side described here.

## GATT Service

The laptop advertises a single custom service.

| Item | UUID |
|---|---|
| Service | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| TX Characteristic | `a1b2c3d4-e5f6-7890-abcd-ef1234567891` |
| RX Characteristic | `a1b2c3d4-e5f6-7890-abcd-ef1234567892` |

**TX** — the watch writes requests here. Properties: **write** (with
response).

**RX** — the laptop sends responses here via notifications. Properties:
**notify**. The watch subscribes to notifications by writing `0x0001` to
the RX characteristic's Client Characteristic Configuration Descriptor
(CCCD, UUID `0x2902`).

## Security

The link must be **encrypted** (LE Secure Connections pairing with
bonding).  The watch initiates pairing via `gap_pair()` during a
dedicated pairing-mode flow triggered by a long press of the BACK button.
The bond is persisted on both sides so subsequent connections are
encrypted automatically.

## Message Frame Format

All messages in both directions use the same 4-byte header:

```
Offset  Size  Field
0       1     msg_type       Message type (see table below)
1       1     seq            Sequence number (groups chunks of one message)
2       1     total_chunks   Total chunks in this message (1 for single-frame)
3       1     chunk_idx      Zero-based index of this chunk
4+      N     payload        Remaining bytes (may be empty)
```

The maximum frame size is the negotiated ATT MTU minus 3 bytes of ATT
overhead.  At the default 23-byte MTU, payload capacity is 16 bytes per
chunk.  The watch requests MTU 517 at connection time; the laptop should
accept the largest MTU it can.

## Message Types

| Code | Name | Direction | Payload |
|---|---|---|---|
| `0x01` | SYNC_REQUEST | watch → laptop | Empty (no payload) |
| `0x02` | SYNC_RESPONSE | laptop → watch | Chunked UTF-8 JSON (see schema below) |
| `0x03` | TIME_SYNC | laptop → watch | 4 bytes: uint32 LE — current UTC epoch |
| `0x10` | EXTRA | laptop → watch | Extensible, format TBD |
| `0xFE` | ACK | either direction | Empty (no payload) |
| `0xFF` | ERROR | either direction | 1 byte: error code |

### Error Codes

| Code | Meaning |
|---|---|
| `0x00` | Unknown / generic error |
| `0x01` | Bad frame (malformed header) |
| `0x02` | Timeout |
| `0x03` | Not ready (data unavailable) |

## Sync Flow

```
Watch                                      Laptop
  |                                          |
  |--- BLE connect (bonded) --------------->|
  |--- Subscribe to RX notifications ------>|
  |--- Write SYNC_REQUEST to TX ----------->|
  |                                          |
  |<--- Notify TIME_SYNC on RX -------------|
  |<--- Notify SYNC_RESPONSE chunk 0/N ----|
  |<--- Notify SYNC_RESPONSE chunk 1/N ----|
  |<--- ...                                 |
  |<--- Notify SYNC_RESPONSE chunk N-1/N --|
  |<--- Notify EXTRA (optional) ------------|
  |                                          |
  |--- Write ACK to TX ------------------->|
  |--- Disconnect ------------------------->|
```

1. The watch connects (using the bonded peer address for fast reconnect).
2. The watch subscribes to RX notifications (writes CCCD).
3. The watch writes a single-frame `SYNC_REQUEST` to the TX
   characteristic.
4. The laptop responds with:
   - **TIME_SYNC** — a single-frame notification containing the current
     UTC epoch as a 4-byte little-endian uint32.
   - **SYNC_RESPONSE** — one or more notification frames containing the
     `server_data` JSON payload, chunked per the frame format.  All
     chunks share the same `seq` number.
   - Optionally, one or more **EXTRA** messages for future extensibility.
5. The watch reassembles the SYNC_RESPONSE chunks, parses the JSON, and
   writes an **ACK** to TX.
6. The watch disconnects.

**Timeouts:** The watch waits up to 10 seconds for a complete
SYNC_RESPONSE after sending the request.  If the response is not
complete by then, the sync is marked as failed and the watch renders from
stale cached data.

## `server_data` JSON Schema

The SYNC_RESPONSE payload is a UTF-8 JSON object:

```json
{
    "utc_offset": -5,
    "weather_now": {
        "temp": 72,
        "condition": "sunny"
    },
    "weather_1h": {
        "temp": 65,
        "condition": "rain"
    },
    "meetings": [
        {
            "start_hour": 10,
            "start_minute": 30,
            "duration_min": 30,
            "title": "Standup",
            "type": "meeting"
        }
    ]
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `utc_offset` | int | Hours offset from UTC for the user's timezone (e.g. -5 for EST). Used to convert the TIME_SYNC epoch to local time. |
| `weather_now.temp` | int | Current temperature (Fahrenheit). |
| `weather_now.condition` | string | One of the canonical condition names (see `weather_types.md`). |
| `weather_1h.temp` | int | Temperature forecast for +1 hour. |
| `weather_1h.condition` | string | Condition forecast for +1 hour. |
| `meetings` | array | Up to 10 upcoming meetings, sorted by start time. |
| `meetings[].start_hour` | int | 0-23, local time. |
| `meetings[].start_minute` | int | 0-59. |
| `meetings[].duration_min` | int | Duration in minutes. |
| `meetings[].title` | string | Short title (truncate to ~20 chars server-side for display). |
| `meetings[].type` | string | One of: `recurring`, `call`, `live`, `focus`, `personal`, `general`. |

### Canonical Weather Conditions

See `weather_types.md` for the full list.  Unknown conditions fall back
to a placeholder icon on the watch.

## Chunking Details

For a payload of `L` bytes and a usable ATT payload of `M` bytes
(negotiated MTU minus 3), the chunk capacity per frame is `M - 4` bytes
(4-byte header).

```
total_chunks = ceil(L / (M - 4))
```

Each chunk carries:
- `msg_type` = `0x02` (SYNC_RESPONSE)
- `seq` = same value for all chunks of one message (typically 0)
- `total_chunks` = total number of chunks
- `chunk_idx` = 0, 1, 2, ... (total_chunks - 1)
- `payload` = the corresponding slice of the JSON bytes

The watch reassembles by concatenating payloads in `chunk_idx` order.

## Laptop Service Requirements

The laptop service must:

1. **Advertise** the service UUID continuously so the watch can discover
   it.
2. **Accept bonding** and persist the bond so reconnections are
   encrypted.
3. **Handle SYNC_REQUEST** by:
   a. Gathering current weather, upcoming meetings, and UTC offset.
   b. Sending TIME_SYNC with the current UTC epoch.
   c. Sending the `server_data` JSON as a chunked SYNC_RESPONSE.
4. **Accept ACK** to confirm the watch received the data.
5. **Optionally send EXTRA** messages during the connection window.

The service should be resilient to the watch disconnecting at any point
(e.g. if a timeout fires mid-transfer).

## Platform Notes

The laptop service will run on macOS or Linux.  Recommended libraries:

- **Python (macOS/Linux):** `bleak` for scanning/connecting (Central),
  `bless` for running a GATT server (Peripheral).
- **Linux:** BlueZ with D-Bus API, or `bless` which wraps it.
- **macOS:** `bless` wraps CoreBluetooth.

The service will be built separately — this document defines the
interface contract.
