#!/usr/bin/env python3
"""Decode the NES controller-port OUT0 ICAO request from an FTDI CTS line."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence


REQUEST_MARKER = 0x4E
CHECK_SEED = 0xA5
REQUEST_BYTES = 6
REQUEST_BITS = REQUEST_BYTES * 8
POLL_SECONDS = 0.001
PAUSE_ACTIVE_MIN_SECONDS = 0.085
PAUSE_ACTIVE_MAX_SECONDS = 0.130


class RequestError(ValueError):
    """A complete OUT0 request is malformed."""


class RequestCancelled(Exception):
    """Request polling was cancelled by its lifecycle owner."""


@dataclass(frozen=True)
class LocationRequest:
    code: str
    idle_state: bool


@dataclass(frozen=True)
class PauseRequest:
    idle_state: bool


def request_bytes(code: str) -> bytes:
    normalized = code.strip().upper()
    if len(normalized) != 4 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("ICAO code must contain exactly four ASCII letters")
    body = bytes((REQUEST_MARKER,)) + normalized.encode("ascii")
    checksum = CHECK_SEED
    for value in body:
        checksum ^= value
    return body + bytes((checksum,))


def request_bits(code: str) -> tuple[int, ...]:
    return tuple(
        (value >> shift) & 1
        for value in request_bytes(code)
        for shift in range(7, -1, -1)
    )


def decode_request_bits(bits: Iterable[int]) -> str:
    values = tuple(bits)
    if len(values) != REQUEST_BITS or any(bit not in (0, 1) for bit in values):
        raise RequestError(f"request must contain exactly {REQUEST_BITS} bits")
    packet = bytes(
        sum(values[offset + bit] << (7 - bit) for bit in range(8))
        for offset in range(0, REQUEST_BITS, 8)
    )
    if packet[0] != REQUEST_MARKER:
        raise RequestError("bad request marker")
    checksum = CHECK_SEED
    for value in packet[:-1]:
        checksum ^= value
    if packet[-1] != checksum:
        raise RequestError("bad request checksum")
    try:
        code = packet[1:5].decode("ascii")
    except UnicodeDecodeError as error:
        raise RequestError("ICAO request is not ASCII") from error
    if len(code) != 4 or not code.isalpha() or code != code.upper():
        raise RequestError("ICAO request must contain four uppercase letters")
    return code


def decode_request_runs(runs: Sequence[tuple[bool, float]]) -> str | None:
    """Decode completed `(CTS state, seconds)` runs; tolerate CTS inversion."""
    decoded = decode_location_request_runs(runs)
    return None if decoded is None else decoded.code


def decode_location_request_runs(
    runs: Sequence[tuple[bool, float]],
) -> LocationRequest | None:
    """Decode a request and retain the CTS idle polarity proved by its frame."""
    for start in range(max(0, len(runs) - 110), len(runs) - 2):
        gap_state, gap = runs[start]
        leader_state, leader = runs[start + 1]
        separator_state, separator = runs[start + 2]
        if gap < 0.35 or not 0.14 <= leader <= 0.30 or not 0.14 <= separator <= 0.30:
            continue
        if leader_state == gap_state or separator_state != gap_state:
            continue
        cursor = start + 3
        bits: list[int] = []
        valid = True
        while len(bits) < REQUEST_BITS:
            if cursor >= len(runs):
                valid = False
                break
            state, duration = runs[cursor]
            if state != leader_state:
                valid = False
                break
            if 0.010 <= duration <= 0.040:
                bits.append(0)
            elif 0.045 <= duration <= 0.085:
                bits.append(1)
            else:
                valid = False
                break
            cursor += 1
            if len(bits) == REQUEST_BITS:
                break
            if cursor >= len(runs):
                valid = False
                break
            state, duration = runs[cursor]
            if state != gap_state or not 0.010 <= duration <= 0.045:
                valid = False
                break
            cursor += 1
        if valid:
            try:
                return LocationRequest(decode_request_bits(bits), gap_state)
            except RequestError:
                continue
    return None


def decode_pause_runs(
    runs: Sequence[tuple[bool, float]],
    idle_state: bool | None,
) -> PauseRequest | None:
    """Decode gap/leader/separator/pause; ordinary controller runs cannot match."""
    if len(runs) < 4:
        return None
    gap_state, gap = runs[-4]
    leader_state, leader = runs[-3]
    separator_state, separator = runs[-2]
    pause_state, pause = runs[-1]
    proved_idle = gap_state if idle_state is None else idle_state
    if (
        gap_state == proved_idle
        and gap >= 0.35
        and 0.14 <= leader <= 0.30
        and leader_state != proved_idle
        and 0.14 <= separator <= 0.30
        and separator_state == proved_idle
        and PAUSE_ACTIVE_MIN_SECONDS <= pause <= PAUSE_ACTIVE_MAX_SECONDS
        and pause_state != proved_idle
    ):
        return PauseRequest(proved_idle)
    return None


def ends_with_request_preamble(runs: Sequence[tuple[bool, float]]) -> bool:
    """Return true only after the full gap/leader/separator preamble completed."""
    if len(runs) < 3:
        return False
    gap_state, gap = runs[-3]
    leader_state, leader = runs[-2]
    separator_state, separator = runs[-1]
    return (
        gap >= 0.35
        and 0.14 <= leader <= 0.30
        and 0.14 <= separator <= 0.30
        and leader_state != gap_state
        and separator_state == gap_state
    )


def wait_for_link_event(
    port,
    timeout: float = 0,
    *,
    idle_state: bool | None = None,
    stop_requested: Callable[[], bool] | None = None,
    on_activity: Callable[[], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> LocationRequest | PauseRequest:
    """Poll CTS for a location frame or a polarity-qualified pause pulse."""
    started = monotonic()
    last_state = bool(port.cts)
    run_started = started
    runs: list[tuple[bool, float]] = []
    activity_reported = False
    while True:
        if stop_requested is not None and stop_requested():
            raise RequestCancelled()
        now = monotonic()
        if timeout and now - started >= timeout:
            raise TimeoutError("timed out waiting for NES ICAO request")
        state = bool(port.cts)
        if state != last_state:
            duration = now - run_started
            runs.append((last_state, duration))
            if len(runs) > 128:
                runs = runs[-128:]
            if not activity_reported and ends_with_request_preamble(runs):
                if on_activity is not None:
                    on_activity()
                activity_reported = True
            pause = decode_pause_runs(runs, idle_state)
            if pause is not None:
                return pause
            request = decode_location_request_runs(runs)
            if request is not None:
                return request
            last_state = state
            run_started = now
        sleep(POLL_SECONDS)


def wait_for_request(
    port,
    timeout: float = 0,
    *,
    stop_requested: Callable[[], bool] | None = None,
    on_activity: Callable[[], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Compatibility wrapper for callers interested only in full ICAO frames."""
    while True:
        event = wait_for_link_event(
            port,
            timeout,
            stop_requested=stop_requested,
            on_activity=on_activity,
            monotonic=monotonic,
            sleep=sleep,
        )
        if isinstance(event, LocationRequest):
            return event.code
