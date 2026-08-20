#!/usr/bin/env python3
"""Offline checks for the reverse-UART decoder.

The one test that carries real weight is the first: a byte-for-byte replay of
`fixtures/reverse_ksba_20260814.bin`, which is what a real NTSC console put on
RXD when START was pressed with KSBA in the editor. Everything else is
constructed, and constructed tests of a codec agree with themselves by
construction.

So the replay runs first, the expected code (KSBA) is fixed by the capture
itself, and the location frames are cross-checked against
nes_icao_request.request_bytes rather than against frame_bytes here.

No pytest. Run it directly:

    python test_uart_request.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import nes_icao_request as shared                          # noqa: E402
import nes_uart_request as uart                         # noqa: E402
from nes_icao_request import LocationRequest, PauseRequest, RequestCancelled  # noqa: E402

# The reverse-UART capture the tests replay.
CAPTURE = os.path.join(HERE, "fixtures", "reverse_ksba_20260814.bin")
CAPTURE_CODE = "KSBA"
CAPTURE_BURSTS = 2

failures = []


def check(name, condition, detail=""):
    if condition:
        print("  ok    {}".format(name))
    else:
        failures.append(name)
        print("  FAIL  {}  {}".format(name, detail))


class FakePort:
    """Delivers a byte stream in fixed-size chunks, then stays silent."""

    def __init__(self, data, chunk=None):
        self.data = bytes(data)
        self.chunk = chunk or len(self.data)
        self.offset = 0

    @property
    def in_waiting(self):
        return min(self.chunk, len(self.data) - self.offset)

    def read(self, count):
        taken = self.data[self.offset:self.offset + count]
        self.offset += len(taken)
        return taken


class FakeClock:
    """Monotonic and sleep that advance a virtual clock, so tests do not wait."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def drain(port, limit=4, **kwargs):
    """Collect up to `limit` events, stopping when the port runs dry.

    One reader across every call, which is how the server uses it. Building a
    fresh reader per call is exactly the bug this file caught.
    """
    clock = FakeClock()
    reader = uart.ReverseUartReader()
    events = []
    idle_deadline = [None]

    def stop():
        # Stop once the port is empty and the decoder has had time to give up.
        if port.in_waiting:
            idle_deadline[0] = None
            return False
        if idle_deadline[0] is None:
            idle_deadline[0] = clock.now + 2 * uart.BURST_GAP_SECONDS
        return clock.now >= idle_deadline[0]

    while len(events) < limit:
        try:
            events.append(reader(
                port, stop_requested=stop,
                monotonic=clock.monotonic, sleep=clock.sleep, **kwargs))
        except RequestCancelled:
            break
    return events


print("1. replay of the real console capture")
with open(CAPTURE, "rb") as handle:
    captured = handle.read()
print("   {} bytes: {}".format(
    len(captured), " ".join("{:02X}".format(b) for b in captured)))

# Whole capture in one chunk, the easy case.
events = drain(FakePort(captured))
check("both bursts decode", len(events) == CAPTURE_BURSTS, "got {}".format(len(events)))
check("both are location requests",
      all(isinstance(e, LocationRequest) for e in events))
check("both read {}".format(CAPTURE_CODE),
      all(getattr(e, "code", None) == CAPTURE_CODE for e in events),
      "got {}".format([getattr(e, "code", None) for e in events]))

# One byte at a time, which is the worst case the FTDI latency timer can hand
# over and the case where a naive fixed-offset parser falls apart.
events = drain(FakePort(captured, chunk=1))
check("byte at a time still decodes both",
      len(events) == CAPTURE_BURSTS and all(getattr(e, "code", None) == CAPTURE_CODE
                               for e in events),
      "got {}".format([getattr(e, "code", None) for e in events]))

# Starting mid-frame, as happens when the server attaches to a live console.
events = drain(FakePort(captured[4:]))
check("mid-frame start recovers on the second burst",
      len(events) == 1 and events[0].code == CAPTURE_CODE,
      "got {}".format([getattr(e, "code", None) for e in events]))

print()
print("2. agreement with the shared request_bytes rule")
mismatches = []
for first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    for last in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        code = first + "P" + "N" + last
        wire = b"\x00" + shared.request_bytes(code) + b"\x00"
        events = drain(FakePort(wire))
        if len(events) != 1 or events[0].code != code:
            mismatches.append(code)
check("676 codes decode to themselves", not mismatches,
      "first failures {}".format(mismatches[:5]))
check("the captured frame equals request_bytes({})".format(CAPTURE_CODE),
      captured[1:7] == shared.request_bytes(CAPTURE_CODE),
      "capture {} vs server {}".format(
          captured[1:7].hex(), shared.request_bytes(CAPTURE_CODE).hex()))

print()
print("3. the pause frame")
pause_wire = b"\x00" + uart.frame_bytes(uart.PAUSE_MARKER, bytes(4)) + b"\x00"
check("pause frame is 50 00 00 00 00 F5",
      pause_wire[1:7] == bytes((0x50, 0x00, 0x00, 0x00, 0x00, 0xF5)),
      pause_wire[1:7].hex())
events = drain(FakePort(pause_wire))
check("pause decodes", len(events) == 1 and isinstance(events[0], PauseRequest),
      "got {}".format(events))

print()
print("4. rejection")
good = shared.request_bytes("KSBA")

bad_checksum = bytearray(good)
bad_checksum[5] ^= 0x01
check("a corrupted checksum is rejected",
      not drain(FakePort(bytes(bad_checksum))))

lowercase = shared.request_bytes("KSBA")
lowercase = bytes((lowercase[0], 0x6B)) + lowercase[2:]
check("a non-letter payload is rejected", not drain(FakePort(lowercase)))

nonzero_pause = uart.frame_bytes(uart.PAUSE_MARKER, b"\x00\x01\x00\x00")
check("a pause frame with a payload is rejected",
      not drain(FakePort(nonzero_pause)))

check("silence yields nothing", not drain(FakePort(b"")))
check("break zeros alone yield nothing", not drain(FakePort(b"\x00" * 64)))
check("0xFF noise yields nothing", not drain(FakePort(b"\xFF" * 64)))

events = drain(FakePort(b"\x4E" + b"\x00" + good + b"\x00"))
check("a stray marker ahead of a frame does not break it",
      len(events) == 1 and events[0].code == "KSBA",
      "got {}".format([getattr(e, "code", None) for e in events]))

# The regression the capture found. Both bursts in a single read must both
# come out, which needs a buffer that outlives one call.
events = drain(FakePort(captured, chunk=len(captured)))
check("two bursts in one read both decode", len(events) == CAPTURE_BURSTS,
      "got {}".format(len(events)))

# And the one-shot wrapper must not be quietly used where that matters.
one_shot = uart.wait_for_link_event(
    FakePort(captured), stop_requested=lambda: False,
    monotonic=FakeClock().monotonic, sleep=FakeClock().sleep)
check("the one-shot wrapper still returns the first frame",
      isinstance(one_shot, LocationRequest) and one_shot.code == CAPTURE_CODE)

print()
print("5. lifecycle contract")
clock = FakeClock()
try:
    uart.wait_for_link_event(FakePort(b""), stop_requested=lambda: True,
                             monotonic=clock.monotonic, sleep=clock.sleep)
    check("stop_requested raises RequestCancelled", False, "no exception")
except RequestCancelled:
    check("stop_requested raises RequestCancelled", True)

clock = FakeClock()
try:
    uart.wait_for_link_event(FakePort(b""), timeout=1.0,
                             monotonic=clock.monotonic, sleep=clock.sleep)
    check("timeout raises TimeoutError", False, "no exception")
except TimeoutError:
    check("timeout raises TimeoutError", True)

fired = []
events = drain(FakePort(good), on_activity=lambda: fired.append(1))
check("on_activity fires for a marker-led burst", len(fired) == 1,
      "fired {}".format(len(fired)))

fired = []
events = drain(FakePort(b"\x00" * 8), on_activity=lambda: fired.append(1))
check("on_activity does not fire on break zeros", not fired)

if failures:
    print("FAIL: {} of the checks above".format(len(failures)))
    for name in failures:
        print("  {}".format(name))
    sys.exit(1)
print("PASS")
