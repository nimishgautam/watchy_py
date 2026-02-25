import network, time, ntptime
from secrets import WIFI, UTC_OFFSET
from machine import Pin, SoftI2C
from lib.bm8563 import BM8563

# WiFi should already be connected in debug mode, but just in case:

wlan = network.WLAN(network.STA_IF)
already_connected = wlan.isconnected()

if not already_connected:
    wlan.active(True)
    wlan.connect(WIFI[0], WIFI[1])
    for _ in range(10):
        if wlan.isconnected():
            break
        time.sleep(1)

try:
    import ntptime
    utc_secs = ntptime.time()
    local = time.gmtime(utc_secs + UTC_OFFSET * 3600)
# time.gmtime -> (year, month, mday, hour, min, sec, weekday, yearday)
# BM8563 expects  (year, month, day, weekday, hour, min, sec, subsec)
    rtc = BM8563(SoftI2C(sda=Pin(21), scl=Pin(22)))
    rtc.datetime((
    local[0], local[1], local[2],
    local[6] + 1,
    local[3], local[4], local[5], 0
))
    print("NTP: synced")
except Exception as e:
    print("NTP: fetch failed:", e)

