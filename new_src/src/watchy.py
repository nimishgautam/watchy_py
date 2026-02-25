from lib.display import Display
from lib.bm8563 import BM8563
from machine import Pin, SoftI2C, ADC
import esp32
import machine
import micropython
import time
from renderer import render_all
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
QUARTER_BOUNDARY_MINUTES = (0, 15, 30, 45)
TRANSITION_OFFSET_MINUTES = 2
# Wake every quarter boundary and 2 minutes before the next quarter.
WAKE_MINUTES = tuple(
    sorted(QUARTER_BOUNDARY_MINUTES + tuple(
        (minute - TRANSITION_OFFSET_MINUTES) % 60
        for minute in QUARTER_BOUNDARY_MINUTES
    ))
)
QUARTER_BOUNDARY_LOOKUP = {minute: True for minute in QUARTER_BOUNDARY_MINUTES}


class Watchy:
    def __init__(self):
        rtc_mem = machine.RTC().memory()
        self._debug_flag = len(rtc_mem) > 0 and rtc_mem[0] == 0x01
        self.sleep_enabled = not DEBUG and not self._debug_flag
        self._debug_exit_irq_armed = False
        self._last_battery_voltage = None
        self._server_data = self._build_mock_server_data(hour=0, minute=0)
        self._server_data_last_updated = None

        self.display = Display()
        i2c = SoftI2C(sda=Pin(RTC_SDA_PIN), scl=Pin(RTC_SCL_PIN))
        if 0x51 not in i2c.scan():
            raise RuntimeError("BM8563 RTC not detected at 0x51")
        self.rtc = BM8563(i2c)
        self.adc = ADC(Pin(BATT_ADC_PIN, Pin.IN))

        self.init_interrupts()

    def run(self):
        self.handle_wakeup()

        now = self.rtc.datetime()
        self.update(now)
        self.schedule_next_wake(now[5])

        if self.sleep_enabled:
            machine.deepsleep()
            return

        if self._debug_flag:
            self.arm_debug_exit_irq()

    def init_interrupts(self):
        esp32.wake_on_ext0(Pin(RTC_INT_PIN, Pin.IN), esp32.WAKEUP_ALL_LOW)
        buttons = (
            Pin(MENU_PIN, Pin.IN),
            Pin(BACK_PIN, Pin.IN),
            Pin(UP_PIN, Pin.IN),
            Pin(DOWN_PIN, Pin.IN),
        )
        esp32.wake_on_ext1(buttons, esp32.WAKEUP_ANY_HIGH)

    def handle_wakeup(self):
        reason = machine.wake_reason()
        if reason is machine.EXT1_WAKE:
            self.handle_pin_wake()
            return
        if reason is machine.EXT0_WAKE or reason == 0:
            print("RTC wake")
            return
        print("Wake for other reason")
        print(reason)

    def handle_pin_wake(self):
        print("PIN wake")
        if Pin(MENU_PIN, Pin.IN).value() != 1:
            return
        self._debug_flag = not self._debug_flag
        machine.RTC().memory(b"\x01" if self._debug_flag else b"\x00")
        self.sleep_enabled = not DEBUG and not self._debug_flag
        self.display_debug_message(self._debug_flag)
        time.sleep(1.5)

    def update(self, now: tuple):
        (_, month, day, _, hour, minute, _, _) = now
        self.update_battery()

        is_quarter_boundary = self.is_quarter_boundary(minute)
        if is_quarter_boundary:
            self.update_server_data(hour, minute)
            if hour == 1 and minute == 30:
                self.maybe_sync_ntp()

        self.render_display(
            now=now,
            server_data=self._server_data,
            partial_refresh=False,
        )

    def update_battery(self):
        self._last_battery_voltage = self.get_battery_voltage()
        print("battery: {:.2f}v".format(self._last_battery_voltage))

    def update_server_data(self, hour: int, minute: int):
        # TODO: replace mock payload with real server fetch + cache write.
        self._server_data = self._build_mock_server_data(hour=hour, minute=minute)
        self._server_data_last_updated = (hour, minute)
        print("mock server_data refreshed at {:02d}:{:02d}".format(hour, minute))

    def maybe_sync_ntp(self):
        # TODO: sync RTC from NTP once per day (1:30 AM).
        print("TODO maybe_sync_ntp")

    def render_display(self, now: tuple, server_data: dict, partial_refresh: bool):
        self._debug_log_render_payload(server_data, partial_refresh)

        (_, month, day, week_day, hour, minute, _, _) = now
        render_all(
            self.display.framebuf,
            hour=hour,
            minute=minute,
            week_day=week_day,
            month=month,
            day=day,
            battery_voltage=self._last_battery_voltage or 0.0,
            server_data=server_data,
        )
        self.display.update(partial=partial_refresh)

    def schedule_next_wake(self, minute: int):
        next_minute = self.next_wake_minute(minute)
        print("Scheduling wake at minute", next_minute)
        self.rtc.set_alarm_at_minute(next_minute)

    @staticmethod
    def is_quarter_boundary(minute: int) -> bool:
        return QUARTER_BOUNDARY_LOOKUP.get(minute, False)

    @staticmethod
    def next_wake_minute(minute: int) -> int:
        for candidate in WAKE_MINUTES:
            if candidate > minute:
                return candidate
        return WAKE_MINUTES[0]

    def arm_debug_exit_irq(self):
        if self._debug_exit_irq_armed:
            return
        Pin(MENU_PIN, Pin.IN).irq(
            handler=self._debug_button_irq, trigger=Pin.IRQ_RISING
        )
        self._debug_exit_irq_armed = True

    def display_prose_watchface(self, partial_refresh: bool):
        self.display.framebuf.fill(WHITE)
        (_, month, day, week_day, hours, minutes, _, _) = self.rtc.datetime()

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
        self.display.update(partial=partial_refresh)

    def display_debug_message(self, on: bool):
        self.display.framebuf.fill(WHITE)
        label = "debug mode on" if on else "debug mode off"
        self.display.display_text(label, 10, 80, fira_sans_regular_28, WHITE, BLACK)
        self.display.update()

    def _debug_button_irq(self, pin):
        pin.irq(handler=None)
        self._debug_exit_irq_armed = False
        micropython.schedule(self._exit_debug_mode, None)

    def _exit_debug_mode(self, _arg):
        machine.RTC().memory(b"\x00")
        self._debug_flag = False
        self.sleep_enabled = not DEBUG
        self.display_debug_message(False)
        time.sleep(1.5)
        machine.deepsleep()

    def get_battery_voltage(self) -> float:
        return self.adc.read_uv() / 1000 * 2

    def _build_mock_server_data(self, hour=None, minute=None) -> dict:
        if hour is None or minute is None:
            now = self.rtc.datetime()
            hour = now[4]
            minute = now[5]

        next_hour = (hour + 1) % 24
        return {
            "utc_offset": -5,
            "weather_now": {"temp": 70 + (hour % 4), "condition": "sunny"},
            "weather_1h": {"temp": 66 + (next_hour % 4), "condition": "cloudy"},
            "meetings": [
                {
                    "start_hour": hour,
                    "start_minute": (minute + 15) % 60,
                    "duration_min": 30,
                    "title": "Standup",
                    "type": "meeting",
                },
                {
                    "start_hour": next_hour,
                    "start_minute": 0,
                    "duration_min": 60,
                    "title": "Design review",
                    "type": "focus",
                },
            ],
        }

    def _debug_log_render_payload(self, server_data: dict, partial_refresh: bool):
        weather_now = server_data.get("weather_now", {})
        meetings = server_data.get("meetings", [])
        refresh_type = "partial" if partial_refresh else "full"
        print(
            "render {} refresh | weather_now={}F {} | meetings={}".format(
                refresh_type,
                weather_now.get("temp", "--"),
                weather_now.get("condition", "unknown"),
                len(meetings),
            )
        )
