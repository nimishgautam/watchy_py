import machine

rtc_mem = machine.RTC().memory()
debug_mode = len(rtc_mem) > 0 and rtc_mem[0] == 0x01

if debug_mode:
    from machine import Pin, Timer

    MENU_PIN = 26
    LONG_PRESS_MS = 1500
    POLL_MS = 200
    _menu_held_count = [0]

    def _check_menu(timer):
        if Pin(MENU_PIN, Pin.IN).value() == 1:
            _menu_held_count[0] += 1
            if _menu_held_count[0] * POLL_MS >= LONG_PRESS_MS:
                machine.RTC().memory(b"\x00")
                machine.reset()
        else:
            _menu_held_count[0] = 0

    t = Timer(1)
    t.init(period=POLL_MS, mode=Timer.PERIODIC, callback=_check_menu)
    # Keep reference so timer keeps running at REPL
    __debug_timer = t
else:
    from watchy import Watchy
    from utils import vibrate_motor
    import uasyncio as asyncio

    async def main():
        w = Watchy()
        w.run()

    asyncio.run(main())
