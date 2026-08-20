#!/usr/bin/env python3
"""Offline timing checks for receive-phase OAM heartbeats."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import nes_radar_server as server  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakePort:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.flushes = 0

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        self.flushes += 1


def check_window(start: float, deadline: float, expected: int) -> None:
    clock = FakeClock()
    port = FakePort()
    server.wait_with_oam_heartbeats(
        port,
        None,
        deadline,
        start,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert clock.now == deadline, (clock.now, deadline)
    assert port.writes == [server.OAM_HEARTBEAT] * expected, port.writes
    assert port.flushes == expected, port.flushes


def main() -> int:
    assert server.OAM_HEARTBEAT != b"\xA5"
    check_window(0.900, 1.000, 3)
    check_window(1.000, 1.000, 0)
    check_window(1.100, 1.000, 0)
    print("display heartbeat timing PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
