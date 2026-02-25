"""CPython shim for micropython module. const() is a compile-time hint; identity on CPython."""

def const(x):
    return x
