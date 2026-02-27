from micropython import const

WIFI = const(("", ""))
WEBREPL_PASSWORD: str = const("")
UTC_OFFSET: int = const(1)

# BLE sync auth — must match laptop's secrets.AUTH_TOKEN
# Omit for backward compatibility (no auth)
# AUTH_TOKEN: str = ""