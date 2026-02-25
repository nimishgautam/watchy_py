import network
import time
import machine
from secrets import WIFI


def connect_to_wifi(ssid: str, password: str):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(ssid, password)
        timeout = 10
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
    if wlan.isconnected():
        print("WiFi connected:", wlan.ifconfig())
    else:
        print("WiFi connection failed")


# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)

rtc_mem = machine.RTC().memory()
debug_mode = len(rtc_mem) > 0 and rtc_mem[0] == 0x01

if debug_mode:
    connect_to_wifi(WIFI[0], WIFI[1])
    import webrepl

    webrepl.start()
