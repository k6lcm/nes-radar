#!/usr/bin/env python3
"""Wire encoder/decoder and deterministic fixtures for NES radar protocol v2."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


MARKER = 0xA5
PACKET_TYPE_SCENE = 0x01
PACKET_TYPE_IDENTITY = 0x02
PACKET_TYPE_LOCATION = 0x03
VERSION = 0x02
MAX_TARGETS = 8
RECORD_SIZE = 9
MAX_PAYLOAD = MAX_TARGETS * RECORD_SIZE
IDENTITY_RECORD_SIZE = 25
MAX_IDENTITY_PAYLOAD = MAX_TARGETS * IDENTITY_RECORD_SIZE
SCOPE_SIZE = 160

SCENE_STALE = 0x01
SCENE_TRUNCATED = 0x02
SCENE_UPSTREAM_DOWN = 0x04
SCENE_BAD_DATA = 0x08
SCENE_BAD_LOCATION = 0x10

SLOT_MASK = 0x07
TRACK_INVALID = 0x08
ALT_INVALID = 0x10
SPEED_INVALID = 0x20
ALERT = 0x40


class ProtocolError(ValueError):
    """A scene packet is malformed or fails CRC."""


@dataclass(frozen=True)
class Target:
    slot: int
    x: int
    y: int
    track: int
    altitude_hundreds: int
    speed_knots: int
    vertical_rate_hundreds: int = 0
    distance_tenths: int = 0
    track_valid: bool = True
    altitude_valid: bool = True
    speed_valid: bool = True
    alert: bool = False
    vertical_rate_valid: bool = True
    distance_valid: bool = True

    def encode(self) -> bytes:
        values = (
            ("slot", self.slot, 0, 7),
            ("x", self.x, 0, SCOPE_SIZE - 1),
            ("y", self.y, 0, SCOPE_SIZE - 1),
            ("track", self.track, 0, 255),
            ("altitude_hundreds", self.altitude_hundreds, 0, 65535),
            ("speed_knots", self.speed_knots, 0, 255),
            ("vertical_rate_hundreds", self.vertical_rate_hundreds, -99, 99),
            ("distance_tenths", self.distance_tenths, 0, 99),
        )
        for name, value, low, high in values:
            if not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer from {low} through {high}")
        flags = self.slot
        if not self.track_valid:
            flags |= TRACK_INVALID
        if not self.altitude_valid:
            flags |= ALT_INVALID
        if not self.speed_valid:
            flags |= SPEED_INVALID
        if self.alert:
            flags |= ALERT
        return bytes((
            flags,
            self.x,
            self.y,
            self.track,
            self.altitude_hundreds & 0xFF,
            (self.altitude_hundreds >> 8) & 0xFF,
            self.speed_knots,
            self.vertical_rate_hundreds & 0xFF if self.vertical_rate_valid else 0x80,
            self.distance_tenths if self.distance_valid else 0xFF,
        ))


IDENTITY_CHARACTERS = frozenset(" ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


def normalize_identity_field(value: str, width: int) -> str:
    if not isinstance(value, str):
        raise ValueError("identity fields must be strings")
    normalized = value.strip().upper()
    if len(normalized) > width:
        raise ValueError(f"identity field is longer than {width} characters")
    if any(character not in IDENTITY_CHARACTERS for character in normalized):
        raise ValueError("identity fields use only A-Z, 0-9, space, and hyphen")
    return normalized


@dataclass(frozen=True)
class Identity:
    slot: int
    callsign: str
    aircraft_type: str
    registration: str = ""
    squawk: str = ""
    category: str = ""

    def encode(self) -> bytes:
        if not isinstance(self.slot, int) or not 0 <= self.slot < MAX_TARGETS:
            raise ValueError("slot must be an integer from 0 through 7")
        callsign = normalize_identity_field(self.callsign, 8).ljust(8)
        aircraft_type = normalize_identity_field(self.aircraft_type, 4).ljust(4)
        registration = normalize_identity_field(self.registration, 6).ljust(6)
        squawk = normalize_identity_field(self.squawk, 4).ljust(4)
        category = normalize_identity_field(self.category, 2).ljust(2)
        return (
            bytes((self.slot,))
            + callsign.encode("ascii")
            + aircraft_type.encode("ascii")
            + registration.encode("ascii")
            + squawk.encode("ascii")
            + category.encode("ascii")
        )


@dataclass(frozen=True)
class IdentityPacket:
    sequence: int
    identities: tuple[Identity, ...]


@dataclass(frozen=True)
class Scene:
    sequence: int
    flags: int
    targets: tuple[Target, ...]


@dataclass(frozen=True)
class LocationResult:
    sequence: int
    code: str
    valid: bool


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def track_sector(track: int) -> int:
    """Round a 0..255 track byte to the NES marker's eight directions."""
    if not isinstance(track, int) or not 0 <= track <= 255:
        raise ValueError("track must be an integer from 0 through 255")
    return ((track + 16) & 0xFF) >> 5


def sprite_tile(target: Target) -> int:
    if not target.track_valid:
        return 0x81 + target.slot * 2
    return 1 + target.slot * 16 + track_sector(target.track) * 2


def scale_c64_coordinate(value: int) -> int:
    """Scale one pinned 0..199 C64U scope coordinate into the 0..159 NES scope."""
    if not isinstance(value, int) or not 0 <= value <= 199:
        raise ValueError("C64 coordinate must be an integer from 0 through 199")
    return round(value * (SCOPE_SIZE - 1) / 199)


def encode_scene(sequence: int, targets: Iterable[Target], flags: int = 0) -> bytes:
    if not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    if not isinstance(flags, int) or not 0 <= flags <= 0x1F:
        raise ValueError("flags must use only scene bits 0 through 4")
    target_list = tuple(targets)
    if len(target_list) > MAX_TARGETS:
        raise ValueError("a scene can contain at most eight targets")
    slots = [target.slot for target in target_list]
    if len(set(slots)) != len(slots):
        raise ValueError("target slots must be unique within a scene")
    payload = b"".join(target.encode() for target in target_list)
    body = bytes((
        PACKET_TYPE_SCENE,
        VERSION,
        sequence & 0xFF,
        flags,
        len(target_list),
        len(payload),
    )) + payload
    crc = crc16_ccitt_false(body)
    return bytes((MARKER,)) + body + crc.to_bytes(2, "big")


def encode_identity(sequence: int, identities: Iterable[Identity]) -> bytes:
    if not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    identity_list = tuple(identities)
    if len(identity_list) > MAX_TARGETS:
        raise ValueError("an identity packet can contain at most eight slots")
    slots = [identity.slot for identity in identity_list]
    if len(set(slots)) != len(slots):
        raise ValueError("identity slots must be unique within a packet")
    payload = b"".join(identity.encode() for identity in identity_list)
    body = bytes((
        PACKET_TYPE_IDENTITY,
        VERSION,
        sequence & 0xFF,
        0,
        len(identity_list),
        len(payload),
    )) + payload
    crc = crc16_ccitt_false(body)
    return bytes((MARKER,)) + body + crc.to_bytes(2, "big")


def normalize_icao(code: str) -> str:
    if not isinstance(code, str):
        raise ValueError("ICAO code must be text")
    normalized = code.strip().upper()
    if len(normalized) != 4 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("ICAO code must contain exactly four ASCII letters")
    return normalized


def encode_location_result(sequence: int, code: str, valid: bool) -> bytes:
    if not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    normalized = normalize_icao(code)
    body = bytes((
        PACKET_TYPE_LOCATION,
        VERSION,
        sequence & 0xFF,
        0 if valid else 1,
        1,
        4,
    )) + normalized.encode("ascii")
    crc = crc16_ccitt_false(body)
    return bytes((MARKER,)) + body + crc.to_bytes(2, "big")


def decode_scene(packet: bytes) -> Scene:
    if len(packet) < 9:
        raise ProtocolError("packet is shorter than the empty-scene packet")
    if packet[0] != MARKER:
        raise ProtocolError("bad marker")
    packet_type, version, sequence, flags, count, length = packet[1:7]
    if packet_type != PACKET_TYPE_SCENE:
        raise ProtocolError("unsupported packet type")
    if version != VERSION:
        raise ProtocolError("unsupported version")
    if flags & 0xE0:
        raise ProtocolError("reserved scene flag is set")
    if count > MAX_TARGETS or length != count * RECORD_SIZE:
        raise ProtocolError("count/length mismatch")
    if len(packet) != 9 + length:
        raise ProtocolError("packet size does not match length")
    expected_crc = crc16_ccitt_false(packet[1:-2])
    if int.from_bytes(packet[-2:], "big") != expected_crc:
        raise ProtocolError("bad CRC")
    targets = []
    for offset in range(7, 7 + length, RECORD_SIZE):
        record = packet[offset:offset + RECORD_SIZE]
        slot_flags, x, y, track, alt_lo, alt_hi, speed, vertical_rate, distance = record
        if slot_flags & 0x80:
            raise ProtocolError("reserved target flag is set")
        if x >= SCOPE_SIZE or y >= SCOPE_SIZE:
            raise ProtocolError("target coordinate is outside the scope")
        signed_vertical_rate = vertical_rate - 256 if vertical_rate >= 128 else vertical_rate
        if vertical_rate != 0x80 and not -99 <= signed_vertical_rate <= 99:
            raise ProtocolError("target vertical rate is outside -9900 through +9900 ft/min")
        if distance != 0xFF and distance > 99:
            raise ProtocolError("target distance is outside 0.0 through 9.9 n.m.")
        targets.append(Target(
            slot=slot_flags & SLOT_MASK,
            x=x,
            y=y,
            track=track,
            altitude_hundreds=(alt_hi << 8) | alt_lo,
            speed_knots=speed,
            vertical_rate_hundreds=signed_vertical_rate,
            distance_tenths=0 if distance == 0xFF else distance,
            track_valid=not bool(slot_flags & TRACK_INVALID),
            altitude_valid=not bool(slot_flags & ALT_INVALID),
            speed_valid=not bool(slot_flags & SPEED_INVALID),
            alert=bool(slot_flags & ALERT),
            vertical_rate_valid=vertical_rate != 0x80,
            distance_valid=distance != 0xFF,
        ))
    if len({target.slot for target in targets}) != len(targets):
        raise ProtocolError("duplicate target slot")
    return Scene(sequence, flags, tuple(targets))


def decode_identity(packet: bytes) -> IdentityPacket:
    if len(packet) < 9:
        raise ProtocolError("packet is shorter than the empty identity packet")
    if packet[0] != MARKER:
        raise ProtocolError("bad marker")
    packet_type, version, sequence, flags, count, length = packet[1:7]
    if packet_type != PACKET_TYPE_IDENTITY:
        raise ProtocolError("unsupported packet type")
    if version != VERSION:
        raise ProtocolError("unsupported version")
    if flags != 0:
        raise ProtocolError("identity flags must be zero")
    if count > MAX_TARGETS or length != count * IDENTITY_RECORD_SIZE:
        raise ProtocolError("identity count/length mismatch")
    if len(packet) != 9 + length:
        raise ProtocolError("packet size does not match length")
    expected_crc = crc16_ccitt_false(packet[1:-2])
    if int.from_bytes(packet[-2:], "big") != expected_crc:
        raise ProtocolError("bad CRC")
    identities = []
    for offset in range(7, 7 + length, IDENTITY_RECORD_SIZE):
        record = packet[offset:offset + IDENTITY_RECORD_SIZE]
        slot = record[0]
        if slot >= MAX_TARGETS:
            raise ProtocolError("identity slot is outside 0 through 7")
        try:
            raw_callsign = record[1:9].decode("ascii")
            raw_aircraft_type = record[9:13].decode("ascii")
            raw_registration = record[13:19].decode("ascii")
            raw_squawk = record[19:23].decode("ascii")
            raw_category = record[23:25].decode("ascii")
        except UnicodeDecodeError as error:
            raise ProtocolError("invalid identity character") from error
        raw_fields = raw_callsign + raw_aircraft_type + raw_registration + raw_squawk + raw_category
        if any(character not in IDENTITY_CHARACTERS for character in raw_fields):
            raise ProtocolError("invalid identity character")
        callsign = raw_callsign.rstrip()
        aircraft_type = raw_aircraft_type.rstrip()
        identities.append(Identity(
            slot,
            callsign,
            aircraft_type,
            raw_registration.rstrip(),
            raw_squawk.rstrip(),
            raw_category.rstrip(),
        ))
    if len({identity.slot for identity in identities}) != len(identities):
        raise ProtocolError("duplicate identity slot")
    return IdentityPacket(sequence, tuple(identities))


def decode_location_result(packet: bytes) -> LocationResult:
    if len(packet) != 13 or packet[0] != MARKER:
        raise ProtocolError("location-result packet size or marker is invalid")
    packet_type, version, sequence, flags, count, length = packet[1:7]
    if packet_type != PACKET_TYPE_LOCATION or version != VERSION:
        raise ProtocolError("unsupported location-result packet")
    if flags not in (0, 1) or count != 1 or length != 4:
        raise ProtocolError("invalid location-result header")
    if int.from_bytes(packet[-2:], "big") != crc16_ccitt_false(packet[1:-2]):
        raise ProtocolError("bad CRC")
    try:
        code = normalize_icao(packet[7:11].decode("ascii"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ProtocolError("invalid ICAO code") from error
    return LocationResult(sequence, code, flags == 0)


class ReceiverModel:
    """Host-side executable specification of the NES scene commit semantics."""

    def __init__(self) -> None:
        self.last_sequence: int | None = None
        self.displayed_scene: Scene | None = None
        self.identities: dict[int, Identity] = {}
        self.status = "WAIT"

    def receive(self, packet: bytes) -> str:
        if len(packet) > 1 and packet[1] == PACKET_TYPE_LOCATION:
            try:
                result = decode_location_result(packet)
            except ProtocolError:
                self.status = "ERROR"
                return "rejected"
            self.status = "WAIT" if result.valid else "BAD_LOCATION"
            return "location"
        if len(packet) > 1 and packet[1] == PACKET_TYPE_IDENTITY:
            try:
                update = decode_identity(packet)
            except ProtocolError:
                self.status = "ERROR"
                return "rejected"
            self.identities.update({identity.slot: identity for identity in update.identities})
            return "identity"
        try:
            scene = decode_scene(packet)
        except ProtocolError:
            self.status = "ERROR"
            return "rejected"
        if self.last_sequence is not None:
            if scene.sequence == self.last_sequence:
                return "duplicate"
            expected = (self.last_sequence + 1) & 0xFF
            if scene.sequence != expected:
                self.last_sequence = scene.sequence
                self.status = "ERROR"
                return "gap"
        self.last_sequence = scene.sequence
        self.displayed_scene = scene
        self.status = "STALE" if scene.flags & SCENE_STALE else "OK"
        return "accepted"


BASE_TARGETS = (
    Target(0, 64, 22, 0, 12, 95, -5, 60),
    Target(1, 90, 30, 32, 18, 110, -3, 51),
    Target(2, 106, 64, 64, 24, 125, 0, 42),
    Target(3, 90, 90, 96, 30, 140, 4, 34),
    Target(4, 64, 106, 128, 36, 155, 8, 29),
    Target(5, 38, 90, 160, 42, 170, 12, 23),
    Target(6, 22, 64, 192, 48, 185, -10, 18),
    Target(7, 38, 38, 224, 54, 200, 6, 12, alert=True),
)

BASE_IDENTITIES = (
    Identity(0, "UAL123", "B738", "N37267", "1201", "A3"),
    Identity(1, "DAL456", "A321", "N321DN", "4210", "A3"),
    Identity(2, "SWA789", "B737", "N781WN", "3274", "A3"),
    Identity(3, "ASA246", "B739", "N462AS", "1157", "A3"),
    Identity(4, "N721ZX", "C172", "N721ZX", "1200", "A1"),
    Identity(5, "FDX510", "B763", "N110FE", "4632", "A5"),
    Identity(6, "SKW8821", "E175", "N298SY", "7124", "A3"),
    Identity(7, "JBU808", "A220", "N3125J", "2035", "A3"),
)


def synthetic_targets(frame: int = 0) -> tuple[Target, ...]:
    """Eight independent, bounded track-line trajectories for hardware tests.

    Frame zero retains the exact documented fixture. Each aircraft then moves
    along its own heading with a different period and phase; direction reverses
    at the ends of the bounded synthetic track instead of all slots translating
    together.
    """
    targets = []
    for target in BASE_TARGETS:
        period = 96 + target.slot * 17
        phase = (target.slot - 3.5) * 0.25
        angle = 2 * math.pi * frame / period + phase
        distance = 10.0 * (math.sin(angle) - math.sin(phase))
        heading = target.track * 2 * math.pi / 256
        x = target.x + round(distance * math.sin(heading))
        y = target.y - round(distance * math.cos(heading))
        track = target.track if math.cos(angle) >= 0 else (target.track + 128) & 0xFF
        targets.append(Target(
            slot=target.slot,
            x=x,
            y=y,
            track=track,
            altitude_hundreds=target.altitude_hundreds,
            speed_knots=target.speed_knots,
            vertical_rate_hundreds=target.vertical_rate_hundreds,
            distance_tenths=target.distance_tenths,
            alert=target.alert,
        ))
    return tuple(targets)


def synthetic_approach_targets(frame: int = 0) -> tuple[Target, ...]:
    """Deliberately overload one scanline band for sprite-dropout testing.

    All eight marker centres remain within five scanlines while moving east on
    a short final. With the retained two-sprite 16x16 markers this exposes the
    expected earlier-than-spec overflow on real NES hardware.
    """
    targets = []
    travel = frame % 56
    for slot in range(MAX_TARGETS):
        x = 10 + ((slot * 13 + travel) % 108)
        y = 62 + (slot % 5)
        targets.append(Target(
            slot=slot,
            x=x,
            y=y,
            track=64,
            altitude_hundreds=max(1, 24 - slot * 2),
            speed_knots=135 - slot * 4,
        ))
    return tuple(targets)
