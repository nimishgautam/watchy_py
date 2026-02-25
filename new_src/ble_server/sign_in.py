"""Pre-sign-in script for Microsoft Calendar.

Run this before starting the BLE server to complete the device-code OAuth flow.
Saves the token to cache/ms_token.json (separate from weather data).
After signing in once, the BLE server will use the cached token silently.

Usage:
    cd new_src && poetry run python -m ble_server.sign_in
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure we can import from ble_server
BLE_SERVER_DIR = Path(__file__).resolve().parent
if str(BLE_SERVER_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BLE_SERVER_DIR.parent))

from ble_server.microsoft_calendar import get_access_token

TOKEN_CACHE_PATH = BLE_SERVER_DIR / "cache" / "ms_token.json"


def main() -> int:
    try:
        from ble_server import secrets
    except ImportError:
        print(
            "secrets.py not found. Copy secrets.example.py to secrets.py "
            "and set MS_TENANT_ID, MS_CLIENT_ID."
        )
        return 1

    tenant = getattr(secrets, "MS_TENANT_ID", None)
    client_id = getattr(secrets, "MS_CLIENT_ID", None)
    client_secret = getattr(secrets, "MS_CLIENT_SECRET", None)
    if not tenant or not client_id:
        print(
            "Set MS_TENANT_ID and MS_CLIENT_ID in secrets.py. "
            "See secrets.example.py for reference."
        )
        return 1

    print("Initiating Microsoft device-code sign-in...")
    token = get_access_token(
        tenant_id=tenant,
        client_id=client_id,
        client_secret=client_secret,
        token_cache_path=TOKEN_CACHE_PATH,
    )

    if token:
        print("Sign-in successful. Token saved to", TOKEN_CACHE_PATH)
        return 0
    print("Sign-in failed. Check the message above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
