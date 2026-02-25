"""BLE pairing agent — platform-dispatched.

On Linux, registers a NoInputNoOutput D-Bus agent with BlueZ so the
watch's ``gap_pair()`` request is accepted automatically ("Just Works"
LE Secure Connections).  BlueZ persists the bond in
``/var/lib/bluetooth/``.

On macOS, CoreBluetooth surfaces a system pairing dialog when the central
initiates — no custom agent is needed.  A stub is provided as a hook for
any future macOS-specific logic.
"""

# NOTE: Do NOT use ``from __future__ import annotations`` here.
# dbus_next inspects method annotations at runtime as D-Bus type
# signatures (e.g. "o", "u", "s").  PEP 563 stringifies them, which
# breaks dbus_next's introspection.

import logging
import sys

log = logging.getLogger(__name__)

AGENT_PATH = "/com/watchy/agent"
AGENT_CAPABILITY = "NoInputNoOutput"


# ---------------------------------------------------------------------------
# Linux — BlueZ D-Bus agent via dbus_next
# ---------------------------------------------------------------------------

async def _register_linux_agent():
    """Register a NoInputNoOutput agent with BlueZ over D-Bus."""
    try:
        from dbus_next.aio import MessageBus
        from dbus_next.service import ServiceInterface, method
        from dbus_next import BusType
    except ImportError:
        log.warning("dbus_next not available — skipping agent registration")
        return None

    class _BluezAgent(ServiceInterface):
        """Implements org.bluez.Agent1 with NoInputNoOutput capability."""

        def __init__(self):
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self):  # noqa: N802
            log.info("Agent released")

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802
            log.info("Auto-accepting pairing for %s (passkey %d)", device, passkey)

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802
            log.info("Authorizing service %s for %s", uuid, device)

        @method()
        def Cancel(self):  # noqa: N802
            log.info("Pairing cancelled")

        @method()
        def RequestPinCode(self, device: "o") -> "s":  # noqa: N802
            log.info("PinCode requested for %s — returning empty", device)
            return ""

        @method()
        def RequestPasskey(self, device: "o") -> "u":  # noqa: N802
            log.info("Passkey requested for %s — returning 0", device)
            return 0

        @method()
        def RequestAuthorization(self, device: "o"):  # noqa: N802
            log.info("Authorization requested for %s — auto-accepting", device)

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    agent = _BluezAgent()
    bus.export(AGENT_PATH, agent)

    introspect = await bus.introspect("org.bluez", "/org/bluez")
    proxy = bus.get_proxy_object("org.bluez", "/org/bluez", introspect)
    manager = proxy.get_interface("org.bluez.AgentManager1")

    await manager.call_register_agent(AGENT_PATH, AGENT_CAPABILITY)
    await manager.call_request_default_agent(AGENT_PATH)
    log.info("BlueZ pairing agent registered at %s (%s)", AGENT_PATH, AGENT_CAPABILITY)

    return bus  # caller must keep this alive so the agent stays registered


# ---------------------------------------------------------------------------
# macOS stub
# ---------------------------------------------------------------------------

async def _register_macos_agent():
    log.info("macOS: pairing handled by OS — no custom agent needed")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def register_agent():
    """Register a platform-appropriate pairing agent.

    Returns an object that must be kept alive for the agent to remain
    registered (on Linux this is the D-Bus ``MessageBus``).
    """
    if sys.platform == "linux":
        return await _register_linux_agent()
    elif sys.platform == "darwin":
        return await _register_macos_agent()
    else:
        log.warning("Unsupported platform %s — skipping agent", sys.platform)
        return None
