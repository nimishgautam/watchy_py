Here's a summary of everything that was built:
Files created (new_src/ble_server/):
__init__.py — empty package marker
protocol.py — injects const into builtins and re-exports all symbols from the watch-side ble_protocol.py, keeping a single source of truth
data_provider.py — abstract DataProvider base + DummyDataProvider that returns timezone-aware dummy weather and meetings anchored to the current local time
agent.py — registers a NoInputNoOutput BlueZ D-Bus pairing agent on Linux (enabling "Just Works" encrypted pairing); macOS stub provided as a hook
server.py — WatchyBLEServer using bless.BlessServer with TX (write) and RX (notify) characteristics; both require encryption (write_encryption_required / read_encryption_required) for pair-on-first-access; on SYNC_REQUEST, sends TIME_SYNC + chunked SYNC_RESPONSE via notifications. On macOS, CoreBluetooth handles pairing when the watch first writes; on Linux, agent.py auto-accepts.
__main__.py — entry point that wires everything together, run with cd new_src && python -m ble_server