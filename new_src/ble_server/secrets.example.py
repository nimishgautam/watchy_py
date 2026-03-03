"""Example secrets config. Copy to secrets.py and set your coordinates."""

# Weather (required)
LATITUDE = 52.52
LONGITUDE = 13.41

# Timezone for calendar events and utc_offset (optional).
# Use IANA name e.g. "Europe/Berlin", "America/New_York".
# If unset, uses system timezone (can be wrong in Docker/WSL/cloud).
# TIMEZONE = "Europe/Berlin"

# Microsoft Calendar (optional – omit to use dummy meetings)
# MS_TENANT_ID = "your-tenant-id"
# MS_CLIENT_ID = "your-client-id"
# MS_CLIENT_SECRET = "your-client-secret"

# BLE sync auth — required; must match watch's secrets.AUTH_TOKEN
# Used for authentication and to derive the encryption key (sha256)
AUTH_TOKEN = "your-shared-secret-token"
