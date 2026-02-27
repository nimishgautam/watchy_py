"""BLE GATT peripheral server for Watchy sync.

Advertises the Watchy sync service, accepts writes on the TX
characteristic (watch → laptop), and sends notifications on the RX
characteristic (laptop → watch).
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
import time
from typing import Any

from bless import (  # type: ignore[import-untyped]
    BlessGATTCharacteristic,
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)

from .data_provider import DataProvider
from .protocol import (
    ERR_AUTH_FAILED,
    ERR_NOT_READY,
    MSG_ACK,
    MSG_ERROR,
    MSG_SYNC_REQUEST,
    MSG_SYNC_RESPONSE,
    MSG_TIME_SYNC,
    chunk_message,
    frame_header,
    parse_header,
)

log = logging.getLogger(__name__)

SERVICE_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
TX_CHAR_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567891"
RX_CHAR_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567892"

# Conservative default — works with most adapters.  The chunking protocol
# handles any size; we can refine with runtime MTU detection later.
DEFAULT_USABLE_MTU = 185

INTER_CHUNK_DELAY_S = 0.02


class WatchyBLEServer:
    def __init__(
        self,
        data_provider: DataProvider,
        *,
        usable_mtu: int = DEFAULT_USABLE_MTU,
    ) -> None:
        self._data_provider = data_provider
        self._usable_mtu = usable_mtu
        self._server: BlessServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()

        trigger = (
            asyncio.Event()
            if sys.platform not in ("darwin", "win32")
            else __import__("threading").Event()
        )

        self._server = BlessServer(name="WatchySync", loop=self._loop)
        self._server.read_request_func = self._on_read
        self._server.write_request_func = self._on_write

        await self._server.add_new_service(SERVICE_UUID)

        # TX — watch writes here (SYNC_REQUEST, ACK, ERROR)
        await self._server.add_new_characteristic(
            SERVICE_UUID,
            TX_CHAR_UUID,
            GATTCharacteristicProperties.write,
            None,
            GATTAttributePermissions.writeable,
        )

        # RX — server notifies here (TIME_SYNC, SYNC_RESPONSE)
        await self._server.add_new_characteristic(
            SERVICE_UUID,
            RX_CHAR_UUID,
            GATTCharacteristicProperties.read
            | GATTCharacteristicProperties.notify,
            None,
            GATTAttributePermissions.readable,
        )

        await self._server.start()
        log.info(
            "Advertising as 'WatchySync' — service %s", SERVICE_UUID
        )

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop()
            log.info("Server stopped")

    # ------------------------------------------------------------------
    # GATT callbacks
    # ------------------------------------------------------------------

    def _on_read(
        self, characteristic: BlessGATTCharacteristic, **kwargs: Any
    ) -> bytearray:
        log.debug("Read request on %s", characteristic.uuid)
        return characteristic.value or bytearray()

    def _on_write(
        self, characteristic: BlessGATTCharacteristic, value: Any, **kwargs: Any
    ) -> None:
        raw = bytes(value)
        log.debug(
            "Write on %s — %d bytes: %s",
            characteristic.uuid,
            len(raw),
            raw.hex(),
        )

        try:
            msg_type, seq, total, idx, payload = parse_header(raw)
        except ValueError:
            log.warning("Malformed frame on TX: %s", raw.hex())
            return

        if msg_type == MSG_SYNC_REQUEST:
            log.info("SYNC_REQUEST received (seq=%d)", seq)
            # Validate AUTH_TOKEN if server has one configured
            try:
                from . import secrets
                expected = getattr(secrets, "AUTH_TOKEN", "") or ""
            except ImportError:
                expected = ""
            if expected:
                if payload != expected.encode("utf-8"):
                    log.warning("Auth failed — token mismatch")
                    err_frame = frame_header(MSG_ERROR, seq, 1, 0) + bytes(
                        [ERR_AUTH_FAILED]
                    )
                    self._notify(err_frame)
                    return
            if self._loop is not None:
                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._handle_sync(seq),
                )
        elif msg_type == MSG_ACK:
            log.info("ACK received (seq=%d)", seq)
        elif msg_type == MSG_ERROR:
            code = payload[0] if payload else 0
            log.warning("ERROR received (seq=%d, code=0x%02x)", seq, code)
        else:
            log.debug(
                "Unhandled msg_type 0x%02x on TX (seq=%d)", msg_type, seq
            )

    # ------------------------------------------------------------------
    # Sync response
    # ------------------------------------------------------------------

    async def _handle_sync(self, seq: int) -> None:
        assert self._server is not None

        # 1. TIME_SYNC — current UTC epoch as uint32 LE
        epoch = int(time.time())
        time_frame = frame_header(MSG_TIME_SYNC, seq, 1, 0) + struct.pack(
            "<I", epoch
        )
        self._notify(time_frame)
        log.info("Sent TIME_SYNC epoch=%d", epoch)

        await asyncio.sleep(INTER_CHUNK_DELAY_S)

        # 2. SYNC_RESPONSE — chunked JSON (or ERROR if data unavailable)
        server_data = self._data_provider.get_server_data()
        if server_data is None:
            log.warning("No cached data — sending ERROR Not ready")
            err_frame = frame_header(MSG_ERROR, seq, 1, 0) + bytes([ERR_NOT_READY])
            self._notify(err_frame)
            return

        payload = json.dumps(server_data, separators=(",", ":")).encode()
        frames = chunk_message(MSG_SYNC_RESPONSE, payload, self._usable_mtu, seq=seq)
        log.info(
            "Sending SYNC_RESPONSE: %d bytes, %d chunk(s)",
            len(payload),
            len(frames),
        )

        for i, frame in enumerate(frames):
            self._notify(frame)
            log.debug("  chunk %d/%d sent (%d bytes)", i + 1, len(frames), len(frame))
            if i < len(frames) - 1:
                await asyncio.sleep(INTER_CHUNK_DELAY_S)

        log.info("SYNC_RESPONSE complete — waiting for ACK")

    def _notify(self, data: bytes) -> None:
        """Push a notification on the RX characteristic."""
        assert self._server is not None
        char = self._server.get_characteristic(RX_CHAR_UUID)
        if char is None:
            log.error("RX characteristic not found")
            return
        char.value = bytearray(data)
        self._server.update_value(SERVICE_UUID, RX_CHAR_UUID)
