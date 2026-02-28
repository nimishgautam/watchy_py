from micropython import const

WIFI = const(("", ""))
WEBREPL_PASSWORD: str = const("")
UTC_OFFSET: int = const(1)

# BLE sync auth — required; must match laptop's secrets.AUTH_TOKEN
# Used for authentication and to derive the encryption key (sha256)
AUTH_TOKEN: str = "your-shared-secret-token"