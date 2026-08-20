#!/usr/bin/env python3
"""Fetch live adsb.fi traffic and stream compact scenes to the NES radar ROM."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum, auto
import json
import math
import os
from pathlib import Path
import queue
import signal
import ssl
import sys
import threading
import time
from typing import Callable, Iterable, Mapping

import certifi
import serial
from serial.tools import list_ports
from c64_reference import ultimate_radar_server as C64

from scene_protocol import (
    ALT_INVALID,
    IDENTITY_CHARACTERS,
    IDENTITY_RECORD_SIZE,
    MAX_TARGETS,
    RECORD_SIZE,
    SCENE_STALE,
    SCENE_TRUNCATED,
    SCENE_UPSTREAM_DOWN,
    SPEED_INVALID,
    TRACK_INVALID,
    Identity,
    Target,
    encode_identity,
    encode_location_result,
    encode_scene,
)
from nes_icao_request import (
    LocationRequest,
    PauseRequest,
    RequestCancelled,
)
from nes_uart_request import ReverseUartReader


CERTIFICATE_BUNDLE = Path(certifi.where()).resolve()
# Python distributions do not agree on where trusted CA certificates live,
# and frozen macOS applications cannot rely on the build machine's OpenSSL
# path existing on the user's Mac. Use the bundled Certifi roots by default,
# while preserving an explicit administrator-provided SSL_CERT_FILE override.
os.environ.setdefault("SSL_CERT_FILE", str(CERTIFICATE_BUNDLE))

BAUD = 9600
APP_VERSION = "0.4.4"

# The pinned C64U Radar module identifies its own project in outgoing requests,
# so without this every adsb.fi call from NES Radar would be attributed to the
# Commodore 64 program.  Override the header here rather than in the vendored
# file, which THIRD_PARTY_NOTICES.md declares to be unmodified upstream source.
# Carries no version: the header should not need revisiting on every release.
C64.USER_AGENT = "NES-Radar (+https://github.com/k6lcm/nes-radar)"
DEFAULT_BYTE_GUARD_SECONDS = 0.005
# After every DEFAULT_CHUNK_BYTES bytes of a packet the host holds a longer
# quiet gap. It is the only moment inside a packet when the ROM can afford to
# wait for vblank and repaint, so it is what makes the controller work during
# reception instead of only between packets.
#
# The gap has to clear the ROM's worst case, which is a vblank wait of one full
# frame at 16.7 ms plus the write, near 18 ms. 30 ms leaves about 12 ms spare.
#
# The released ROM services controller work in these gaps. Running with
# --chunk-bytes 0 is unsupported: when a service commits a directional
# repaint, the following packet byte can be lost and the packet fails CRC.
# Without pending controller work the service returns quickly enough to fit
# inside the 5 ms byte guard, but do not rely on that.
DEFAULT_CHUNK_BYTES = 8
DEFAULT_CHUNK_GAP_SECONDS = 0.030
DEFAULT_POLL_SECONDS = 8.0
DEFAULT_SCENE_INTERVAL_SECONDS = 9.500
OAM_HEARTBEAT = b"\x5A"
OAM_HEARTBEAT_GAP_SECONDS = 0.025
# Shortened from 448 when chunked reception arrived, and it must stay equal to
# DISPLAY_WINDOW_FRAMES in nes/nes_radar_scope_v3.s. The window used to be the
# only time the controller did anything. Now the pad also works between chunks,
# and the budget is needed for the chunk gaps.
DISPLAY_WINDOW_FRAMES = 360
NES_FIELD_HZ = 60.0
DISPLAY_SCHEDULING_MARGIN_SECONDS = 0.050
DISPLAY_COMMIT_FRAMES = 4
DEFAULT_ICAO = "KSBA"
DEFAULT_RANGE_NM = 9.0
IDENTITY_SETTLE_SECONDS = 0.050
LEAD_IN_SECONDS = 0.020
REQUEST_SETTLE_SECONDS = 0.300
LDV_SCOPE_CENTER = 72
LDV_RADIUS_PIXELS = 71
LDV_PIXELS_PER_NM = LDV_RADIUS_PIXELS / DEFAULT_RANGE_NM
RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0, 5.0)
MONITOR_JOIN_SECONDS = 0.5
SERIAL_IO_ERRORS = (serial.SerialException, OSError)

SOURCE_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
AIRPORT_CACHE = RESOURCE_ROOT / "data" / "airports_cache.json"
LOCAL_AIRPORTS = RESOURCE_ROOT / "data" / "airports"


class SerialTransportError(Exception):
    """An expected OS/pyserial failure at a named serial boundary."""

    def __init__(self, boundary: str, error: BaseException):
        super().__init__(str(error))
        self.boundary = boundary
        self.error = error


class LocationChangeRequested(Exception):
    """The NES submitted a new ICAO code while traffic was streaming."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class LocationRequestStarted(Exception):
    """A request preamble began; pause the old stream before decoding completes."""


class NavigationPauseRequested(Exception):
    """Select requested exclusive controller ownership for the ICAO editor."""


@dataclass(frozen=True)
class MonitorFailure:
    error: BaseException


@dataclass(frozen=True)
class MonitorActivity:
    pass


@dataclass(frozen=True)
class MonitorPause:
    pass


class LocationRequestMonitor:
    """Own one cancellable reverse-UART reader and surface requests or serial failures."""

    def __init__(
        self,
        port,
        *,
        request_reader: Callable[..., object] | None = None,
        join_timeout: float = MONITOR_JOIN_SECONDS,
    ) -> None:
        self.port = port
        self.request_reader = request_reader or ReverseUartReader()
        self.join_timeout = join_timeout
        self.requests: queue.Queue[object] = queue.Queue()
        self.stop_event = threading.Event()
        self.idle_state: bool | None = None
        self.thread = threading.Thread(
            target=self._run,
            name="nes-icao-request",
            daemon=True,
        )
        self.thread.start()

    def _run(self) -> None:
        try:
            while not self.stop_event.is_set():
                event = self.request_reader(
                    self.port,
                    idle_state=self.idle_state,
                    stop_requested=self.stop_event.is_set,
                    on_activity=lambda: self.requests.put(MonitorActivity()),
                )
                if isinstance(event, LocationRequest):
                    self.idle_state = event.idle_state
                    self.requests.put(event.code)
                elif isinstance(event, PauseRequest):
                    self.idle_state = event.idle_state
                    self.requests.put(MonitorPause())
                elif isinstance(event, str):
                    # Retain support for small injected readers in offline tests.
                    self.requests.put(event)
                else:
                    raise TypeError(f"unexpected link-monitor event: {event!r}")
        except RequestCancelled:
            return
        except SERIAL_IO_ERRORS as error:
            self.requests.put(MonitorFailure(error))
        except BaseException as error:
            self.requests.put(MonitorFailure(error))

    def wait(
        self,
        timeout: float | None = None,
        *,
        include_activity: bool = False,
        include_pause: bool = False,
    ) -> str | None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                item = self.requests.get(timeout=remaining)
            except queue.Empty:
                return None
            if isinstance(item, MonitorFailure):
                if isinstance(item.error, SERIAL_IO_ERRORS):
                    raise SerialTransportError("reverse-UART read", item.error) from item.error
                raise item.error
            if isinstance(item, MonitorActivity):
                if include_activity:
                    raise LocationRequestStarted()
                continue
            if isinstance(item, MonitorPause):
                if include_pause:
                    raise NavigationPauseRequested()
                continue
            if not isinstance(item, str):
                raise TypeError(f"unexpected request-monitor item: {item!r}")
            return item

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=self.join_timeout)


class ConnectionState(Enum):
    NO_ADAPTER = auto()
    SELECTING = auto()
    OPENING = auto()
    WAITING_FOR_REQUEST = auto()
    VALIDATING = auto()
    STREAMING = auto()
    RETRYING = auto()
    STOPPED = auto()


class TransitionLogger:
    """Emit lifecycle state changes and de-duplicate persistent detail messages."""

    def __init__(self, output: Callable[..., None] = print) -> None:
        self.output = output
        self.state: ConnectionState | None = None
        self._details: dict[str, object] = {}

    def transition(self, state: ConnectionState, message: str) -> None:
        if state == self.state:
            return
        self.state = state
        self.output(message, flush=True)

    def detail(self, category: str, value: object, message: str) -> None:
        if self._details.get(category) == value:
            return
        self._details[category] = value
        self.output(message, flush=True)


@dataclass(frozen=True)
class SerialDevice:
    device: str
    description: str
    vid: int | None
    pid: int | None
    serial_number: str | None

    def label(self) -> str:
        details = [self.description]
        if self.vid is not None and self.pid is not None:
            details.append(f"USB {self.vid:04X}:{self.pid:04X}")
        if self.serial_number:
            details.append(f"serial {self.serial_number}")
        return f"{self.device} — " + "; ".join(details)


def serial_candidates(ports: Iterable[object]) -> tuple[SerialDevice, ...]:
    by_device: dict[str, SerialDevice] = {}
    for port in ports:
        device = str(port.device)
        by_device[device] = SerialDevice(
            device=device,
            description=str(getattr(port, "description", None) or "unknown serial device"),
            vid=getattr(port, "vid", None),
            pid=getattr(port, "pid", None),
            serial_number=getattr(port, "serial_number", None),
        )
    return tuple(by_device[device] for device in sorted(by_device))


def prompt_for_serial_device(
    candidates: tuple[SerialDevice, ...],
    *,
    input_func: Callable[[str], str] = input,
    output: Callable[..., None] = print,
) -> str | None:
    output("Available serial devices:", flush=True)
    for index, candidate in enumerate(candidates, 1):
        output(f"  {index}. {candidate.label()}", flush=True)
    prompt = f"Select serial device [1-{len(candidates)}]"
    if len(candidates) == 1:
        prompt += " (Enter for 1)"
    prompt += ", or R to rescan: "
    while True:
        try:
            selection = input_func(prompt).strip()
        except EOFError as error:
            raise KeyboardInterrupt() from error
        if not selection and len(candidates) == 1:
            return candidates[0].device
        if selection.lower() == "r":
            return None
        if selection in {candidate.device for candidate in candidates}:
            return selection
        try:
            index = int(selection, 10)
        except ValueError:
            index = 0
        if 1 <= index <= len(candidates):
            return candidates[index - 1].device
        output("Invalid selection; enter a listed number, exact device path, or R.", flush=True)


def choose_port(
    requested: str | None,
    port_lister: Callable[[], Iterable[object]] = list_ports.comports,
    input_func: Callable[[str], str] = input,
    output: Callable[..., None] = print,
) -> str:
    if requested:
        return requested
    while True:
        candidates = serial_candidates(port_lister())
        if not candidates:
            raise SystemExit("No serial devices were found; connect one or specify --port.")
        selected = prompt_for_serial_device(
            candidates,
            input_func=input_func,
            output=output,
        )
        if selected is not None:
            return selected


def clean_identity(value: object, width: int) -> str:
    text = str(value or "").strip().upper()
    cleaned = "".join(character if character in IDENTITY_CHARACTERS else "-" for character in text)
    return cleaned[:width]


def target_identity(target: Mapping) -> tuple[str, str, str, str, str]:
    return (
        clean_identity(target.get("callsign"), 8),
        clean_identity(target.get("type"), 4),
        clean_identity(target.get("registration"), 6),
        clean_identity(target.get("squawk"), 4),
        clean_identity(target.get("category"), 2),
    )


def target_key(target: Mapping, occurrence: int = 0) -> tuple[str, str, int]:
    callsign, aircraft_type, *_ = target_identity(target)
    return callsign, aircraft_type, occurrence


def to_nes_target(slot: int, target: Mapping) -> Target:
    bearing = math.radians(float(target["bearing"]))
    distance = float(target["distance"])
    radius = min(LDV_RADIUS_PIXELS, distance * LDV_PIXELS_PER_NM)
    x = LDV_SCOPE_CENTER + round(math.sin(bearing) * radius)
    y = LDV_SCOPE_CENTER - round(math.cos(bearing) * radius)
    track = target.get("trk")
    altitude = target.get("alt")
    speed = target.get("gs")
    vertical_rate = target.get("vertical_rate")
    return Target(
        slot=slot,
        x=max(0, min(143, x)),
        y=max(0, min(143, y)),
        track=0 if track is None else round(float(track) * 256 / 360) & 0xFF,
        altitude_hundreds=(
            0 if altitude is None else max(0, min(65535, round(float(altitude) / 100)))
        ),
        speed_knots=0 if speed is None else max(0, min(255, round(float(speed)))),
        vertical_rate_hundreds=(
            0 if vertical_rate is None
            else max(-99, min(99, round(float(vertical_rate) / 100)))
        ),
        distance_tenths=max(0, min(99, round(distance * 10))),
        track_valid=track is not None,
        altitude_valid=altitude is not None,
        speed_valid=speed is not None,
        vertical_rate_valid=vertical_rate is not None,
        distance_valid=True,
    )


@dataclass(frozen=True)
class AssignedScene:
    targets: tuple[Target, ...]
    identities: tuple[Identity, ...]
    identity_changed: bool


class SlotAllocator:
    """Assign markers 1..8 nearest-to-farthest, matching C64U Radar."""

    def __init__(self) -> None:
        self._identities: tuple[Identity, ...] | None = None

    def assign(self, targets: Iterable[Mapping]) -> AssignedScene:
        nearest = sorted(
            (
                target for target in targets
                if 0.0 <= float(target.get("distance", float("inf"))) <= 9.0
            ),
            key=lambda target: float(target.get("distance", float("inf"))),
        )[:MAX_TARGETS]
        assigned = tuple(enumerate(nearest))
        scene_targets = tuple(to_nes_target(slot, target) for slot, target in assigned)
        identity_by_slot = {
            slot: Identity(slot, *target_identity(target)) for slot, target in assigned
        }
        identities = tuple(
            identity_by_slot.get(slot, Identity(slot, "", ""))
            for slot in range(MAX_TARGETS)
        )
        changed = identities != self._identities
        self._identities = identities
        return AssignedScene(scene_targets, identities, changed)


def scene_flags(snapshot) -> int:
    flags = 0
    if snapshot.stale:
        flags |= SCENE_STALE
    if snapshot.total > MAX_TARGETS:
        flags |= SCENE_TRUNCATED
    if snapshot.error:
        flags |= SCENE_UPSTREAM_DOWN
    return flags


def resolve_airport(code: str) -> tuple[float, float]:
    code = code.strip().upper()
    if len(code) != 4 or not code.isalpha():
        raise ValueError("ICAO must contain four letters")
    local_path = LOCAL_AIRPORTS / f"{code.lower()}.json"
    if local_path.exists():
        raw = json.loads(local_path.read_text())
        return float(raw["lat"]), float(raw["lon"])
    raw = json.loads(AIRPORT_CACHE.read_text())
    try:
        latitude, longitude = raw["airports"][code]
    except KeyError as error:
        raise ValueError(f"ICAO {code} is not in the pinned airport cache") from error
    return float(latitude), float(longitude)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"NES Radar Server {APP_VERSION}")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="verify bundled code and airport data without network or serial access",
    )
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--icao")
    location.add_argument("--lat", type=float)
    location.add_argument(
        "--nes-icao",
        action="store_true",
        help="wait for the four-letter controller selection on the reverse-UART channel",
    )
    parser.add_argument("--lon", type=float)
    parser.add_argument("--range", dest="range_nm", type=float, default=DEFAULT_RANGE_NM)
    parser.add_argument("--port")
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument(
        "--scene-interval",
        type=float,
        default=DEFAULT_SCENE_INTERVAL_SECONDS,
        help="seconds between scene starts; ADS-B is still refreshed only at --poll",
    )
    parser.add_argument("--frames", type=int, default=0, help="zero streams until interrupted")
    parser.add_argument("--sequence", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--byte-guard", type=float, default=DEFAULT_BYTE_GUARD_SECONDS)
    parser.add_argument(
        "--chunk-bytes",
        type=int,
        default=DEFAULT_CHUNK_BYTES,
        help="hold a long gap after every N packet bytes so the NES can repaint; "
             "the released ROM expects 8, so change only when experimenting",
    )
    parser.add_argument(
        "--chunk-gap",
        type=float,
        default=DEFAULT_CHUNK_GAP_SECONDS,
        help="seconds of quiet at each chunk edge; must exceed one NES frame "
             "plus the repaint, so not much below 0.025",
    )
    parser.add_argument("--dry-run", action="store_true", help="fetch once without opening serial")
    parser.add_argument("--clear", action="store_true", help="blank all slots and send an empty scene")
    args = parser.parse_args(argv)
    if (args.lat is None) != (args.lon is None):
        parser.error("--lat and --lon must be supplied together")
    if args.nes_icao and args.lon is not None:
        parser.error("--nes-icao cannot be combined with --lon")
    if args.nes_icao and args.dry_run:
        parser.error("--nes-icao requires an open serial port")
    if args.icao is None and args.lat is None and not args.nes_icao:
        if args.dry_run or args.clear or args.self_test:
            args.icao = DEFAULT_ICAO
        else:
            args.nes_icao = True
    if args.frames < 0:
        parser.error("--frames must not be negative")
    if args.poll < 2.0:
        parser.error("--poll must be at least 2 seconds")
    if args.byte_guard < 0.001:
        parser.error("--byte-guard must be at least 0.001 seconds")
    if args.chunk_bytes < 0:
        parser.error("--chunk-bytes must not be negative")
    if args.chunk_bytes and args.chunk_gap < 0.025:
        parser.error(
            "--chunk-gap must be at least 0.025 seconds, since the NES spends up "
            "to one 16.7 ms frame waiting for vblank before it can repaint"
        )
    # Worst case for one cycle: an identity packet and a full scene, both paced
    # byte by byte, plus one long gap at every chunk edge, plus the NES display
    # window. The identity packet used to be left out of this, which is why the
    # old figure was optimistic.
    worst_scene_bytes = 9 + MAX_TARGETS * RECORD_SIZE
    worst_identity_bytes = 9 + MAX_TARGETS * IDENTITY_RECORD_SIZE
    packet_bytes = worst_scene_bytes + worst_identity_bytes
    chunk_edges = 0
    if args.chunk_bytes:
        chunk_edges = (worst_scene_bytes // args.chunk_bytes
                       + worst_identity_bytes // args.chunk_bytes)
    minimum_scene_interval = (
        packet_bytes * (10 / BAUD + args.byte_guard)
        + chunk_edges * (args.chunk_gap - args.byte_guard)
        + 4 / NES_FIELD_HZ
        + DISPLAY_WINDOW_FRAMES / NES_FIELD_HZ
        + DISPLAY_SCHEDULING_MARGIN_SECONDS
    )
    if args.scene_interval < minimum_scene_interval:
        parser.error(
            f"--scene-interval must be at least {minimum_scene_interval:.3f} seconds "
            "for the NES 60 Hz display window"
        )
    if not 0 <= args.sequence <= 255:
        parser.error("--sequence must be from 0 through 255")
    return args


def self_test() -> int:
    """Exercise the frozen resources and protocol without external I/O."""
    if not CERTIFICATE_BUNDLE.is_file():
        raise RuntimeError(f"bundled CA certificate file is missing: {CERTIFICATE_BUNDLE}")
    configured_bundle = os.environ.get("SSL_CERT_FILE")
    if not configured_bundle or not Path(configured_bundle).is_file():
        raise RuntimeError(f"configured CA certificate file is missing: {configured_bundle}")
    try:
        tls_context = ssl.create_default_context()
    except (OSError, ssl.SSLError) as error:
        raise RuntimeError(f"could not load trusted CA certificates: {error}") from error
    if not tls_context.get_ca_certs():
        raise RuntimeError("trusted CA certificate store is empty")
    if resolve_airport("KSBA") != (34.4262, -119.8404):
        raise RuntimeError("bundled KSBA override is invalid")
    latitude, longitude = resolve_airport("EGLL")
    if not (51.4 < latitude < 51.6 and -0.6 < longitude < -0.3):
        raise RuntimeError("bundled worldwide airport cache is invalid")
    scene = encode_scene(0x5A, ())
    if len(scene) != 9:
        raise RuntimeError("protocol self-test failed")
    print(f"NES Radar Server {APP_VERSION} self-test OK")
    return 0


def write_packet(
    port: serial.Serial,
    packet: bytes,
    byte_guard: float,
    sleep: Callable[[float], None] = time.sleep,
    *,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    chunk_gap: float = DEFAULT_CHUNK_GAP_SECONDS,
) -> None:
    """Write one packet byte by byte, holding a long gap at every chunk edge.

    Both sides count the marker as byte 1, so the gaps fall after packet bytes
    8, 16, 24 and so on. The ROM counts the same way in
    receive_byte_with_controller. No gap follows the final byte, where the
    ROM's own quiet window starts anyway.

    chunk_bytes of 0 disables the chunk gaps. The released ROM expects a
    match with its own hardcoded CHUNK_BYTES = 8; a mismatch is unsupported
    and can drop packet bytes when the ROM commits a repaint in the missing
    gap, surfacing as ERROR 3.
    """
    last = len(packet)
    for index, byte in enumerate(packet, start=1):
        try:
            port.write(bytes((byte,)))
            port.flush()
        except SERIAL_IO_ERRORS as error:
            raise SerialTransportError("serial write", error) from error
        if chunk_bytes and index % chunk_bytes == 0 and index != last:
            sleep(chunk_gap)
        else:
            sleep(byte_guard)


def control_heartbeat(sequence: int) -> bytes:
    """Retained legal no-op packet for compatibility with older v2 hosts."""
    return encode_identity(sequence, ())


def write_oam_heartbeat(
    port: serial.Serial,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Advance receive-phase sprite priority without starting a packet.

    The ROM recognizes this byte only while seeking the next packet marker.
    The following quiet gap covers its worst-case vblank wait and OAM DMA.
    """
    try:
        port.write(OAM_HEARTBEAT)
        port.flush()
    except SERIAL_IO_ERRORS as error:
        raise SerialTransportError("serial write", error) from error
    sleep(OAM_HEARTBEAT_GAP_SECONDS)


def wait_with_oam_heartbeats(
    port: serial.Serial,
    request_monitor: LocationRequestMonitor | None,
    scene_deadline: float,
    heartbeat_start: float,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait for the next scene while keeping paired markers rotating."""

    def wait_until(deadline: float) -> None:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        if request_monitor is None:
            sleep(remaining)
        else:
            wait_for_location_change(request_monitor, remaining)

    wait_until(min(heartbeat_start, scene_deadline))
    while monotonic() + OAM_HEARTBEAT_GAP_SECONDS < scene_deadline:
        wait_for_location_change(request_monitor, 0)
        write_oam_heartbeat(port, sleep)
    wait_until(scene_deadline)


def clear_packets(sequence: int) -> tuple[bytes, bytes]:
    identities = tuple(Identity(slot, "", "") for slot in range(MAX_TARGETS))
    return (
        encode_identity(sequence, identities),
        encode_scene(sequence, (), SCENE_STALE),
    )


def clear_screen(args: argparse.Namespace) -> int:
    device = choose_port(args.port)
    identity_packet, scene_packet = clear_packets(args.sequence)
    print(f"Opening {device}: clearing NES radar at sequence ${args.sequence:02X}.", flush=True)
    with serial.Serial(
        device,
        baudrate=BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1,
        rtscts=False,
        xonxoff=False,
    ) as port:
        port.break_condition = False
        port.reset_output_buffer()
        time.sleep(LEAD_IN_SECONDS)
        write_packet(port, identity_packet, args.byte_guard,
                     chunk_bytes=args.chunk_bytes, chunk_gap=args.chunk_gap)
        time.sleep(IDENTITY_SETTLE_SECONDS)
        write_packet(port, scene_packet, args.byte_guard,
                     chunk_bytes=args.chunk_bytes, chunk_gap=args.chunk_gap)
        port.break_condition = False
    print(
        f"Cleared: identity bytes={len(identity_packet)}; scene bytes={len(scene_packet)}; "
        "TX HIGH; port closed.",
        flush=True,
    )
    return 0


def snapshot_text(snapshot, assigned: AssignedScene) -> str:
    callsigns = [identity.callsign or "----" for identity in assigned.identities if identity.callsign]
    details = ", ".join(callsigns) if callsigns else "no aircraft in range"
    state = "stale" if snapshot.stale else "live"
    if snapshot.error:
        state += f", upstream error: {snapshot.error}"
    return f"{state}; nearby={snapshot.total}; shown={len(assigned.targets)}; {details}"


def wait_for_location_change(
    request_monitor: LocationRequestMonitor | None,
    timeout: float,
) -> None:
    if request_monitor is None:
        return
    requested_code = request_monitor.wait(
        timeout,
        include_activity=True,
        include_pause=True,
    )
    if requested_code is not None:
        raise LocationChangeRequested(requested_code)


def stream_scope(
    args: argparse.Namespace,
    port: serial.Serial | None,
    code: str | None = None,
    request_monitor: LocationRequestMonitor | None = None,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    global ACTIVE_SCOPE
    if code is not None or args.lat is None:
        selected = code or args.icao
        assert selected is not None
        latitude, longitude = resolve_airport(selected)
        location_label = selected.upper()
    else:
        latitude, longitude = args.lat, args.lon
        location_label = f"{latitude:.6f},{longitude:.6f}"
    ACTIVE_SCOPE = C64.Scope(latitude, longitude, args.range_nm).validated()
    config = C64.ServerConfig(
        default_scope=ACTIVE_SCOPE,
        cache_seconds=args.poll,
        stale_after_seconds=max(30.0, args.poll),
        timeout_seconds=15.0,
        ultimate_discovery=False,
    ).validate()
    service = C64.TrafficService(config)
    allocator = SlotAllocator()

    snapshot = service.refresh(ACTIVE_SCOPE, force=True)
    assigned = allocator.assign(snapshot.targets)
    print(f"Scope {location_label}: {ACTIVE_SCOPE.label()}")
    print(snapshot_text(snapshot, assigned), flush=True)
    if args.dry_run:
        return 0

    assert port is not None
    sequence = args.sequence
    frame = 0
    scene_deadline = monotonic()
    heartbeat_start = scene_deadline
    refresh_deadline = scene_deadline + args.poll
    identity_pending = assigned.identity_changed
    try:
        while args.frames == 0 or frame < args.frames:
            if frame:
                wait_with_oam_heartbeats(
                    port,
                    request_monitor,
                    scene_deadline,
                    heartbeat_start,
                    monotonic=monotonic,
                    sleep=sleep,
                )
            wait_for_location_change(request_monitor, 0)
            now = monotonic()
            if now >= refresh_deadline:
                snapshot = service.refresh(ACTIVE_SCOPE, force=True)
                assigned = allocator.assign(snapshot.targets)
                identity_pending = assigned.identity_changed
                print(snapshot_text(snapshot, assigned), flush=True)
                refresh_deadline = now + args.poll
                wait_for_location_change(request_monitor, 0)

            if identity_pending:
                identity_packet = encode_identity(sequence, assigned.identities)
                write_packet(port, identity_packet, args.byte_guard, sleep,
                             chunk_bytes=args.chunk_bytes, chunk_gap=args.chunk_gap)
                print(
                    f"Transmitting identity seq=${sequence:02X} bytes={len(identity_packet)}",
                    flush=True,
                )
                sleep(IDENTITY_SETTLE_SECONDS)
                identity_pending = False
                wait_for_location_change(request_monitor, 0)

            scene_start = monotonic()
            scene_packet = encode_scene(sequence, assigned.targets, scene_flags(snapshot))
            write_packet(port, scene_packet, args.byte_guard, sleep,
                         chunk_bytes=args.chunk_bytes, chunk_gap=args.chunk_gap)
            print(
                f"Transmitting scene {frame + 1} seq=${sequence:02X} bytes={len(scene_packet)}",
                flush=True,
            )
            heartbeat_start = (
                monotonic()
                + (DISPLAY_COMMIT_FRAMES + DISPLAY_WINDOW_FRAMES) / NES_FIELD_HZ
                + DISPLAY_SCHEDULING_MARGIN_SECONDS
            )
            sequence = (sequence + 1) & 0xFF
            frame += 1
            scene_deadline = scene_start + args.scene_interval
    finally:
        service.stop()
    return 0


@dataclass
class LifecycleDependencies:
    port_lister: Callable[[], Iterable[object]] = list_ports.comports
    serial_factory: Callable[..., object] = serial.Serial
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    monitor_factory: Callable[[object], LocationRequestMonitor] = LocationRequestMonitor
    scope_streamer: Callable[..., int] = stream_scope
    output: Callable[..., None] = print
    input: Callable[[str], str] = input


def open_serial_port(device: str, serial_factory: Callable[..., object]):
    return serial_factory(
        device,
        baudrate=BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1,
        rtscts=False,
        xonxoff=False,
    )


def clean_up_port(port, logger: TransitionLogger) -> None:
    """Best-effort idle HIGH and close; one failure cannot suppress the other."""
    try:
        port.break_condition = False
    except SERIAL_IO_ERRORS as error:
        logger.detail(
            "cleanup-idle",
            (type(error), str(error)),
            f"Could not set serial TX idle HIGH during cleanup: {error}",
        )
    try:
        port.close()
    except SERIAL_IO_ERRORS as error:
        logger.detail(
            "cleanup-close",
            (type(error), str(error)),
            f"Could not close serial port cleanly: {error}",
        )


class ConnectionLifecycle:
    """Discover, open, serve, and recover without changing the wire protocol."""

    def __init__(
        self,
        args: argparse.Namespace,
        dependencies: LifecycleDependencies | None = None,
    ) -> None:
        self.args = args
        self.dependencies = dependencies or LifecycleDependencies()
        self.logger = TransitionLogger(self.dependencies.output)
        self.retry_index = 0
        self.last_airport: str | None = None
        self.require_fresh_request = args.nes_icao
        self.selected_device: str | None = args.port

    def _retry_delay(self) -> float:
        delay = RETRY_DELAYS_SECONDS[min(self.retry_index, len(RETRY_DELAYS_SECONDS) - 1)]
        self.retry_index += 1
        return delay

    def _discover(self) -> str | None:
        if self.selected_device is not None:
            qualifier = "requested" if self.args.port else "selected"
            self.logger.transition(
                ConnectionState.OPENING,
                f"Opening {qualifier} serial port {self.selected_device}.",
            )
            return self.selected_device

        try:
            candidates = serial_candidates(self.dependencies.port_lister())
        except SERIAL_IO_ERRORS as error:
            raise SerialTransportError("adapter discovery", error) from error
        if not candidates:
            self.logger.transition(
                ConnectionState.NO_ADAPTER,
                "No serial devices detected; scanning.",
            )
            return None
        self.logger.transition(
            ConnectionState.SELECTING,
            "Serial devices detected; user selection required.",
        )
        selected = prompt_for_serial_device(
            candidates,
            input_func=self.dependencies.input,
            output=self.dependencies.output,
        )
        if selected is None:
            return None
        self.selected_device = selected
        self.logger.transition(
            ConnectionState.OPENING,
            f"Selected serial port {selected}; opening.",
        )
        return selected

    def _prepare_port(self, device: str):
        try:
            port = open_serial_port(device, self.dependencies.serial_factory)
        except SERIAL_IO_ERRORS as error:
            raise SerialTransportError("serial open", error) from error
        try:
            port.break_condition = False
            port.reset_output_buffer()
            self.dependencies.sleep(LEAD_IN_SECONDS)
        except SERIAL_IO_ERRORS as error:
            clean_up_port(port, self.logger)
            raise SerialTransportError("serial setup", error) from error
        except BaseException:
            clean_up_port(port, self.logger)
            raise
        return port

    def _wait_message(self) -> str:
        if self.last_airport is None:
            return "Serial port open; waiting for an NES airport request."
        return (
            f"Serial port open; last airport was {self.last_airport}. Waiting for a fresh request. "
            "On NES: press Select, choose the airport, then Start."
        )

    def _request_code(
        self,
        monitor: LocationRequestMonitor,
        *,
        include_pause: bool = False,
    ) -> str:
        self.logger.transition(ConnectionState.WAITING_FOR_REQUEST, self._wait_message())
        code = monitor.wait(include_pause=include_pause)
        if code is None:
            raise RuntimeError("request monitor returned without a request")
        self.logger.transition(
            ConnectionState.VALIDATING,
            f"NES airport request received: {code}",
        )
        return code

    def _validate_and_reply(
        self,
        port,
        monitor: LocationRequestMonitor,
        code: str,
    ) -> str:
        while True:
            self.dependencies.sleep(REQUEST_SETTLE_SECONDS)
            try:
                resolve_airport(code)
            except ValueError:
                write_packet(
                    port,
                    encode_location_result(self.args.sequence, code, False),
                    self.args.byte_guard,
                    self.dependencies.sleep,
                    chunk_bytes=self.args.chunk_bytes,
                    chunk_gap=self.args.chunk_gap,
                )
                self.dependencies.output(
                    f"ICAO {code} is not in the pinned worldwide cache; transmitted rejection.",
                    flush=True,
                )
                code = self._request_code(monitor)
                continue
            write_packet(
                port,
                encode_location_result(self.args.sequence, code, True),
                self.args.byte_guard,
                self.dependencies.sleep,
                chunk_bytes=self.args.chunk_bytes,
                chunk_gap=self.args.chunk_gap,
            )
            self.dependencies.output(
                f"ICAO {code} accepted; transmitted location result to the adapter.",
                flush=True,
            )
            self.last_airport = code
            return code

    def _acknowledge_pause_and_wait(
        self,
        port,
        monitor: LocationRequestMonitor,
    ) -> str:
        if self.logger.state == ConnectionState.WAITING_FOR_REQUEST:
            self.dependencies.output(
                "NES Select pause request confirmed; old scope stopped.",
                flush=True,
            )
        else:
            self.logger.transition(
                ConnectionState.WAITING_FOR_REQUEST,
                "NES Select pause request received; old scope stopped.",
            )
        self.dependencies.sleep(LEAD_IN_SECONDS)
        write_packet(
            port,
            control_heartbeat(self.args.sequence),
            self.args.byte_guard,
            self.dependencies.sleep,
            chunk_bytes=self.args.chunk_bytes,
            chunk_gap=self.args.chunk_gap,
        )
        self.dependencies.output(
            "Transmitted editor-pause acknowledgement to the adapter; "
            "waiting for a fresh airport request.",
            flush=True,
        )
        code = monitor.wait()
        if code is None:
            raise RuntimeError("request monitor returned without a request")
        self.logger.transition(
            ConnectionState.VALIDATING,
            f"NES airport request received: {code}",
        )
        return self._validate_and_reply(port, monitor, code)

    def _serve_open_port(self, port) -> int:
        monitor = self.dependencies.monitor_factory(port)
        try:
            selected_code: str | None = None
            if self.require_fresh_request:
                try:
                    code = self._request_code(monitor, include_pause=True)
                except NavigationPauseRequested:
                    selected_code = self._acknowledge_pause_and_wait(port, monitor)
                else:
                    selected_code = self._validate_and_reply(port, monitor, code)
            elif self.args.icao is not None:
                self.last_airport = self.args.icao.upper()
            while True:
                label = selected_code or self.args.icao or "configured coordinates"
                self.logger.transition(
                    ConnectionState.STREAMING,
                    f"Streaming scope {label}; writes confirm adapter transmission only.",
                )
                try:
                    return self.dependencies.scope_streamer(
                        self.args,
                        port,
                        selected_code,
                        monitor,
                        monotonic=self.dependencies.monotonic,
                        sleep=self.dependencies.sleep,
                    )
                except LocationChangeRequested as change:
                    self.logger.transition(
                        ConnectionState.VALIDATING,
                        f"NES airport request received: {change.code}",
                    )
                    selected_code = self._validate_and_reply(
                        port,
                        monitor,
                        change.code,
                    )
                except NavigationPauseRequested:
                    selected_code = self._acknowledge_pause_and_wait(port, monitor)
                except LocationRequestStarted:
                    self.logger.transition(
                        ConnectionState.WAITING_FOR_REQUEST,
                        "NES airport request activity detected; old scope paused while decoding.",
                    )
                    try:
                        code = monitor.wait(include_pause=True)
                    except NavigationPauseRequested:
                        selected_code = self._acknowledge_pause_and_wait(port, monitor)
                        continue
                    if code is None:
                        raise RuntimeError("request monitor returned without a request")
                    self.logger.transition(
                        ConnectionState.VALIDATING,
                        f"NES airport request received: {code}",
                    )
                    selected_code = self._validate_and_reply(port, monitor, code)
        finally:
            monitor.stop()

    def run(self) -> int:
        current_port = None
        opened = False
        try:
            while True:
                try:
                    device = self._discover()
                    if device is None:
                        self.dependencies.sleep(self._retry_delay())
                        continue
                    opened = False
                    current_port = self._prepare_port(device)
                    opened = True
                    self.retry_index = 0
                    result = self._serve_open_port(current_port)
                    clean_up_port(current_port, self.logger)
                    current_port = None
                    self.logger.transition(
                        ConnectionState.STOPPED,
                        "Streaming complete; serial TX idle HIGH requested and serial port closed.",
                    )
                    return result
                except (SerialTransportError, serial.SerialException) as error:
                    detail = error.error if isinstance(error, SerialTransportError) else error
                    boundary = error.boundary if isinstance(error, SerialTransportError) else "serial I/O"
                    message = (
                        f"Serial adapter disconnected during {boundary} ({detail}); retrying."
                        if opened
                        else f"Serial port open failed during {boundary} ({detail}); retrying."
                    )
                    self.logger.transition(ConnectionState.RETRYING, message)
                    if current_port is not None:
                        clean_up_port(current_port, self.logger)
                        current_port = None
                    opened = False
                    self.require_fresh_request = True
                    self.dependencies.sleep(self._retry_delay())
        except KeyboardInterrupt:
            previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                had_open_port = current_port is not None
                if current_port is not None:
                    clean_up_port(current_port, self.logger)
                    current_port = None
                message = (
                    "Shutdown requested; serial TX idle HIGH requested and serial port closed."
                    if had_open_port
                    else "Shutdown requested; no serial port was open."
                )
                self.logger.transition(
                    ConnectionState.STOPPED,
                    message,
                )
                return 0
            finally:
                signal.signal(signal.SIGINT, previous_sigint)
        finally:
            if current_port is not None:
                clean_up_port(current_port, self.logger)


def run(
    args: argparse.Namespace,
    dependencies: LifecycleDependencies | None = None,
) -> int:
    if args.dry_run:
        return stream_scope(args, None)
    return ConnectionLifecycle(args, dependencies).run()


ACTIVE_SCOPE = C64.Scope(34.4262, -119.8404, DEFAULT_RANGE_NM).validated()
_C64_EXTRACT_TARGETS = C64.extract_targets


def extract_targets_with_details(payload: Mapping, scope) -> list[dict]:
    """Preserve C64U filtering/geometry and attach raw ADS-B detail fields."""
    targets = [dict(target) for target in _C64_EXTRACT_TARGETS(payload, scope)]
    aircraft = payload.get("ac") or payload.get("aircraft") or []
    candidates: list[tuple[str, str, float, Mapping]] = []
    center = (scope.latitude, scope.longitude)
    for item in aircraft if isinstance(aircraft, list) else ():
        if not isinstance(item, Mapping):
            continue
        try:
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        callsign = str(item.get("flight") or item.get("r") or item.get("hex") or "----").strip()
        aircraft_type = str(item.get("t") or "----").strip()
        distance = C64.distance_nm(center, (latitude, longitude))
        candidates.append((callsign, aircraft_type, distance, item))

    used: set[int] = set()
    for target in targets:
        match_index = next((
            index for index, (callsign, aircraft_type, distance, _item) in enumerate(candidates)
            if index not in used
            and callsign == target["callsign"]
            and aircraft_type == target["type"]
            and abs(distance - target["distance"]) < 0.01
        ), None)
        if match_index is None:
            continue
        used.add(match_index)
        item = candidates[match_index][3]
        target["registration"] = item.get("r")
        target["squawk"] = item.get("squawk")
        target["category"] = item.get("category")
        rate = item.get("baro_rate")
        if rate is None:
            rate = item.get("geom_rate")
        try:
            target["vertical_rate"] = None if rate is None else float(rate)
        except (TypeError, ValueError):
            target["vertical_rate"] = None
    return targets


C64.extract_targets = extract_targets_with_details


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    return clear_screen(args) if args.clear else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
