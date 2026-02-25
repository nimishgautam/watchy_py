"""CPython shim for micropython machine module.

Only needs to not crash on import. The renderer never calls hardware functions.
"""

class Pin:
    IN = 0
    OUT = 1
    IRQ_RISING = 1

    def __init__(self, *args, **kwargs):
        pass

    def value(self, *args):
        return 0

    def irq(self, **kwargs):
        pass

    def off(self):
        pass


class SPI:
    def __init__(self, *args, **kwargs):
        pass


class SoftI2C:
    def __init__(self, *args, **kwargs):
        pass

    def scan(self):
        return []


class ADC:
    def __init__(self, *args, **kwargs):
        pass

    def read_uv(self):
        return 0


class RTC:
    def __init__(self):
        pass

    def memory(self, *args):
        return b""


EXT0_WAKE = 2
EXT1_WAKE = 3

def wake_reason():
    return 0

def deepsleep(*args):
    pass

def reset():
    pass
