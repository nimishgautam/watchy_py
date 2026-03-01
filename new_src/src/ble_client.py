"""BLE Central client for Watchy.

Connects to the laptop-side GATT peripheral, sends a SYNC_REQUEST,
collects the TIME_SYNC + SYNC_RESPONSE (+ optional EXTRA) messages via
notifications, and returns parsed server_data and UTC datetime.

The laptop-side peripheral advertises a custom service UUID and exposes
two characteristics:
  - TX (watch writes):  write-with-response
  - RX (watch reads):   notify

Bond data (peer address) is persisted to flash so subsequent connections
can skip scanning and connect directly.
"""

import bluetooth
import struct
import time
import json

from micropython import const

from ble_protocol import (
    MSG_SYNC_REQUEST,
    MSG_SYNC_RESPONSE,
    MSG_TIME_SYNC,
    MSG_EXTRA,
    MSG_ACK,
    MSG_ERROR,
    parse_header,
    chunk_message,
    ChunkedReceiver,
)

from ble_crypto import derive_key, encrypt, decrypt

from constants import (
    BLE_SERVICE_UUID,
    BLE_TX_CHAR_UUID,
    BLE_RX_CHAR_UUID,
    BLE_SCAN_TIMEOUT_MS,
    BLE_CONNECT_TIMEOUT_MS,
    BLE_SYNC_TIMEOUT_MS,
    BLE_PAIRING_TIMEOUT_MS,
)

# IRQ event constants
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_CHARACTERISTIC_DONE = const(12)
_IRQ_GATTC_WRITE_DONE = const(17)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_MTU_EXCHANGED = const(21)

_ADV_IND = const(0x00)
_ADV_DIRECT_IND = const(0x01)

_BOND_FILE = "ble_bond.json"

# CCC descriptor UUID for enabling notifications
_CCCD_UUID = bluetooth.UUID(0x2902)


def _decode_services(adv_data):
    """Extract 128-bit service UUIDs from advertisement payload."""
    services = []
    i = 0
    while i < len(adv_data):
        length = adv_data[i]
        if length == 0:
            break
        ad_type = adv_data[i + 1]
        # 0x06 = Incomplete 128-bit, 0x07 = Complete 128-bit
        if ad_type in (0x06, 0x07):
            j = i + 2
            while j + 16 <= i + 1 + length:
                services.append(bluetooth.UUID(bytes(adv_data[j:j + 16])))
                j += 16
        i += 1 + length
    return services


class BLEClient:
    def __init__(self):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)

        self._conn_handle = None
        self._tx_handle = None
        self._rx_handle = None
        self._service_start = None
        self._service_end = None
        self._mtu = 20

        # State flags set by IRQ, polled by blocking methods
        self._scan_found_addr = None
        self._scan_found_addr_type = None
        self._scan_done = False
        self._connected = False
        self._disconnected = False
        self._service_discovered = False
        self._chars_discovered = False
        self._write_done = False

        self._notify_buffer = []
        self._bonded_peer = self._load_bond()
        self._connected_addr_type = None
        self._connected_addr = None

    # ------------------------------------------------------------------
    # IRQ handler
    # ------------------------------------------------------------------

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            if adv_type in (_ADV_IND, _ADV_DIRECT_IND):
                for svc_uuid in _decode_services(adv_data):
                    if svc_uuid == BLE_SERVICE_UUID:
                        self._scan_found_addr_type = addr_type
                        self._scan_found_addr = bytes(addr)
                        self._ble.gap_scan(None)
                        break

        elif event == _IRQ_SCAN_DONE:
            self._scan_done = True

        elif event == _IRQ_PERIPHERAL_CONNECT:
            conn_handle, addr_type, addr = data
            self._conn_handle = conn_handle
            self._connected = True
            self._connected_addr_type = addr_type
            self._connected_addr = bytes(addr)
            self._ble.gattc_discover_services(conn_handle, BLE_SERVICE_UUID)

        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            self._conn_handle = None
            self._connected = False
            self._disconnected = True

        elif event == _IRQ_GATTC_SERVICE_RESULT:
            conn_handle, start_handle, end_handle, uuid = data
            if uuid == BLE_SERVICE_UUID:
                self._service_start = start_handle
                self._service_end = end_handle

        elif event == _IRQ_GATTC_SERVICE_DONE:
            if self._service_start is not None:
                self._ble.gattc_discover_characteristics(
                    self._conn_handle, self._service_start, self._service_end
                )
            self._service_discovered = True

        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            conn_handle, def_handle, value_handle, properties, uuid = data
            if uuid == BLE_TX_CHAR_UUID:
                self._tx_handle = value_handle
            elif uuid == BLE_RX_CHAR_UUID:
                self._rx_handle = value_handle

        elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
            self._chars_discovered = True

        elif event == _IRQ_GATTC_NOTIFY:
            conn_handle, value_handle, notify_data = data
            if conn_handle == self._conn_handle:
                self._notify_buffer.append(bytes(notify_data))

        elif event == _IRQ_GATTC_WRITE_DONE:
            self._write_done = True

        elif event == _IRQ_MTU_EXCHANGED:
            conn_handle, mtu = data
            self._mtu = mtu - 3

    # ------------------------------------------------------------------
    # Blocking helpers
    # ------------------------------------------------------------------

    def _wait_for(self, flag_name, timeout_ms):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while not getattr(self, flag_name):
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return False
            time.sleep_ms(10)
        return True

    def _enable_notifications(self):
        """Write 0x0001 to the RX characteristic's CCCD to enable notifications."""
        if self._rx_handle is None or self._conn_handle is None:
            return
        # CCCD is typically at value_handle + 1 for a notify characteristic
        cccd_handle = self._rx_handle + 1
        self._write_done = False
        self._ble.gattc_write(self._conn_handle, cccd_handle, b"\x01\x00", 1)
        self._wait_for("_write_done", 3000)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_and_connect(self, timeout_ms=None):
        """Connect to the bonded peer, or scan if no bond exists.

        Returns True on successful connection with characteristics
        discovered, False otherwise.
        """
        scan_timeout = timeout_ms or BLE_SCAN_TIMEOUT_MS
        connect_timeout = BLE_CONNECT_TIMEOUT_MS

        # Reset state
        self._connected = False
        self._disconnected = False
        self._service_discovered = False
        self._chars_discovered = False
        self._service_start = None
        self._service_end = None
        self._tx_handle = None
        self._rx_handle = None

        if self._bonded_peer:
            print("BLE: connecting to bonded peer")
            self._ble.gap_connect(
                self._bonded_peer["addr_type"],
                bytes(self._bonded_peer["addr"]),
            )
        else:
            print("BLE: scanning for service")
            self._scan_found_addr = None
            self._scan_done = False
            self._ble.gap_scan(scan_timeout, 30000, 30000)

            if not self._wait_for("_scan_done", scan_timeout + 1000):
                print("BLE: scan timeout")
                self._ble.gap_scan(None)
                return False

            if self._scan_found_addr is None:
                print("BLE: service not found")
                return False

            print("BLE: found peer, connecting")
            self._ble.gap_connect(self._scan_found_addr_type, self._scan_found_addr)

        if not self._wait_for("_connected", connect_timeout):
            print("BLE: connect timeout")
            return False

        # Wait for characteristic discovery to complete
        if not self._wait_for("_chars_discovered", 5000):
            print("BLE: char discovery timeout")
            self.disconnect()
            return False

        if self._tx_handle is None or self._rx_handle is None:
            print("BLE: required characteristics not found")
            self.disconnect()
            return False

        self._enable_notifications()

        # Request larger MTU (ESP32 supports up to 517)
        try:
            self._ble.config(mtu=517)
        except Exception:
            pass

        print("BLE: connected, tx={} rx={} mtu={}".format(
            self._tx_handle, self._rx_handle, self._mtu
        ))
        return True

    def enter_pairing_mode(self, timeout_ms=None):
        """Clear bond, scan for service, connect, and request sync data.

        Returns (True, sync_result) if connection succeeded (sync_result may be
        None if sync failed), or False if connection failed.
        """
        pairing_timeout = timeout_ms or BLE_PAIRING_TIMEOUT_MS

        self.clear_bond()

        self._scan_found_addr = None
        self._scan_done = False
        self._connected = False
        self._service_start = None
        self._service_end = None
        self._tx_handle = None
        self._rx_handle = None
        self._chars_discovered = False

        print("BLE: pairing mode — scanning")
        self._ble.gap_scan(pairing_timeout, 30000, 30000)

        if not self._wait_for("_scan_done", pairing_timeout + 1000):
            self._ble.gap_scan(None)
            print("BLE: pairing scan timeout")
            return False

        if self._scan_found_addr is None:
            print("BLE: no device found for pairing")
            return False

        print("BLE: found device, connecting")
        self._ble.gap_connect(self._scan_found_addr_type, self._scan_found_addr)

        if not self._wait_for("_connected", BLE_CONNECT_TIMEOUT_MS):
            print("BLE: pairing connect timeout")
            return False

        # Discover characteristics
        if not self._chars_discovered:
            self._service_discovered = False
            self._ble.gattc_discover_services(self._conn_handle, BLE_SERVICE_UUID)
            if not self._wait_for("_chars_discovered", 5000):
                print("BLE: char discovery timeout")
                self.disconnect()
                return (True, None)

        if self._tx_handle is None or self._rx_handle is None:
            print("BLE: required characteristics not found")
            self.disconnect()
            return (True, None)

        self._enable_notifications()

        try:
            self._ble.config(mtu=517)
        except Exception:
            pass

        # Store bond for future fast reconnect
        self._bonded_peer = {
            "addr_type": self._scan_found_addr_type,
            "addr": list(self._scan_found_addr),
        }
        self._save_bond()
        print("BLE: connected and bonded")

        result = self.request_sync()
        self.disconnect()
        return (True, result)

    def request_sync(self, timeout_ms=None):
        """Send SYNC_REQUEST, collect response messages.

        Returns dict with keys:
            "data":  parsed server_data dict (from SYNC_RESPONSE)
            "datetime": (year, month, day, hour, minute, second) UTC from TIME_SYNC, or None
            "extra": list of raw EXTRA payloads, or []
        Returns None on failure.
        """
        sync_timeout = timeout_ms or BLE_SYNC_TIMEOUT_MS

        if self._conn_handle is None or self._tx_handle is None:
            return None

        try:
            import secrets
            auth_token = getattr(secrets, "AUTH_TOKEN", "") or ""
        except ImportError:
            auth_token = ""
        if not auth_token:
            print("BLE: AUTH_TOKEN required in secrets.py")
            return None

        key = derive_key(auth_token)
        token_bytes = auth_token.encode("utf-8")
        encrypted_req = encrypt(token_bytes, key)
        frames = chunk_message(MSG_SYNC_REQUEST, encrypted_req, self._mtu, seq=0)

        self._notify_buffer.clear()
        for frame in frames:
            self._write_done = False
            self._ble.gattc_write(self._conn_handle, self._tx_handle, frame, 1)
            if not self._wait_for("_write_done", 3000):
                print("BLE: sync request write timeout")
                return None

        deadline = time.ticks_add(time.ticks_ms(), sync_timeout)
        receiver = ChunkedReceiver()
        utc_datetime = None
        extra_payloads = []
        server_data = None
        processed = 0

        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(10)

            while processed < len(self._notify_buffer):
                raw = self._notify_buffer[processed]
                processed += 1

                try:
                    msg_type, seq, total, idx, payload = parse_header(raw)
                except ValueError:
                    continue

                if msg_type == MSG_TIME_SYNC:
                    done, assembled = receiver.feed(seq, total, idx, payload)
                    if done:
                        try:
                            plain = decrypt(assembled, key)
                            if len(plain) >= 7:
                                year, month, day, hour, minute, second = struct.unpack(
                                    "<HBBBBB", plain[:7]
                                )
                                utc_datetime = (year, month, day, hour, minute, second)
                        except (ValueError, Exception) as e:
                            print("BLE: decrypt TIME_SYNC failed:", e)

                elif msg_type == MSG_SYNC_RESPONSE:
                    done, assembled = receiver.feed(seq, total, idx, payload)
                    if done:
                        try:
                            plain = decrypt(assembled, key)
                            server_data = json.loads(plain)
                        except (ValueError, Exception) as e:
                            print("BLE: bad SYNC_RESPONSE:", e)

                elif msg_type == MSG_EXTRA:
                    done, assembled = receiver.feed(seq, total, idx, payload)
                    if done:
                        try:
                            plain = decrypt(assembled, key)
                            extra_payloads.append(plain)
                        except (ValueError, Exception):
                            pass

                elif msg_type == MSG_ERROR:
                    done, assembled = receiver.feed(seq, total, idx, payload)
                    if done:
                        try:
                            plain = decrypt(assembled, key)
                            code = plain[0] if plain else 0
                        except (ValueError, Exception):
                            code = 0
                        print("BLE: received ERROR code={}".format(code))
                        return None

            if server_data is not None:
                break

        if server_data is None:
            print("BLE: sync response timeout")
            return None

        # Send ACK (encrypted empty payload)
        ack_encrypted = encrypt(b"", key)
        ack_frames = chunk_message(MSG_ACK, ack_encrypted, self._mtu, seq=0)
        for frame in ack_frames:
            self._write_done = False
            self._ble.gattc_write(self._conn_handle, self._tx_handle, frame, 1)
            self._wait_for("_write_done", 2000)

        return {"data": server_data, "datetime": utc_datetime, "extra": extra_payloads}

    def disconnect(self):
        """Disconnect and deactivate the BLE radio."""
        if self._conn_handle is not None:
            try:
                self._ble.gap_disconnect(self._conn_handle)
            except Exception:
                pass
        self._conn_handle = None
        self._tx_handle = None
        self._rx_handle = None
        try:
            self._ble.active(False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Bond persistence
    # ------------------------------------------------------------------

    def _load_bond(self):
        try:
            with open(_BOND_FILE, "r") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save_bond(self):
        try:
            with open(_BOND_FILE, "w") as f:
                json.dump(self._bonded_peer, f)
            print("BLE: bond saved to", _BOND_FILE)
        except OSError as e:
            print("BLE: failed to save bond:", e)

    def persist_bond(self):
        """Save the current connected peer as bonded for future direct connect.

        Call after a successful sync (e.g. from update flow) so the next
        sync can connect directly without scanning.
        """
        if self._conn_handle is None or self._connected_addr is None:
            return
        self._bonded_peer = {
            "addr_type": self._connected_addr_type,
            "addr": list(self._connected_addr),
        }
        self._save_bond()

    def clear_bond(self):
        """Remove stored bond data."""
        self._bonded_peer = None
        try:
            import os
            os.remove(_BOND_FILE)
        except OSError:
            pass
