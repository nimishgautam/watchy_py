from micropython import const


CONTROL_STATUS1_REG = const(0x00)
CONTROL_STATUS2_REG = const(0x01)
DATETIME_REG = const(0x02)  # 7 bytes: sec, min, hour, day, weekday, month, year
MINUTE_ALARM_REG = const(0x09)
HOUR_ALARM_REG = const(0x0A)
DAY_ALARM_REG = const(0x0B)
WEEKDAY_ALARM_REG = const(0x0C)

CONTROL2_AF = const(0x08)
CONTROL2_AIE = const(0x02)
ALARM_DISABLE_MATCH = const(0x80)


def dectobcd(decimal):
    return (decimal // 10) << 4 | (decimal % 10)


def bcdtodec(bcd):
    return ((bcd >> 4) * 10) + (bcd & 0x0F)


class BM8563:
    """BM8563 / PCF8563 RTC driver (I2C addr 0x51)."""

    def __init__(self, i2c, addr=0x51):
        self.i2c = i2c
        self.addr = addr
        self._timebuf = bytearray(7)
        self._buf = bytearray(1)

    def datetime(self, datetime=None):
        """Get or set datetime.

        Returns tuple compatible with DS3231 driver:
        (year, month, day, weekday, hour, minute, second, subsecond)
        where weekday is 1-7 (Mon-Sun).
        """
        if datetime is None:
            self.i2c.readfrom_mem_into(self.addr, DATETIME_REG, self._timebuf)
            seconds = bcdtodec(self._timebuf[0] & 0x7F)
            minutes = bcdtodec(self._timebuf[1] & 0x7F)
            hours = bcdtodec(self._timebuf[2] & 0x3F)
            day = bcdtodec(self._timebuf[3] & 0x3F)
            weekday = (self._timebuf[4] & 0x07) + 1
            month = bcdtodec(self._timebuf[5] & 0x1F)
            year = 2000 + bcdtodec(self._timebuf[6])
            return (year, month, day, weekday, hours, minutes, seconds, 0)

        year, month, day, weekday, hours, minutes, seconds, _ = datetime
        self._timebuf[0] = dectobcd(seconds) & 0x7F
        self._timebuf[1] = dectobcd(minutes) & 0x7F
        self._timebuf[2] = dectobcd(hours) & 0x3F
        self._timebuf[3] = dectobcd(day) & 0x3F
        self._timebuf[4] = (weekday - 1) & 0x07
        self._timebuf[5] = dectobcd(month) & 0x1F
        self._timebuf[6] = dectobcd(year % 100)
        self.i2c.writeto_mem(self.addr, DATETIME_REG, self._timebuf)
        return True

    def set_alarm_next_minute(self):
        """Configure minute alarm to fire on next minute boundary."""
        _, _, _, _, _, minute, _, _ = self.datetime()
        next_minute = (minute + 1) % 60
        self.set_alarm_at_minute(next_minute)

    def set_alarm_at_minute(self, target_minute):
        """Configure minute alarm to fire when minute register matches target."""
        self.i2c.writeto_mem(self.addr, MINUTE_ALARM_REG, bytearray([dectobcd(target_minute)]))
        self.i2c.writeto_mem(
            self.addr,
            HOUR_ALARM_REG,
            bytearray([ALARM_DISABLE_MATCH, ALARM_DISABLE_MATCH, ALARM_DISABLE_MATCH]),
        )
        self._set_alarm_interrupt_enabled(True)
        self.clear_alarm_flag()

    def clear_alarm_flag(self):
        self.i2c.readfrom_mem_into(self.addr, CONTROL_STATUS2_REG, self._buf)
        self.i2c.writeto_mem(
            self.addr,
            CONTROL_STATUS2_REG,
            bytearray([self._buf[0] & ~CONTROL2_AF]),
        )

    def _set_alarm_interrupt_enabled(self, enabled):
        self.i2c.readfrom_mem_into(self.addr, CONTROL_STATUS2_REG, self._buf)
        value = self._buf[0]
        value = (value | CONTROL2_AIE) if enabled else (value & ~CONTROL2_AIE)
        self.i2c.writeto_mem(self.addr, CONTROL_STATUS2_REG, bytearray([value]))
