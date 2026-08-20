"""Shared types for the NES-to-host reverse channel.

The channel is 9,600 8N1 bit-banged by the ROM on OUT0 and decoded on the
host by nes_uart_request.ReverseUartReader. This module carries only the
constants, exceptions, dataclasses, and encoder helpers that the reader,
the server, and the ROM verifiers all agree on.

The file used to hold a pulse-width decoder as well, from the 0.3.1 release
that read OUT0 as FTDI CTS transitions. That decoder was retired when the
reverse-UART channel became the release path in 0.4.3; the shared types
stay here so verify_frame_bytes.py and the request-shape tests keep working
against the same source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass


REQUEST_MARKER = 0x4E
CHECK_SEED = 0xA5
REQUEST_BYTES = 6


class RequestError(ValueError):
    """A well-formed frame that fails an application-level check."""


class RequestCancelled(Exception):
    """The reader was asked to stop before a frame arrived."""


@dataclass(frozen=True)
class LocationRequest:
    code: str
    idle_state: bool


@dataclass(frozen=True)
class PauseRequest:
    idle_state: bool


def request_bytes(code: str) -> bytes:
    """The six wire bytes for a location request: marker, four letters, XOR check.

    The check is the XOR of seed $A5 with the marker and the four payload
    bytes. This is what the ROM's send_location_request emits and what the
    host's ReverseUartReader validates; verify_frame_bytes.py compares the
    ROM's cycle-accurate output against exactly this.
    """
    if len(code) != 4 or not code.isascii() or not code.isalpha() or not code.isupper():
        raise RequestError("ICAO code must be four uppercase ASCII letters")
    payload = code.encode("ascii")
    check = CHECK_SEED ^ REQUEST_MARKER
    for byte in payload:
        check ^= byte
    return bytes((REQUEST_MARKER,)) + payload + bytes((check,))
