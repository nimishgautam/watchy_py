import machine

machine.RTC().memory(b"\x00")
machine.reset()