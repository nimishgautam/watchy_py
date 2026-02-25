# This file is executed on every boot (including wake-boot from deepsleep)
import machine

rtc_mem = machine.RTC().memory()
debug_mode = len(rtc_mem) > 0 and rtc_mem[0] == 0x01

if debug_mode:
    try:
        import network
        from secrets import WIFI
        if WIFI[0] and WIFI[1]:
            wlan = network.WLAN(network.STA_IF)
            wlan.active(True)
            wlan.connect(WIFI[0], WIFI[1])
    except Exception:
        pass
    try:
        import webrepl
        webrepl.start()
    except Exception:
        pass
