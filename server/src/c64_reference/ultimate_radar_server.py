#!/usr/bin/env python3
"""Standalone ADS-B bridge for C64 Ultimate Radar.

This replaces the two-process ldv_server.py -> ldv_c64_feed.py path for the
C64U. It talks to adsb.fi over HTTPS, performs filtering and projection, and
serves the existing 232-byte maximum radar wire format over plain LAN TCP.

The current C64U program connects to TCP port 6464, sends nothing, receives one
blob, and disconnects. A forward-compatible request is also accepted:

    MR2 POS 51.470748 -0.459909 9
    MR2 ICAO EGLL 9

ICAO codes are resolved from a cached copy of the public-domain OurAirports
dataset. Optional ``airports`` entries in the JSON configuration are retained
as local overrides.

Only the Python standard library is required. Supported operating systems are
macOS, Windows, Linux, Raspberry Pi OS, and other conventional Python systems.
"""

from __future__ import annotations

import argparse
import csv
import io
import ipaddress
import json
import math
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


APP_NAME = "C64 Ultimate Radar Server"
APP_VERSION = "1.3.0"

DEFAULT_LATITUDE = 0.0
DEFAULT_LONGITUDE = 0.0
DEFAULT_RANGE_NM = 9.0
DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 6464
DEFAULT_CACHE_SECONDS = 8.0
DEFAULT_STALE_AFTER_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_PEEK_SECONDS = 0.35
DEFAULT_AIRPORT_CACHE_DAYS = 30.0

ADSB_FI_BASE = "https://opendata.adsb.fi/api/v3"
USER_AGENT = "C64-Ultimate-Radar/1.2"
AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORTS_CSV_FALLBACK_URL = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
)
AIRPORT_DOWNLOAD_TIMEOUT_SECONDS = 60.0

MAX_AIRCRAFT = 8
MIN_GROUND_SPEED_KT = 40.0
SCOPE_CENTER_PX = 100
SCOPE_RADIUS_PX = 95.0
BLIP_COLOR = 0x03

MAGIC = b"LD"
WIRE_VERSION = 1
RECORD_SIZE = 28
FLAG_LOCATION_ERROR = 0x04

# C64 Ultimate REST API mailbox used to hand this server's address to a
# running radar PRG. The PRG plants the magic at $8AC0; the server refuses to
# write unless the magic is present, so it can never poke a machine that is
# not running the radar. Layout (23 bytes):
#   +0..3  magic "MR2M"   +4 version   +5 ip length
#   +6..21 ip text, NUL padded to 16   +22 checksum
MAILBOX_ADDRESS = 0x8AC0
MAILBOX_MAGIC = b"MR2M"
MAILBOX_VERSION = 1
MAILBOX_IP_CAPACITY = 16
MAILBOX_SIZE = 23
MAILBOX_CHECKSUM_SEED = 0xA5
DEFAULT_ULTIMATE_INTERVAL_SECONDS = 10.0
ULTIMATE_RESCAN_SECONDS = 60.0
ULTIMATE_HTTP_TIMEOUT_SECONDS = 2.0
ULTIMATE_PROBE_TIMEOUT_SECONDS = 0.35

NM_PER_KM = 0.539957
EARTH_RADIUS_KM = 6371.0


class ConfigurationError(ValueError):
    """Raised for invalid user configuration."""


@dataclass(frozen=True)
class Scope:
    latitude: float
    longitude: float
    range_nm: float = DEFAULT_RANGE_NM

    def validated(self) -> "Scope":
        if not math.isfinite(self.latitude) or not -90.0 <= self.latitude <= 90.0:
            raise ConfigurationError("latitude must be between -90 and 90")
        if not math.isfinite(self.longitude) or not -180.0 <= self.longitude <= 180.0:
            raise ConfigurationError("longitude must be between -180 and 180")
        if not math.isfinite(self.range_nm) or not 1.0 <= self.range_nm <= 100.0:
            raise ConfigurationError("range_nm must be between 1 and 100")
        return Scope(round(self.latitude, 6), round(self.longitude, 6), round(self.range_nm, 2))

    def label(self) -> str:
        return f"{self.latitude:.6f},{self.longitude:.6f} / {self.range_nm:g} nm"


@dataclass
class ServerConfig:
    default_scope: Scope
    bind: str = DEFAULT_BIND
    port: int = DEFAULT_PORT
    cache_seconds: float = DEFAULT_CACHE_SECONDS
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    peek_seconds: float = DEFAULT_PEEK_SECONDS
    provider_base: str = ADSB_FI_BASE
    airport_database_url: str = AIRPORTS_CSV_URL
    airport_cache_days: float = DEFAULT_AIRPORT_CACHE_DAYS
    airports: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    ultimate_discovery: bool = True
    ultimate_hosts: List[str] = field(default_factory=list)
    ultimate_interval_seconds: float = DEFAULT_ULTIMATE_INTERVAL_SECONDS
    verbose: bool = False

    def validate(self) -> "ServerConfig":
        self.default_scope = self.default_scope.validated()
        if not 0 <= self.port <= 65535:
            raise ConfigurationError("port must be between 0 and 65535")
        if self.cache_seconds < 2.0:
            raise ConfigurationError("cache_seconds must be at least 2")
        if self.stale_after_seconds < self.cache_seconds:
            raise ConfigurationError("stale_after_seconds must be at least cache_seconds")
        if self.timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be positive")
        if not 0.05 <= self.peek_seconds <= 5.0:
            raise ConfigurationError("peek_seconds must be between 0.05 and 5")
        if not self.provider_base.startswith("https://"):
            raise ConfigurationError("provider_base must be an HTTPS URL")
        if not self.airport_database_url.startswith("https://"):
            raise ConfigurationError("airport_database_url must be an HTTPS URL")
        if self.airport_cache_days < 1:
            raise ConfigurationError("airport_cache_days must be at least 1")
        if self.ultimate_interval_seconds < 3.0:
            raise ConfigurationError("ultimate_interval_seconds must be at least 3")
        clean_hosts: List[str] = []
        for host in self.ultimate_hosts:
            host = str(host).strip()
            if host and host not in clean_hosts:
                clean_hosts.append(host)
        self.ultimate_hosts = clean_hosts
        clean_airports: Dict[str, Tuple[float, float]] = {}
        for code, position in self.airports.items():
            code = str(code).upper().strip()
            if len(code) != 4 or not code.isalpha():
                raise ConfigurationError(f"invalid ICAO airport code: {code!r}")
            scope = Scope(float(position[0]), float(position[1]), self.default_scope.range_nm).validated()
            clean_airports[code] = (scope.latitude, scope.longitude)
        self.airports = clean_airports
        return self


@dataclass
class Snapshot:
    scope: Scope
    targets: List[dict]
    total: int
    good_time: Optional[float]
    attempted_monotonic: float
    last_used_monotonic: float
    stale: bool
    error: Optional[str] = None

    def age_seconds(self, now: Optional[float] = None) -> int:
        if self.good_time is None:
            return 255
        return min(255, max(0, int((time.time() if now is None else now) - self.good_time)))


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        value = float(value)
    else:
        try:
            value = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    return value if math.isfinite(value) else None


def distance_nm(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Great-circle distance in nautical miles."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    h = min(1.0, max(0.0, h))
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h)) * NM_PER_KM


def bearing_degrees(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Bearing from a to b, clockwise from true north."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def project_to_scope(bearing: float, distance: float, range_nm: float) -> Tuple[int, int]:
    radius = (distance / range_nm) * SCOPE_RADIUS_PX
    angle = math.radians(bearing)
    x = round(SCOPE_CENTER_PX + radius * math.sin(angle))
    y = round(SCOPE_CENTER_PX - radius * math.cos(angle))
    return max(0, min(199, x)), max(0, min(199, y))


def screen_codes(text: str, width: int, right: bool = False) -> bytes:
    text = str(text).upper()
    text = text.rjust(width) if right else text.ljust(width)
    result = bytearray()
    for character in text[:width]:
        value = ord(character)
        if 65 <= value <= 90:
            result.append(value - 64)
        elif 32 <= value <= 63:
            result.append(value)
        else:
            result.append(46)
    return bytes(result)


def altitude_text(altitude: Optional[float]) -> str:
    if altitude is None:
        return "--"
    if altitude >= 18000:
        return f"FL{round(altitude / 100)}"
    return str(int(round(altitude)))


def extract_targets(payload: Mapping, scope: Scope) -> List[dict]:
    aircraft = payload.get("ac") or payload.get("aircraft") or []
    if not isinstance(aircraft, list):
        return []
    center = (scope.latitude, scope.longitude)
    targets: List[dict] = []
    for item in aircraft:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("alt_baro", "")).lower() == "ground":
            continue
        speed = _number(item.get("gs"))
        if speed is not None and speed < MIN_GROUND_SPEED_KT:
            continue
        latitude = _number(item.get("lat"))
        longitude = _number(item.get("lon"))
        if latitude is None or longitude is None:
            continue
        distance = distance_nm(center, (latitude, longitude))
        if distance > scope.range_nm:
            continue
        altitude = _number(item.get("alt_baro"))
        track = _number(item.get("track"))
        if track is None:
            track = _number(item.get("true_heading"))
        callsign = item.get("flight") or item.get("r") or item.get("hex") or "----"
        aircraft_type = item.get("t") or "----"
        targets.append({
            "callsign": str(callsign).strip(),
            "type": str(aircraft_type).strip(),
            "alt": altitude,
            "gs": speed,
            "trk": track,
            "distance": distance,
            "bearing": bearing_degrees(center, (latitude, longitude)),
        })
    targets.sort(key=lambda target: target["distance"])
    return targets


def pack_record(target: Mapping, scope: Scope) -> bytes:
    x, y = project_to_scope(target["bearing"], target["distance"], scope.range_nm)
    status = 0
    if target["alt"] is None:
        status |= 0x01
    if target["gs"] is None:
        status |= 0x02
    if target["trk"] is None:
        status |= 0x04
    track_byte = 0 if target["trk"] is None else round(target["trk"] * 256 / 360) % 256
    speed_byte = 0 if target["gs"] is None else max(0, min(255, round(target["gs"])))
    speed_text = "--" if target["gs"] is None else str(round(target["gs"]))
    record = (
        bytes([x, y, BLIP_COLOR, status, track_byte, speed_byte])
        + screen_codes(target["callsign"], 8)
        + screen_codes(target["type"], 4)
        + screen_codes(altitude_text(target["alt"]), 5, right=True)
        + screen_codes(speed_text, 4, right=True)
        + b"\x00"
    )
    if len(record) != RECORD_SIZE:
        raise AssertionError(f"record is {len(record)} bytes, expected {RECORD_SIZE}")
    return record


def build_blob(snapshot: Snapshot) -> bytes:
    shown = snapshot.targets[:MAX_AIRCRAFT]
    flags = (0x01 if snapshot.stale else 0) | (0x02 if snapshot.total > MAX_AIRCRAFT else 0)
    header = MAGIC + bytes([
        WIRE_VERSION,
        flags,
        len(shown),
        min(255, snapshot.total),
        snapshot.age_seconds(),
        0,
    ])
    return header + b"".join(pack_record(target, snapshot.scope) for target in shown)


def build_location_error_blob() -> bytes:
    return MAGIC + bytes([WIRE_VERSION, FLAG_LOCATION_ERROR, 0, 0, 255, 0])


def provider_url(base: str, scope: Scope) -> str:
    provider_distance = max(1, min(250, int(math.ceil(scope.range_nm + 1.0))))
    return (
        f"{base.rstrip('/')}/lat/{scope.latitude:.6f}"
        f"/lon/{scope.longitude:.6f}/dist/{provider_distance}"
    )


class TrafficService:
    """Thread-safe adsb.fi cache, normalizer, and binary encoder."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self._snapshots: Dict[Scope, Snapshot] = {}
        self._lock = threading.RLock()
        self._upstream_lock = threading.Lock()
        self._last_upstream_monotonic = 0.0
        self._stop_event = threading.Event()
        self._refresh_thread: Optional[threading.Thread] = None

    def refresh(self, scope: Scope, force: bool = False) -> Snapshot:
        scope = scope.validated()
        now_mono = time.monotonic()
        with self._lock:
            current = self._snapshots.get(scope)
            if current and not force and now_mono - current.attempted_monotonic < self.config.cache_seconds:
                current.last_used_monotonic = now_mono
                return current

        with self._upstream_lock:
            now_mono = time.monotonic()
            with self._lock:
                current = self._snapshots.get(scope)
                if current and not force and now_mono - current.attempted_monotonic < self.config.cache_seconds:
                    current.last_used_monotonic = now_mono
                    return current

            delay = 1.05 - (now_mono - self._last_upstream_monotonic)
            if delay > 0:
                self._stop_event.wait(delay)
            attempt_mono = time.monotonic()
            self._last_upstream_monotonic = attempt_mono
            url = provider_url(self.config.provider_base, scope)
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                targets = extract_targets(payload, scope)
                snapshot = Snapshot(
                    scope=scope,
                    targets=targets,
                    total=len(targets),
                    good_time=time.time(),
                    attempted_monotonic=attempt_mono,
                    last_used_monotonic=attempt_mono,
                    stale=False,
                )
            except Exception as error:
                with self._lock:
                    old = self._snapshots.get(scope)
                if old:
                    stale = (
                        old.good_time is None
                        or time.time() - old.good_time >= self.config.stale_after_seconds
                    )
                    snapshot = Snapshot(
                        scope=scope,
                        targets=old.targets,
                        total=old.total,
                        good_time=old.good_time,
                        attempted_monotonic=attempt_mono,
                        last_used_monotonic=attempt_mono,
                        stale=stale,
                        error=str(error),
                    )
                else:
                    snapshot = Snapshot(
                        scope=scope,
                        targets=[],
                        total=0,
                        good_time=None,
                        attempted_monotonic=attempt_mono,
                        last_used_monotonic=attempt_mono,
                        stale=True,
                        error=str(error),
                    )
            with self._lock:
                self._snapshots[scope] = snapshot
            return snapshot

    def get(self, scope: Scope) -> Snapshot:
        scope = scope.validated()
        with self._lock:
            snapshot = self._snapshots.get(scope)
            if snapshot:
                snapshot.last_used_monotonic = time.monotonic()
                return snapshot
        return self.refresh(scope, force=True)

    def start_background_refresh(self) -> None:
        if self._refresh_thread and self._refresh_thread.is_alive():
            return

        def worker() -> None:
            while not self._stop_event.wait(1.0):
                now = time.monotonic()
                with self._lock:
                    active = [
                        snapshot.scope
                        for snapshot in self._snapshots.values()
                        if now - snapshot.last_used_monotonic < 600.0
                        and now - snapshot.attempted_monotonic >= self.config.cache_seconds
                    ]
                if self.config.default_scope not in active:
                    with self._lock:
                        default = self._snapshots.get(self.config.default_scope)
                    if default is None or now - default.attempted_monotonic >= self.config.cache_seconds:
                        active.insert(0, self.config.default_scope)
                for scope in active:
                    if self._stop_event.is_set():
                        return
                    self.refresh(scope)

        self._refresh_thread = threading.Thread(target=worker, name="adsb-refresh", daemon=True)
        self._refresh_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=2.0)

    def status(self) -> List[dict]:
        with self._lock:
            snapshots = list(self._snapshots.values())
        return [
            {
                "center": snapshot.scope.label(),
                "targets": snapshot.total,
                "shown": min(MAX_AIRCRAFT, snapshot.total),
                "age_seconds": snapshot.age_seconds(),
                "stale": snapshot.stale,
                "error": snapshot.error,
            }
            for snapshot in snapshots
        ]


def parse_location_command(
    data: bytes,
    default_scope: Scope,
    airports: Mapping[str, Tuple[float, float]],
) -> Tuple[Scope, Optional[str]]:
    if not data:
        return default_scope, None
    try:
        line = data.splitlines()[0].decode("ascii", "strict").strip()
    except (UnicodeDecodeError, IndexError):
        return default_scope, "request was not ASCII"
    parts = line.split()
    if not parts or parts[0].upper() != "MR2":
        return default_scope, "unknown request; using default center"
    try:
        mode = parts[1].upper()
        if mode == "POS" and len(parts) in (4, 5):
            range_nm = float(parts[4]) if len(parts) == 5 else default_scope.range_nm
            return Scope(float(parts[2]), float(parts[3]), range_nm).validated(), None
        if mode == "ICAO" and len(parts) in (3, 4):
            code = parts[2].upper()
            if code not in airports:
                return default_scope, f"ICAO {code} is not in the configured airport table"
            range_nm = float(parts[3]) if len(parts) == 4 else default_scope.range_nm
            latitude, longitude = airports[code]
            return Scope(latitude, longitude, range_nm).validated(), None
    except (ValueError, ConfigurationError) as error:
        return default_scope, str(error)
    return default_scope, "invalid MR2 request; using default center"


def scope_from_query(
    query: Mapping[str, Sequence[str]],
    default_scope: Scope,
    airports: Mapping[str, Tuple[float, float]],
) -> Scope:
    range_nm = float(query.get("range", [str(default_scope.range_nm)])[0])
    if "icao" in query:
        code = query["icao"][0].upper()
        if code not in airports:
            raise ConfigurationError(f"ICAO {code} is not in the configured airport table")
        latitude, longitude = airports[code]
        return Scope(latitude, longitude, range_nm).validated()
    if "lat" in query or "lon" in query:
        if "lat" not in query or "lon" not in query:
            raise ConfigurationError("lat and lon must be supplied together")
        return Scope(float(query["lat"][0]), float(query["lon"][0]), range_nm).validated()
    return Scope(default_scope.latitude, default_scope.longitude, range_nm).validated()


def text_view(snapshot: Snapshot) -> str:
    lines = [
        f"{APP_NAME} {APP_VERSION}",
        f"center {snapshot.scope.label()}",
        f"targets {min(snapshot.total, MAX_AIRCRAFT)} shown / {snapshot.total} in range"
        f"{'  [STALE]' if snapshot.stale else ''}   age {snapshot.age_seconds()}s",
        f"{'#':1} {'CALLSIGN':8} {'TYPE':4} {'ALT':>5} {'GS':>4} {'TRK':>3}  BRG/DIST      (X,Y)",
    ]
    for index, target in enumerate(snapshot.targets[:MAX_AIRCRAFT], 1):
        x, y = project_to_scope(target["bearing"], target["distance"], snapshot.scope.range_nm)
        track = "---" if target["trk"] is None else f"{round(target['trk']) % 360:03d}"
        speed = "---" if target["gs"] is None else f"{round(target['gs']):3d}"
        lines.append(
            f"{index} {target['callsign']:8.8} {target['type']:4.4} "
            f"{altitude_text(target['alt']):>5} {speed:>4} {track}  "
            f"{round(target['bearing']):03d}/{target['distance']:4.1f}nm   ({x:3d},{y:3d})"
        )
    if snapshot.error:
        lines.append(f"last error: {snapshot.error}")
    return "\n".join(lines) + "\n"


def lan_ipv4_addresses() -> List[str]:
    addresses: List[str] = []

    def add(address: str) -> None:
        try:
            parsed = ipaddress.ip_address(address)
            usable = (
                parsed.version == 4
                and not parsed.is_loopback
                and not parsed.is_unspecified
                and not parsed.is_link_local
                and not parsed.is_multicast
            )
        except ValueError:
            usable = False
        if usable and address not in addresses:
            addresses.append(address)

    # The address selected by the operating system's default route is usually
    # the one another LAN device should use, so report it first.
    for destination in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(destination)
                add(probe.getsockname()[0])
            finally:
                probe.close()
        except OSError:
            pass
    try:
        discovered = {
            result[4][0]
            for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
        }
        for address in sorted(discovered, key=lambda value: (not ipaddress.ip_address(value).is_private, value)):
            add(address)
    except OSError:
        pass
    return addresses


def mailbox_checksum(ip_bytes: bytes) -> int:
    checksum = MAILBOX_CHECKSUM_SEED ^ len(ip_bytes)
    for value in ip_bytes:
        checksum ^= value
    return checksum


def build_mailbox_payload(ip: str) -> bytes:
    """Bytes for mailbox offsets +5..+22: length, padded ip, checksum."""
    ip_bytes = ip.encode("ascii")
    if not 7 <= len(ip_bytes) <= 15:
        raise ValueError(f"not a usable dotted IPv4 address: {ip!r}")
    padded = ip_bytes.ljust(MAILBOX_IP_CAPACITY, b"\x00")
    return bytes([len(ip_bytes)]) + padded + bytes([mailbox_checksum(ip_bytes)])


def parse_mailbox(blob: bytes) -> Tuple[bool, Optional[str]]:
    """Return (radar_running, current_ip_or_None) for a mailbox dump."""
    if len(blob) < MAILBOX_SIZE or blob[:4] != MAILBOX_MAGIC:
        return False, None
    if blob[4] != MAILBOX_VERSION:
        return False, None
    length = blob[5]
    if not 7 <= length <= 15:
        return True, None
    ip_bytes = blob[6:6 + length]
    if blob[22] != mailbox_checksum(ip_bytes):
        return True, None
    try:
        text = ip_bytes.decode("ascii")
        ipaddress.IPv4Address(text)
    except (UnicodeDecodeError, ValueError):
        return True, None
    return True, text


class UltimatePusher:
    """Find C64 Ultimate machines and hand them this server's address.

    Uses the Ultimate's REST API (GET /v1/version to identify, machine:readmem
    and machine:writemem for the $8AC0 mailbox). Candidates come from the
    configured host list plus a threaded port-80 sweep of each local /24.
    """

    def __init__(self, config: "ServerConfig", lan_addresses: Sequence[str]):
        self.config = config
        self.lan_addresses = list(lan_addresses)
        self._known: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_scan_monotonic = 0.0

    # -- HTTP primitives ----------------------------------------------------

    def _api(self, host: str, path: str, method: str = "GET") -> bytes:
        request = urllib.request.Request(
            f"http://{host}{path}",
            method=method,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=ULTIMATE_HTTP_TIMEOUT_SECONDS) as response:
            return response.read()

    def identify(self, host: str) -> Optional[dict]:
        try:
            payload = json.loads(self._api(host, "/v1/version").decode("utf-8", "replace"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def read_mailbox(self, host: str) -> Tuple[bool, Optional[str]]:
        blob = self._api(
            host,
            f"/v1/machine:readmem?address={MAILBOX_ADDRESS:04x}&length={MAILBOX_SIZE}",
        )
        return parse_mailbox(blob)

    def write_mailbox(self, host: str, ip: str) -> None:
        payload = build_mailbox_payload(ip)
        self._api(
            host,
            f"/v1/machine:writemem?address={MAILBOX_ADDRESS + 5:04x}&data={payload.hex()}",
            method="PUT",
        )

    # -- discovery ----------------------------------------------------------

    def _probe(self, host: str) -> Optional[str]:
        try:
            with socket.create_connection((host, 80), timeout=ULTIMATE_PROBE_TIMEOUT_SECONDS):
                pass
        except OSError:
            return None
        return host if self.identify(host) is not None else None

    def scan(self) -> List[str]:
        candidates: List[str] = list(self.config.ultimate_hosts)
        seen = set(candidates)
        if not candidates:  # no explicit hosts: sweep each local /24
            for address in self.lan_addresses:
                try:
                    network = ipaddress.ip_network(f"{address}/24", strict=False)
                except ValueError:
                    continue
                for host in network.hosts():
                    text = str(host)
                    if text != address and text not in seen:
                        seen.add(text)
                        candidates.append(text)
        found: List[str] = []
        with ThreadPoolExecutor(max_workers=32) as pool:
            for host in pool.map(self._probe, candidates):
                if host:
                    found.append(host)
        return found

    def server_ip_for(self, host: str) -> Optional[str]:
        """Pick the local address a given Ultimate should connect back to."""
        try:
            target = ipaddress.ip_address(host)
        except ValueError:
            target = None
        if target is not None:
            for address in self.lan_addresses:
                try:
                    network = ipaddress.ip_network(f"{address}/24", strict=False)
                except ValueError:
                    continue
                if target in network:
                    return address
        return self.lan_addresses[0] if self.lan_addresses else None

    # -- push loop ----------------------------------------------------------

    def poll_host(self, host: str) -> Optional[str]:
        """One mailbox check/push. Returns a log message or None."""
        my_ip = self.server_ip_for(host)
        if my_ip is None:
            return None
        running, current = self.read_mailbox(host)
        if not running:
            return None
        if current == my_ip:
            return None
        self.write_mailbox(host, my_ip)
        return f"C64U at {host}: radar detected, sent server address {my_ip}"

    def _tick(self) -> None:
        with self._lock:
            known = list(self._known)
        now = time.monotonic()
        if not known and now - self._last_scan_monotonic >= ULTIMATE_RESCAN_SECONDS:
            self._last_scan_monotonic = now
            for host in self.scan():
                with self._lock:
                    self._known[host] = {"found_time": time.time(), "pushed_ip": None}
                print(f"C64U found at {host} (Ultimate API)", flush=True)
            with self._lock:
                known = list(self._known)
        for host in known:
            try:
                message = self.poll_host(host)
            except Exception as error:
                if self.config.verbose:
                    print(f"C64U at {host}: {error}", flush=True)
                with self._lock:
                    self._known.pop(host, None)
                continue
            if message:
                with self._lock:
                    if host in self._known:
                        self._known[host]["pushed_ip"] = self.server_ip_for(host)
                        self._known[host]["pushed_time"] = time.time()
                print(message, flush=True)

    def start(self) -> None:
        if not self.config.ultimate_discovery:
            return
        if self._thread and self._thread.is_alive():
            return
        self._last_scan_monotonic = -ULTIMATE_RESCAN_SECONDS

        def worker() -> None:
            while True:
                self._tick()
                if self._stop_event.wait(self.config.ultimate_interval_seconds):
                    return

        self._thread = threading.Thread(target=worker, name="ultimate-push", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def status(self) -> List[dict]:
        with self._lock:
            return [
                {"host": host, **details}
                for host, details in sorted(self._known.items())
            ]


class RadarRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        self.request.settimeout(server.config.peek_seconds)
        data = b""
        try:
            data = self.request.recv(1024)
        except (socket.timeout, ConnectionError, OSError):
            pass

        try:
            if data.startswith(b"GET "):
                self._handle_http(data)
            else:
                scope, warning = parse_location_command(data, server.config.default_scope, server.config.airports)
                if warning and server.config.verbose:
                    print(f"{self.client_address[0]}: {warning}", flush=True)
                if warning:
                    self.request.sendall(build_location_error_blob())
                    return
                snapshot = server.traffic.get(scope)
                self.request.sendall(build_blob(snapshot))
        except (BrokenPipeError, ConnectionError, OSError) as error:
            if server.config.verbose:
                print(f"{self.client_address[0]}: {error}", flush=True)

    def _handle_http(self, data: bytes) -> None:
        try:
            line = data.splitlines()[0].decode("ascii", "replace")
            target = line.split()[1]
            parsed = urllib.parse.urlsplit(target)
            query = urllib.parse.parse_qs(parsed.query)
            scope = scope_from_query(query, self.server.config.default_scope, self.server.config.airports)
        except (IndexError, ValueError, ConfigurationError) as error:
            self._send_http(400, (str(error) + "\n").encode(), "text/plain; charset=utf-8")
            return

        if parsed.path in ("/traffic", "/traffic.bin"):
            self._send_http(200, build_blob(self.server.traffic.get(scope)), "application/octet-stream")
        elif parsed.path == "/traffic.txt":
            self._send_http(200, text_view(self.server.traffic.get(scope)).encode(), "text/plain; charset=utf-8")
        elif parsed.path == "/status.json":
            body = json.dumps({
                "application": APP_NAME,
                "version": APP_VERSION,
                "addresses": self.server.lan_addresses,
                "port": self.server.server_address[1],
                "default_scope": self.server.config.default_scope.label(),
                "icao_airports": len(self.server.config.airports),
                "stale_after_seconds": self.server.config.stale_after_seconds,
                "provider": self.server.config.provider_base,
                "uptime_seconds": int(time.time() - self.server.started_time),
                "caches": self.server.traffic.status(),
                "ultimates": pusher.status() if (pusher := getattr(self.server, "pusher", None)) else [],
            }, indent=2).encode()
            self._send_http(200, body, "application/json")
        elif parsed.path in ("/", "/index.txt"):
            addresses = "\n".join(
                f"  Server: {address}:{self.server.server_address[1]}"
                for address in self.server.lan_addresses
            ) or "  No LAN IPv4 address found"
            body = (
                f"{APP_NAME} {APP_VERSION}\n\n"
                f"{addresses}\n"
                f"  Default: {self.server.config.default_scope.label()}\n"
                f"  Provider: adsb.fi\n\n"
                f"Debug:\n"
                f"  /traffic.txt\n"
                f"  /traffic\n"
                f"  /status.json\n"
            ).encode()
            self._send_http(200, body, "text/plain; charset=utf-8")
        else:
            self._send_http(404, b"not found\n", "text/plain; charset=utf-8")

    def _send_http(self, status: int, body: bytes, content_type: str) -> None:
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found"}.get(status, "")
        header = (
            f"HTTP/1.0 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        self.request.sendall(header + body)


class RadarServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: Tuple[str, int], config: ServerConfig, traffic: TrafficService):
        self.config = config
        self.traffic = traffic
        self.lan_addresses = lan_ipv4_addresses()
        self.started_time = time.time()
        self.pusher: Optional[UltimatePusher] = None
        super().__init__(address, RadarRequestHandler)


def _load_json_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{path} must contain a JSON object")
    return value


def _airport_table(value) -> Dict[str, Tuple[float, float]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigurationError("airports must be a JSON object")
    result = {}
    for code, position in value.items():
        if not isinstance(position, Sequence) or isinstance(position, (str, bytes)) or len(position) != 2:
            raise ConfigurationError(f"airport {code} must be [latitude, longitude]")
        result[str(code)] = (float(position[0]), float(position[1]))
    return result


def parse_airports_csv(data: bytes) -> Dict[str, Tuple[float, float]]:
    """Extract four-letter ICAO coordinates from the OurAirports CSV."""
    result: Dict[str, Tuple[float, float]] = {}
    text = io.StringIO(data.decode("utf-8-sig"))
    for row in csv.DictReader(text):
        code = (row.get("icao_code") or "").strip().upper()
        if len(code) != 4 or not code.isalpha():
            continue
        try:
            scope = Scope(
                float(row["latitude_deg"]),
                float(row["longitude_deg"]),
                DEFAULT_RANGE_NM,
            ).validated()
        except (KeyError, TypeError, ValueError, ConfigurationError):
            continue
        result[code] = (scope.latitude, scope.longitude)
    return result


def load_airport_database(
    config: ServerConfig,
    cache_path: Optional[Path] = None,
) -> str:
    """Load cached ICAO coordinates and refresh them periodically."""
    cache_path = cache_path or Path(__file__).with_name("airports_cache.json")
    configured = dict(config.airports)
    cached: Dict[str, Tuple[float, float]] = {}
    updated = 0.0
    try:
        raw = _load_json_config(cache_path)
        cached = _airport_table(raw.get("airports"))
        updated = float(raw.get("updated", 0))
    except (ConfigurationError, TypeError, ValueError):
        cached = {}

    max_age = config.airport_cache_days * 86400.0
    needs_refresh = not cached or time.time() - updated >= max_age
    warning: Optional[str] = None
    if needs_refresh:
        urls = [config.airport_database_url]
        if AIRPORTS_CSV_FALLBACK_URL not in urls:
            urls.append(AIRPORTS_CSV_FALLBACK_URL)
        errors = []
        for url in urls:
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
                )
                with urllib.request.urlopen(
                    request,
                    timeout=max(config.timeout_seconds, AIRPORT_DOWNLOAD_TIMEOUT_SECONDS),
                ) as response:
                    downloaded = parse_airports_csv(response.read())
                if len(downloaded) < 1000:
                    raise ConfigurationError("download did not contain a full ICAO table")
                cached = downloaded
                updated = time.time()
                try:
                    cache_path.write_text(
                        json.dumps({"updated": updated, "airports": cached}, separators=(",", ":")),
                        encoding="utf-8",
                    )
                except OSError as error:
                    warning = f"airport cache could not be saved: {error}"
                break
            except Exception as error:
                errors.append(f"{url}: {error}")
        else:
            warning = "airport database refresh failed: " + " | ".join(errors)

    cached.update(configured)  # local configuration always wins
    config.airports = cached
    if len(cached) < 1000:
        message = f"ICAO WARNING: worldwide database unavailable; only {len(cached)} fallback airport(s)"
    else:
        message = f"ICAO database: {len(cached):,} airport(s) available"
    return f"{message}; {warning}" if warning else message


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    default_config = Path(__file__).with_suffix(".json")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config, help=f"JSON configuration file (default: {default_config.name})")
    parser.add_argument("--lat", type=float, help="override default latitude")
    parser.add_argument("--lon", type=float, help="override default longitude")
    parser.add_argument("--range", dest="range_nm", type=float, help="override scope range in nautical miles")
    parser.add_argument("--bind", help="address to bind, normally 0.0.0.0")
    parser.add_argument("--port", type=int, help="TCP port, normally 6464")
    parser.add_argument("--ultimate-host", action="append", help="C64 Ultimate address to push the server IP to (repeatable; skips LAN scan)")
    parser.add_argument("--no-ultimate", action="store_true", help="disable C64 Ultimate discovery/push")
    parser.add_argument("--verbose", action="store_true", help="print client warnings and connection errors")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    return parser.parse_args(argv)


def configuration_from_arguments(arguments: argparse.Namespace) -> ServerConfig:
    raw = _load_json_config(arguments.config)
    latitude = arguments.lat if arguments.lat is not None else float(raw.get("latitude", DEFAULT_LATITUDE))
    longitude = arguments.lon if arguments.lon is not None else float(raw.get("longitude", DEFAULT_LONGITUDE))
    range_nm = arguments.range_nm if arguments.range_nm is not None else float(raw.get("range_nm", DEFAULT_RANGE_NM))
    config = ServerConfig(
        default_scope=Scope(latitude, longitude, range_nm),
        bind=arguments.bind if arguments.bind is not None else str(raw.get("bind", DEFAULT_BIND)),
        port=arguments.port if arguments.port is not None else int(raw.get("port", DEFAULT_PORT)),
        cache_seconds=float(raw.get("cache_seconds", DEFAULT_CACHE_SECONDS)),
        stale_after_seconds=float(raw.get("stale_after_seconds", DEFAULT_STALE_AFTER_SECONDS)),
        timeout_seconds=float(raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        peek_seconds=float(raw.get("peek_seconds", DEFAULT_PEEK_SECONDS)),
        provider_base=str(raw.get("provider_base", ADSB_FI_BASE)),
        airport_database_url=str(raw.get("airport_database_url", AIRPORTS_CSV_URL)),
        airport_cache_days=float(raw.get("airport_cache_days", DEFAULT_AIRPORT_CACHE_DAYS)),
        airports=_airport_table(raw.get("airports")),
        ultimate_discovery=(
            not arguments.no_ultimate and bool(raw.get("ultimate_discovery", True))
        ),
        ultimate_hosts=(
            list(arguments.ultimate_host)
            if arguments.ultimate_host
            else [str(host) for host in raw.get("ultimate_hosts", [])]
        ),
        ultimate_interval_seconds=float(
            raw.get("ultimate_interval_seconds", DEFAULT_ULTIMATE_INTERVAL_SECONDS)
        ),
        verbose=arguments.verbose or bool(raw.get("verbose", False)),
    )
    return config.validate()


def run(config: ServerConfig) -> int:
    print(f"{APP_NAME} {APP_VERSION}")
    print("-" * 46)
    print("Loading ICAO airport data...", flush=True)
    print(load_airport_database(config), flush=True)
    traffic = TrafficService(config)
    try:
        server = RadarServer((config.bind, config.port), config, traffic)
    except OSError as error:
        print(f"Cannot listen on {config.bind}:{config.port}: {error}", file=sys.stderr)
        return 2

    actual_port = server.server_address[1]
    if server.lan_addresses:
        for address in server.lan_addresses:
            print(f"Server address: {address}:{actual_port}")
            print(f"Status page:   http://{address}:{actual_port}/")
    else:
        print("LAN address:    not detected; check this computer's network settings")
    print(f"Provider:      {provider_url(config.provider_base, config.default_scope)}")
    print("Warming the traffic cache...", flush=True)
    first = traffic.refresh(config.default_scope, force=True)
    if first.stale:
        print(f"Cache warning:  {first.error or 'no upstream data'}")
        print("The server will keep retrying and will serve a stale/empty blob meanwhile.")
    else:
        print("Traffic cache ready. Target totals update continuously.")
    print("Press Ctrl+C to stop.\n", flush=True)
    traffic.start_background_refresh()

    pusher = UltimatePusher(config, server.lan_addresses)
    server.pusher = pusher
    if config.ultimate_discovery:
        if config.ultimate_hosts:
            print(f"C64U push:     using configured host(s) {', '.join(config.ultimate_hosts)}")
        else:
            print("C64U push:     scanning the LAN for the Ultimate API")
        pusher.start()
    else:
        print("C64U push:     disabled")

    try:
        with server:
            server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.shutdown()
        traffic.stop()
        pusher.stop()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        config = configuration_from_arguments(parse_arguments(argv))
    except (ConfigurationError, ValueError, TypeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
