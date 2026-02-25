"""CPython shim for micropython uctypes module.

bytearray_at and addressof are imported by writer.py but never called
in the rendering code path.
"""

def bytearray_at(addr, size):
    raise NotImplementedError("uctypes.bytearray_at is not available on CPython")

def addressof(obj):
    return id(obj)
