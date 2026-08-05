"""Traffic-fetching subset of C64U Radar, reduced to what NES Radar uses.

Modified 2026-08-05: reduced from the upstream file to the subset NES Radar
needs. No code was rewritten, only omitted.

Upstream is the standalone ``ultimate_radar_server.py`` from C64U Radar commit
dab67473cbe487dd03b3dd5ca8d803a8572bad56, distributed under GPL-3.0. That file
is a complete C64 radar server; NES Radar only needs its adsb.fi client, so the
Commodore-specific half -- the TCP service, wire format, Ultimate-64 LAN push,
CLI, and airport-CSV loader -- is not included.

NES Radar entry points are TrafficService, ServerConfig, Scope, extract_targets
and distance_nm; everything else here exists to support them. What remains is
copied verbatim, so each definition still diffs line-for-line against upstream.
See ../../THIRD_PARTY_NOTICES.md and ../../licenses/GPL-3.0.txt.
"""

from __future__ import annotations
import json
import math
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


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


MAX_AIRCRAFT = 8


MIN_GROUND_SPEED_KT = 40.0


DEFAULT_ULTIMATE_INTERVAL_SECONDS = 10.0


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
