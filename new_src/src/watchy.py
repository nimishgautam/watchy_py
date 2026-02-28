from lib.display import Display
from lib.bm8563 import BM8563
from machine import Pin, SoftI2C, ADC
import esp32
import machine
import micropython
import time
import json
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
    DUMMY_DATA,
)

_CACHE_FILE = "server_cache.json"

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
        self._last_battery_voltage = None
        self._force_sync = False

        cached = self._cache_read()
        if cached:
            self._server_data = cached["data"]
            self._server_data_last_updated = (cached["fetch_hour"], cached["fetch_minute"])
            self._server_data_stale = True
        else:
            if DUMMY_DATA:
                self._server_data = self._build_mock_server_data(hour=0, minute=0)
            else:
                self._server_data = {
                    "utc_offset": 0,
                    "weather_now": {},
                    "weather_1h": {},
                    "meetings": [],
                }
            self._server_data_last_updated = None
            self._server_data_stale = True

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
        else:
            Pin(MENU_PIN, Pin.IN).irq(
                handler=self._debug_button_irq, trigger=Pin.IRQ_RISING
            )
            while self._debug_flag:
                time.sleep(0.5)

    def _debug_button_irq(self, pin):
        pin.irq(handler=None)
        micropython.schedule(self._exit_debug_mode, None)

    def _exit_debug_mode(self, _arg):
        machine.RTC().memory(b'\x00')
        self._debug_flag = False
        self._display_status_message("debug mode off")
        time.sleep(1.5)
        machine.deepsleep()

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
        menu = Pin(MENU_PIN, Pin.IN).value() == 1
        back = Pin(BACK_PIN, Pin.IN).value() == 1

        if menu and back:
            self._handle_pairing()
        elif menu:
            self._handle_debug_toggle()
        elif back:
            self._force_sync = True

    def _handle_pairing(self):
        print("MENU+BACK held — entering pairing mode")
        self._display_status_message("pairing mode")

        import gc
        gc.collect()
        from ble_client import BLEClient
        client = BLEClient()
        result = client.enter_pairing_mode()
        if result is False:
            client.disconnect()
            self._display_status_message("pairing failed")
        else:
            success, sync_result = result
            if sync_result:
                self._server_data = sync_result["data"]
                now = self.rtc.datetime()
                data = sync_result["data"]
                fh, fm = data.get("fetch_hour"), data.get("fetch_minute")
                if fh is not None and fm is not None:
                    self._server_data_last_updated = (fh, fm)
                else:
                    self._server_data_last_updated = (now[4], now[5])
                self._server_data_stale = False
                if sync_result.get("epoch") is not None:
                    self._apply_time_sync(sync_result["epoch"])
                self._cache_write(data, now[4], now[5])
                print("BLE pairing+sync OK")
            self._display_status_message("paired")
        time.sleep(1.5)

    def _handle_debug_toggle(self):
        self._debug_flag = not self._debug_flag
        machine.RTC().memory(b'\x01' if self._debug_flag else b'\x00')
        self.sleep_enabled = not DEBUG and not self._debug_flag
        label = "debug mode on" if self._debug_flag else "debug mode off"
        self._display_status_message(label)
        time.sleep(1.5)

    def update(self, now: tuple):
        (_, month, day, _, hour, minute, _, _) = now
        self.update_battery()

        should_sync = self.is_quarter_boundary(minute) or self._force_sync
        self._force_sync = False

        if should_sync:
            self.update_server_data(hour, minute)

        self.render_display(
            now=now,
            server_data=self._server_data,
            partial_refresh=False,
        )

    def update_battery(self):
        self._last_battery_voltage = self.get_battery_voltage()
        print("battery: {:.2f}v".format(self._last_battery_voltage))

    def update_server_data(self, hour: int, minute: int):
        if DUMMY_DATA:
            self._server_data = self._build_mock_server_data(hour=hour, minute=minute)
            self._server_data_last_updated = (hour, minute)
            self._server_data_stale = False
            print("dummy server_data at {:02d}:{:02d}".format(hour, minute))
            return

        try:
            import gc
            gc.collect()
            from ble_client import BLEClient
            client = BLEClient()
            if client.scan_and_connect():
                result = client.request_sync()
                if result:
                    client.persist_bond()
                    data = result["data"]
                    self._server_data = data
                    fh, fm = data.get("fetch_hour"), data.get("fetch_minute")
                    if fh is not None and fm is not None:
                        self._server_data_last_updated = (fh, fm)
                    else:
                        self._server_data_last_updated = (hour, minute)
                    self._server_data_stale = False
                    if result["epoch"] is not None:
                        self._apply_time_sync(result["epoch"])
                    self._cache_write(data, hour, minute)
                    print("BLE sync OK at {:02d}:{:02d}".format(hour, minute))
                client.disconnect()
                if result:
                    return
            else:
                client.disconnect()
        except Exception as e:
            print("BLE sync failed:", e)

        self._server_data_stale = True
        print("BLE sync failed — data is stale")

    def _apply_time_sync(self, epoch: int):
        """Adjust the RTC from a UTC epoch received over BLE."""
        utc_offset = self._server_data.get("utc_offset", 0)
        local_epoch = epoch + utc_offset * 3600
        tm = time.gmtime(local_epoch)
        # tm: (year, month, mday, hour, minute, second, weekday, yearday)
        self.rtc.set_datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
        print("RTC synced from BLE epoch={} offset={}".format(epoch, utc_offset))

    def maybe_sync_ntp(self):
        """Manual NTP sync — kept as fallback, not called automatically."""
        print("TODO maybe_sync_ntp (manual trigger only)")

    def render_display(self, now: tuple, server_data: dict, partial_refresh: bool):
        from renderer import render_all

        self._debug_log_render_payload(server_data, partial_refresh)

        (year, month, day, week_day, hour, minute, _, _) = now

        stale_since_hour = None
        if self._server_data_stale and self._server_data_last_updated:
            stale_since_hour = self._server_data_last_updated[0]

        has_valid_weather = self._server_data_last_updated is not None
        data_is_fresh = not self._server_data_stale

        render_all(
            self.display.framebuf,
            hour=hour,
            minute=minute,
            week_day=week_day,
            year=year,
            month=month,
            day=day,
            battery_voltage=self._last_battery_voltage or 0.0,
            server_data=server_data,
            stale_since_hour=stale_since_hour,
            has_valid_weather=has_valid_weather,
            data_is_fresh=data_is_fresh,
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

    def display_prose_watchface(self, partial_refresh: bool):
        import assets.fonts.fira_sans_regular_28 as fira_sans_regular_28
        import assets.fonts.fira_sans_regular_20 as fira_sans_regular_20
        import assets.fonts.fira_sans_regular_14 as fira_sans_regular_14
        self.display.framebuf.fill(WHITE)
        (_, month, day, week_day, hours, minutes, _, _) = self.rtc.datetime()

        self.display.display_text(
            hour_to_string(hours), 10, 15, fira_sans_regular_28, WHITE, BLACK
        )

        display_minutes_1 = lambda text: self.display.display_text(
            text, 10, 60, fira_sans_regular_20, WHITE, BLACK
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
                minutes_ones_str, 10, 85, fira_sans_regular_20, WHITE, BLACK
            )

        week_day_str = week_day_to_short_string(week_day)
        month_str = month_to_short_string(month)
        self.display.display_text(
            f"{week_day_str}, {day} {month_str}",
            10,
            160,
            fira_sans_regular_14,
            WHITE,
            BLACK,
        )
        self.display.update(partial=partial_refresh)

    def _display_status_message(self, label: str):
        import assets.fonts.fira_sans_regular_14 as fira_sans_regular_14
        self.display.framebuf.fill(WHITE)
        self.display.display_text(label, 10, 80, fira_sans_regular_14, WHITE, BLACK)
        self.display.update()

    def get_battery_voltage(self) -> float:
        return self.adc.read_uv() / 1000 * 2

    def _cache_write(self, data: dict, hour: int, minute: int):
        fh = data.get("fetch_hour", hour)
        fm = data.get("fetch_minute", minute)
        try:
            with open(_CACHE_FILE, "w") as f:
                json.dump({"data": data, "fetch_hour": fh, "fetch_minute": fm}, f)
        except OSError as e:
            print("cache write failed:", e)

    @staticmethod
    def _cache_read():
        try:
            with open(_CACHE_FILE, "r") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _build_mock_server_data(self, hour=None, minute=None) -> dict:
        now = self.rtc.datetime()
        if hour is None or minute is None:
            hour = now[4]
            minute = now[5]
        year, month, day = now[0], now[1], now[2]
        today = "{:04d}-{:02d}-{:02d}".format(year, month, day)
        next_hour = (hour + 1) % 24
        return {
            "utc_offset": -5,
            "weather_now": {"temp": 70 + (hour % 4), "condition": "sunny"},
            "weather_1h": {"temp": 66 + (next_hour % 4), "condition": "cloudy_thin"},
            "fetch_hour": hour,
            "fetch_minute": minute,
            "meetings": [
                {
                    "date": today,
                    "start_hour": hour,
                    "start_minute": (minute + 15) % 60,
                    "duration_min": 30,
                    "title": "Standup",
                    "type": "meeting",
                },
                {
                    "date": today,
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
