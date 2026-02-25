from lib.display import Display
from lib.bm8563 import BM8563
from machine import Pin, SoftI2C, ADC, WDT, Timer
import esp32
import machine
import micropython
import time
from utils import (
    hour_to_string,
    number_teen_to_string,
    number_tens_to_string,
    month_to_short_string,
    week_day_to_short_string,
)
from constants import (
    MENU_PIN,
    BACK_PIN,
    UP_PIN,
    DOWN_PIN,
    RTC_SDA_PIN,
    RTC_SCL_PIN,
    RTC_INT_PIN,
    BATT_ADC_PIN,
    WHITE,
    BLACK,
)

import assets.fonts.fira_sans_bold_58 as fira_sans_bold_58
import assets.fonts.fira_sans_regular_38 as fira_sans_regular_38
import assets.fonts.fira_sans_regular_28 as fira_sans_regular_28


DEBUG = False


class Watchy:
    def __init__(self):
        rtc_mem = machine.RTC().memory()
        self._debug_flag = len(rtc_mem) > 0 and rtc_mem[0] == 0x01
        self.sleep_enabled = not DEBUG and not self._debug_flag
        self.using_fallback_rtc = False

        self.display = Display()
        self.rtc = machine.RTC()
        self.rtc_driver = "machine"
        try:
            i2c = SoftI2C(sda=Pin(RTC_SDA_PIN), scl=Pin(RTC_SCL_PIN))
            i2c_devices = i2c.scan()
            if 0x51 in i2c_devices:
                self.rtc = BM8563(i2c)
                self.rtc.set_alarm_next_minute()
                self.rtc_driver = "bm8563"
                print("Using BM8563 RTC at 0x51")
            else:
                raise OSError("No supported RTC found on I2C bus")
        except OSError as err:
            # Keep running with a basic RTC source while RTC alarm support is unavailable.
            print("RTC alarm setup failed; running without RTC alarms.")
            print(err)
            self.rtc = machine.RTC()
            self.using_fallback_rtc = True
            self.sleep_enabled = False
        self.adc = ADC(Pin(BATT_ADC_PIN, Pin.IN))

        self.init_interrupts()
        # self.init_buttons()
        self.handle_wakeup()
        if self.sleep_enabled:
            self.wdt = WDT(timeout=30000)
            self.wdt_timer = Timer(0)
            self.wdt_timer.init(mode=Timer.PERIODIC, period=10000, callback=self.feed_wdt)
            machine.deepsleep()
        elif self._debug_flag:
            Pin(MENU_PIN, Pin.IN).irq(
                handler=self._debug_button_irq, trigger=Pin.IRQ_RISING
            )

    def init_interrupts(self):
        esp32.wake_on_ext0(Pin(RTC_INT_PIN, Pin.IN), esp32.WAKEUP_ALL_LOW)

        buttons = (
            Pin(MENU_PIN, Pin.IN),
            Pin(BACK_PIN, Pin.IN),
            Pin(UP_PIN, Pin.IN),
            Pin(DOWN_PIN, Pin.IN),
        )
        esp32.wake_on_ext1(buttons, esp32.WAKEUP_ANY_HIGH)
        # NOTE: it is not possible to get the wakeup bit in MicroPython yet
        # see https://github.com/micropython/micropython/issues/6981

    def init_buttons(self):
        menu_pin = Pin(26, Pin.IN)
        back_pin = Pin(25, Pin.IN)
        up_pin = Pin(32, Pin.IN)
        down_pin = Pin(4, Pin.IN)
        for pin in [menu_pin]:  # back_pin, up_pin
            self.set_pin_handler(pin)

    def set_pin_handler(self, pin: Pin):
        pin.irq(
            handler=self.handle_pin_wakeup,
            trigger=Pin.WAKE_HIGH,
            wake=machine.DEEPSLEEP,
        )

    def handle_wakeup(self):
        reason = machine.wake_reason()
        if reason is machine.EXT0_WAKE or reason == 0:
            print("RTC wake")
            if self.rtc_driver == "bm8563":
                _, _, _, _, _, minutes, _, _ = self.rtc.datetime()
                if minutes % 15 == 0:
                    self.sync_ntp()
            self.display_prose_watchface()
        elif reason is machine.EXT1_WAKE:
            print("PIN wake")
            if Pin(MENU_PIN, Pin.IN).value() == 1:
                self._debug_flag = not self._debug_flag
                machine.RTC().memory(b'\x01' if self._debug_flag else b'\x00')
                self.sleep_enabled = not DEBUG and not self._debug_flag
                self.display_debug_message(self._debug_flag)
                time.sleep(1.5)
            self.display_prose_watchface()
        else:
            print("Wake for other reason")
            print(reason)

    def handle_pin_wakeup(self, pin: Pin):
        print("handle_pin_wakeup")
        print(pin)

    def display_prose_watchface(self):
        self.display.framebuf.fill(WHITE)
        datetime = self.rtc.datetime()
        (_, month, day, week_day, hours, minutes, _, _) = datetime
        if self.using_fallback_rtc and self.rtc_driver == "machine":
            # machine.RTC weekday is 0-6; watchface helpers expect 1-7.
            week_day += 1
        self.display.display_text(
            hour_to_string(hours), 10, 15, fira_sans_bold_58, WHITE, BLACK
        )

        display_minutes_1 = lambda text: self.display.display_text(
            text, 10, 80, fira_sans_regular_38, WHITE, BLACK
        )
        if minutes == 0:
            display_minutes_1("o'clock")
        elif minutes < 10:
            display_minutes_1("oh " + number_teen_to_string(minutes))
        elif minutes < 20:
            display_minutes_1(number_teen_to_string(minutes))
        else:
            minutes_tens_str, minutes_ones_str = number_tens_to_string(minutes)
            display_minutes_1(minutes_tens_str)
            self.display.display_text(
                minutes_ones_str, 10, 115, fira_sans_regular_38, WHITE, BLACK
            )
        week_day_str = week_day_to_short_string(week_day)
        month_str = month_to_short_string(month)
        self.display.display_text(
            f"{week_day_str}, {day} {month_str}",
            10,
            160,
            fira_sans_regular_28,
            WHITE,
            BLACK,
        )
        self.display.update()

    def display_debug_message(self, on: bool):
        self.display.framebuf.fill(WHITE)
        label = "debug mode on" if on else "debug mode off"
        self.display.display_text(label, 10, 80, fira_sans_regular_28, WHITE, BLACK)
        self.display.update()

    def _debug_button_irq(self, pin):
        pin.irq(handler=None)
        micropython.schedule(self._exit_debug_mode, None)

    def _exit_debug_mode(self, _arg):
        machine.RTC().memory(b'\x00')
        self._debug_flag = False
        self.display_debug_message(False)
        time.sleep(1.5)
        machine.deepsleep()

    def sync_ntp(self):
        """Connect to WiFi, pull NTP time, update the BM8563 RTC, disconnect."""
        import network
        from secrets import WIFI, UTC_OFFSET

        wlan = network.WLAN(network.STA_IF)
        already_connected = wlan.isconnected()

        if not already_connected:
            wlan.active(True)
            wlan.connect(WIFI[0], WIFI[1])
            for _ in range(10):
                if wlan.isconnected():
                    break
                time.sleep(1)

        if not wlan.isconnected():
            print("NTP: WiFi failed")
            return

        try:
            import ntptime
            utc_secs = ntptime.time()
        except Exception as e:
            print("NTP: fetch failed:", e)
            return
        finally:
            if not already_connected:
                wlan.active(False)

        local = time.gmtime(utc_secs + UTC_OFFSET * 3600)
        # time.gmtime -> (year, month, mday, hour, min, sec, weekday, yearday)
        # BM8563 expects  (year, month, day, weekday, hour, min, sec, subsec)
        self.rtc.datetime((
            local[0], local[1], local[2],
            local[6] + 1,
            local[3], local[4], local[5], 0
        ))
        print("NTP: synced")

    def get_battery_voltage(self) -> float:
        return self.adc.read_uv() / 1000 * 2

    def feed_wdt(self, timer):
        # TODO: verify that everything is functioning correctly
        self.wdt.feed()
