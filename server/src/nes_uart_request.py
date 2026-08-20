"""Decode the NES reverse channel: 9,600 8N1 bit-banged by the ROM on OUT0
and read as ordinary UART data on the host's RXD.

This is the only reverse-channel decoder as of 0.4.3. Shared types
(LocationRequest, PauseRequest, RequestCancelled, marker/check constants)
live in nes_icao_request.py so verify_frame_bytes.py and the request-shape
tests keep working against one source of truth.

wait_for_link_event and ReverseUartReader are the two entry points.
LocationRequestMonitor takes a ReverseUartReader as its request_reader by
default; the one-shot wait_for_link_event wrapper exists for tools that want
to decode one frame and exit.
"""

from __future__ import annotations

import time
from typing import Callable

from nes_icao_request import (
    CHECK_SEED,
    REQUEST_MARKER,
    LocationRequest,
    PauseRequest,
    RequestCancelled,
)

PAUSE_MARKER = 0x50
FRAME_BYTES = 6
PAYLOAD_BYTES = 4
MARKERS = (REQUEST_MARKER, PAUSE_MARKER)

# The FTDI latency timer is 16 ms, so a 7 ms frame lands in one or two of its
# windows. Polling faster than that buys nothing, and polling this often keeps
# stop_requested responsive enough that shutdown is not noticeable.
POLL_SECONDS = 0.002

# A burst that has gone this long without another byte is over. Dropping it
# stops a leftover byte from pairing up with the head of the next burst to
# form a frame that was never sent. Generous against the 16 ms latency timer
# and the roughly 32 ms worst case for a frame split across two windows.
BURST_GAP_SECONDS = 0.25

# Nothing legitimate accumulates. This only bounds a wire that has started
# oscillating for reasons that have nothing to do with the ROM.
MAX_BUFFER_BYTES = 256


def frame_checksum(body: bytes) -> int:
    """XOR of marker and payload, seeded with $A5. Same as request_bytes."""
    value = CHECK_SEED
    for byte in body:
        value ^= byte
    return value


def frame_bytes(marker: int, payload: bytes) -> bytes:
    """Build a frame the way the ROM does. Used by the tests, not the server."""
    if len(payload) != PAYLOAD_BYTES:
        raise ValueError("payload must be exactly four bytes")
    body = bytes((marker,)) + payload
    return body + bytes((frame_checksum(body),))


def decode_frame(frame: bytes, idle_state: bool):
    """Return a request for a well-formed frame, or None.

    The checksum alone is a weak filter at six bytes, so the payload is checked
    too: a location payload must be four letters A-Z, which is all the ICAO
    editor can emit, and a pause payload must be the four zeros the ROM pads
    with. Together these make a false frame out of noise very unlikely without
    rejecting anything the ROM can actually send.
    """
    if len(frame) != FRAME_BYTES:
        return None
    marker = frame[0]
    if marker not in MARKERS:
        return None
    if frame_checksum(frame[:FRAME_BYTES - 1]) != frame[FRAME_BYTES - 1]:
        return None
    payload = frame[1:1 + PAYLOAD_BYTES]
    if marker == PAUSE_MARKER:
        if any(payload):
            return None
        return PauseRequest(idle_state=idle_state)
    if not all(0x41 <= byte <= 0x5A for byte in payload):
        return None
    return LocationRequest(code=payload.decode("ascii"), idle_state=idle_state)


def scan_for_frame(buffer: bytes, idle_state: bool):
    """Find the first valid frame.

    Returns (event, consumed). When nothing decodes, consumed is how many
    leading bytes can never begin a frame and may be dropped, which keeps the
    last five bytes as the possible head of a frame still arriving.
    """
    for start in range(0, max(0, len(buffer) - FRAME_BYTES + 1)):
        event = decode_frame(bytes(buffer[start:start + FRAME_BYTES]), idle_state)
        if event is not None:
            return event, start + FRAME_BYTES
    return None, max(0, len(buffer) - (FRAME_BYTES - 1))


def read_available(port) -> bytes:
    """Read what has already arrived, never blocking.

    in_waiting rather than a timed read, so the poll interval alone decides how
    fast a stop is noticed and the port's own timeout is left as the writer set
    it. The server opens the port with timeout=1, which would otherwise make
    shutdown take up to a second.
    """
    waiting = getattr(port, "in_waiting", 0)
    if callable(waiting):
        waiting = waiting()
    if not waiting:
        return b""
    return port.read(waiting)


class ReverseUartReader:
    """Stateful drop-in for wait_for_link_event.

    The buffer has to outlive a single call, and that is not a detail. One
    read can return two bursts, and the first real console capture did
    exactly that -- seventeen bytes carrying the same frame twice, the
    trailing break of the first burst shared with the leading break of the
    second. A reader that rebuilds its buffer per call returns the first
    frame and silently drops the second, which is the failure mode this
    project keeps warning itself about, since the caller sees a plausible
    answer and no error.

    LocationRequestMonitor takes any callable as request_reader, so an
    instance of this substitutes for the module-level wait_for_link_event.
    """

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.last_byte_at: float | None = None
        self.activity_reported = False

    def __call__(
        self,
        port,
        timeout: float = 0,
        *,
        idle_state: bool | None = None,
        stop_requested: Callable[[], bool] | None = None,
        on_activity: Callable[[], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> LocationRequest | PauseRequest:
        """Read RXD until a location or pause frame arrives.

        idle_state is carried through unchanged. This transport has no polarity
        state; the field is kept so LocationRequestMonitor's per-request
        bookkeeping stays the same.

        on_activity fires once per burst, and only when the burst opens with a
        marker byte. A UART frame is complete before the host sees any of it,
        so the signal is nearly redundant here; gating it on a marker keeps a
        stray break zero from aborting a scene in flight.
        """
        resolved_idle = bool(idle_state)
        started = monotonic()

        while True:
            if stop_requested is not None and stop_requested():
                raise RequestCancelled()
            now = monotonic()
            if timeout and now - started >= timeout:
                raise TimeoutError(
                    "timed out waiting for NES reverse-UART request")

            # Decode what is already held before asking for more, so residue
            # from the previous call is never stranded behind a quiet port.
            if self.buffer:
                event, consumed = scan_for_frame(self.buffer, resolved_idle)
                if event is not None:
                    del self.buffer[:consumed]
                    if not self.buffer:
                        self.activity_reported = False
                    return event
                if consumed:
                    del self.buffer[:consumed]
                if len(self.buffer) > MAX_BUFFER_BYTES:
                    del self.buffer[:len(self.buffer) - (FRAME_BYTES - 1)]

            chunk = read_available(port)
            if chunk:
                was_empty = not self.buffer
                self.buffer += chunk
                self.last_byte_at = now
                if (was_empty and not self.activity_reported
                        and self.buffer[0] in MARKERS):
                    self.activity_reported = True
                    if on_activity is not None:
                        on_activity()
                continue
            if (self.buffer and self.last_byte_at is not None
                    and now - self.last_byte_at >= BURST_GAP_SECONDS):
                self.buffer.clear()
                self.activity_reported = False

            sleep(POLL_SECONDS)


def wait_for_link_event(port, timeout: float = 0, **kwargs):
    """One-shot convenience wrapper.

    Each call builds a fresh reader, so anything left in the buffer behind the
    frame it returns is lost. That is fine for a single decode and wrong for a
    server loop. Long-lived callers want their own ReverseUartReader, which is
    what LocationRequestMonitor constructs by default.
    """
    return ReverseUartReader()(port, timeout, **kwargs)
