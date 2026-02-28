Here's a summary of everything that was built:
Files created (new_src/ble_server/):
__init__.py — empty package marker
protocol.py — injects const into builtins and re-exports all symbols from the watch-side ble_protocol.py, keeping a single source of truth
data_provider.py — abstract DataProvider base + DummyDataProvider that returns timezone-aware dummy weather and meetings anchored to the current local time
agent.py — registers a NoInputNoOutput BlueZ D-Bus pairing agent on Linux (enabling "Just Works" encrypted pairing); macOS stub provided as a hook
server.py — WatchyBLEServer using bless.BlessServer with TX (write) and RX (notify) characteristics; on SYNC_REQUEST, sends TIME_SYNC + chunked SYNC_RESPONSE via notifications
__main__.py — entry point that wires everything together, run with cd new_src && python -m ble_server


Pre-sign-in script
cd new_src && poetry run python -m ble_server.sign_in
Run this once before the BLE server. It prints the device-code URL, waits for you to sign in, and saves the token to cache/ms_token.json.
Flow
First-time sign-in
   cd new_src && poetry run python -m ble_server.sign_in
Follow the device-code steps in the browser.
Start the server
   cd new_src && poetry run python -m ble_server
The calendar fetcher runs immediately on startup, then every 20 minutes. The weather fetcher runs when its cache is empty, then every 45 minutes.