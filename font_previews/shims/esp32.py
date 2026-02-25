"""CPython shim for micropython esp32 module.

Only needs to not crash on import. The renderer never calls hardware functions.
"""

WAKEUP_ALL_LOW = 0
WAKEUP_ANY_HIGH = 1

def wake_on_ext0(*args, **kwargs):
    pass

def wake_on_ext1(*args, **kwargs):
    pass

def raw_temperature():
    return 100
