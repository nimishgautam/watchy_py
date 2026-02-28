Here's a summary of everything that was built:
Files created (new_src/ble_server/):
__init__.py — empty package marker
protocol.py — injects const into builtins and re-exports all symbols from the watch-side ble_protocol.py, keeping a single source of truth
data_provider.py — abstract DataProvider base + DummyDataProvider that returns timezone-aware dummy weather and meetings anchored to the current local time
crypto.py — AES-256-CBC encrypt/decrypt for application-level payload encryption (key derived from AUTH_TOKEN)
server.py — WatchyBLEServer using bless.BlessServer with TX (write) and RX (notify) characteristics; on SYNC_REQUEST, sends TIME_SYNC + chunked encrypted SYNC_RESPONSE via notifications
__main__.py — entry point that wires everything together, run with cd new_src && python -m ble_server

AUTH_TOKEN is required in secrets.py; it must match the watch's AUTH_TOKEN.