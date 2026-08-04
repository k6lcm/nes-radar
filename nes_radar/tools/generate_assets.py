#!/usr/bin/env python3
"""Generate deterministic CHR, nametable, include, and preview assets."""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path


WIDTH = 256
HEIGHT = 240

# The scene protocol projects targets into a fixed 160x160 space. The scope
# renders that space one-to-one at SCOPE_ORIGIN. The NES has less horizontal
# but more vertical resolution than the C64, so the scope is centered above a
# two-column aircraft list instead of being squeezed beside one tall column.
SCOPE_ORIGIN_X = 48
SCOPE_ORIGIN_Y = 8
SCOPE_CENTER_X = SCOPE_ORIGIN_X + 80
SCOPE_CENTER_Y = SCOPE_ORIGIN_Y + 80

# The pinned C64U scope is 200 px across with rings at 32/63/96. The host
# scales its coordinates by 159/199, so the rings scale with them.
C64_SCOPE_HALF = 100
C64_RING_RADII = (32, 63, 96)
RING_RADII = tuple(round(r * 159 / 199) for r in C64_RING_RADII)

# Sprite pattern geometry: the marker center sits at local (3, 7) inside the
# 8x16 pattern. OAM Y displays one scanline late, so:
#   OAM X = scene X + SCOPE_ORIGIN_X - 3
#   OAM Y = scene Y + SCOPE_ORIGIN_Y - 1 - 7
SPRITE_OFFSET_X = SCOPE_ORIGIN_X - 3
SPRITE_OFFSET_Y = SCOPE_ORIGIN_Y - 8

# Six-tile side gutters carry the title and link diagnostics. Rows 21..28 are
# two columns of four aircraft, two rows each. Each aircraft column is fourteen
# tiles wide and remains outside the outer eight-pixel overscan margin:
#
#   [N]CALLSIGN TYPE
#      ALT     SPD
TITLE_COL = 1
TITLE_ROW = 2
LINK_COL = 26
LINK_ROW = 2
COUNT_ROW = 3
ERROR_ROW = 4
STATUS_COL = 30
STATUS_ROW = LINK_ROW
COUNT_COL = 30
ERROR_COL = 30
PANEL_LEFT_COL = 1
PANEL_RIGHT_COL = 17
PANEL_FIRST_ROW = 21
PANEL_CALLSIGN_OFFSET = 1
PANEL_ALT_OFFSET = 3
PANEL_TYPE_OFFSET = 10
PANEL_SPEED_OFFSET = 11

STARTUP_CODE_COL = 14
STARTUP_CODE_ROW = 12
STARTUP_MESSAGE_COL = 8
STARTUP_MESSAGE_ROW = 15
STARTUP_MESSAGE_WIDTH = 16
DEFAULT_ICAO = "KSBA"


def panel_origin(slot: int) -> tuple[int, int]:
    """Nametable column/row for stable slot 0..7."""
    return (
        PANEL_LEFT_COL if slot < 4 else PANEL_RIGHT_COL,
        PANEL_FIRST_ROW + (slot & 3) * 2,
    )


# Five columns by seven rows. Rows use bit 4 as the leftmost pixel.
FONT = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "-": (0, 0, 0, 0b11111, 0, 0, 0),
    ".": (0, 0, 0, 0, 0, 0b00110, 0b00110),
    "/": (0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0, 0),
    "0": (0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "2": (0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111),
    "3": (0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110),
    "4": (0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010),
    "5": (0b11111, 0b10000, 0b10000, 0b11110, 0b00001, 0b00001, 0b11110),
    "6": (0b01110, 0b10000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110),
    "7": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000),
    "8": (0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110),
    "9": (0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00001, 0b01110),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "B": (0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110),
    "C": (0b01111, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b01111),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
    "G": (0b01111, 0b10000, 0b10000, 0b10111, 0b10001, 0b10001, 0b01111),
    "H": (0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "I": (0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "J": (0b00001, 0b00001, 0b00001, 0b00001, 0b10001, 0b10001, 0b01110),
    "K": (0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "M": (0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001),
    "O": (0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "Q": (0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "V": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100),
    "W": (0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b10101, 0b01010),
    "X": (0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001),
    "Y": (0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100),
    "Z": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111),
}

DIGIT_3X5 = (
    (0b111, 0b101, 0b101, 0b101, 0b111),
    (0b010, 0b110, 0b010, 0b010, 0b111),
    (0b111, 0b001, 0b111, 0b100, 0b111),
    (0b111, 0b001, 0b111, 0b001, 0b111),
    (0b101, 0b101, 0b111, 0b001, 0b001),
    (0b111, 0b100, 0b111, 0b001, 0b111),
    (0b111, 0b100, 0b111, 0b101, 0b111),
    (0b111, 0b001, 0b010, 0b010, 0b010),
    (0b111, 0b101, 0b111, 0b101, 0b111),
)


def put(canvas: list[list[int]], x: int, y: int, color: int = 1) -> None:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        canvas[y][x] = color


def line(canvas: list[list[int]], x0: int, y0: int, x1: int, y1: int, color: int = 1) -> None:
    dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
    dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        put(canvas, x0, y0, color)
        if x0 == x1 and y0 == y1:
            return
        twice = error * 2
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


def circle(canvas: list[list[int]], cx: int, cy: int, radius: int, color: int = 1) -> None:
    x, y, error = radius, 0, 1 - radius
    while x >= y:
        for px, py in (
            (cx + x, cy + y), (cx - x, cy + y),
            (cx + x, cy - y), (cx - x, cy - y),
            (cx + y, cy + x), (cx - y, cy + x),
            (cx + y, cy - x), (cx - y, cy - x),
        ):
            put(canvas, px, py, color)
        y += 1
        if error < 0:
            error += 2 * y + 1
        else:
            x -= 1
            error += 2 * (y - x) + 1


def text(canvas: list[list[int]], x: int, y: int, value: str, color: int = 1) -> None:
    for character in value.upper():
        rows = FONT[character]
        for row, bits in enumerate(rows):
            for column in range(5):
                if bits & (0x10 >> column):
                    put(canvas, x + column, y + row, color)
        # Keep every glyph in its own aligned tile. Besides producing a crisp
        # NES-native label, this lets repeated letters share CHR patterns.
        x += 8


def text_cell(canvas: list[list[int]], col: int, row: int, value: str, color: int = 1) -> None:
    """Draw tile-aligned text at nametable cell (col, row)."""
    text(canvas, col * 8, row * 8, value, color)


def reverse_cell(canvas: list[list[int]], col: int, row: int, character: str) -> None:
    """Fill one tile and carve the glyph out in black, matching the C64U
    reverse-video slot numbers."""
    rows = FONT[character]
    for py in range(8):
        for px in range(8):
            put(canvas, col * 8 + px, row * 8 + py, 1)
    for gy, bits in enumerate(rows):
        for gx in range(5):
            if bits & (0x10 >> gx):
                put(canvas, col * 8 + gx + 1, row * 8 + gy, 0)


def blank_box(canvas: list[list[int]], x: int, y: int, width: int, height: int) -> None:
    for py in range(y, y + height):
        for px in range(x, x + width):
            put(canvas, px, py, 0)


def ring_label(canvas: list[list[int]], radius: int, character: str) -> None:
    """Place a ring label just right of 12 o'clock. The C64 writes a whole
    character cell there, which punches a gap in the ring; the label reads as
    a break in the arc rather than a digit with a line through it."""
    x = SCOPE_CENTER_X + 4
    y = SCOPE_CENTER_Y - radius - 3
    blank_box(canvas, x - 1, y - 1, 7, 9)
    text(canvas, x, y, character)


def make_canvas() -> list[list[int]]:
    canvas = [[0 for _ in range(WIDTH)] for _ in range(HEIGHT)]

    # Scope bezel, 3/6/9 nm rings, centre cross.
    left = SCOPE_ORIGIN_X
    top = SCOPE_ORIGIN_Y
    right = SCOPE_ORIGIN_X + 159
    bottom = SCOPE_ORIGIN_Y + 159
    line(canvas, left, top, right, top)
    line(canvas, left, bottom, right, bottom)
    line(canvas, left, top, left, bottom)
    line(canvas, right, top, right, bottom)
    for radius in RING_RADII:
        circle(canvas, SCOPE_CENTER_X, SCOPE_CENTER_Y, radius)
    line(canvas, SCOPE_CENTER_X - 4, SCOPE_CENTER_Y, SCOPE_CENTER_X + 4, SCOPE_CENTER_Y)
    line(canvas, SCOPE_CENTER_X, SCOPE_CENTER_Y - 4, SCOPE_CENTER_X, SCOPE_CENTER_Y + 4)
    for radius, character in zip(RING_RADII, ("3", "6", "9")):
        ring_label(canvas, radius, character)

    # NES-native side chrome around the centered scope.
    text_cell(canvas, TITLE_COL, TITLE_ROW, "NES")
    text_cell(canvas, TITLE_COL, TITLE_ROW + 1, "RADAR")
    text_cell(canvas, LINK_COL, LINK_ROW, "LINK")
    text_cell(canvas, LINK_COL, COUNT_ROW, "IN")
    text_cell(canvas, LINK_COL, ERROR_ROW, "ERR")

    # Two columns of four stable slots below the scope. Callsign/type and
    # numeric values are dynamic; only the reverse-video slot is static.
    for slot in range(8):
        col, row = panel_origin(slot)
        reverse_cell(canvas, col, row, str(slot + 1))
    return canvas


def tile_bytes(pixels: tuple[int, ...]) -> bytes:
    low = bytearray()
    high = bytearray()
    for row in range(8):
        low_byte = 0
        high_byte = 0
        for col in range(8):
            value = pixels[row * 8 + col]
            low_byte |= (value & 1) << (7 - col)
            high_byte |= ((value >> 1) & 1) << (7 - col)
        low.append(low_byte)
        high.append(high_byte)
    return bytes(low + high)


def icon_pattern(kind: str) -> tuple[int, ...]:
    pixels = [0] * 64
    if kind == "wait":
        for x in range(1, 7):
            pixels[3 * 8 + x] = 3
    elif kind == "ok":
        for x, y in ((1, 4), (2, 5), (3, 5), (4, 4), (5, 3), (6, 2)):
            pixels[y * 8 + x] = 1
    elif kind == "stale":
        for x, y in ((3, 1), (4, 1), (2, 2), (5, 2), (2, 3), (5, 3),
                     (2, 4), (5, 4), (3, 5), (4, 5), (4, 3)):
            pixels[y * 8 + x] = 3
    elif kind == "error":
        for index in range(1, 7):
            pixels[index * 8 + index] = 2
            pixels[index * 8 + (7 - index)] = 2
    else:
        raise ValueError(kind)
    return tuple(pixels)


def digit_pattern(value: int, color: int = 1) -> tuple[int, ...]:
    pixels = [0] * 64
    rows = FONT[str(value)]
    for row, bits in enumerate(rows):
        for col in range(5):
            if bits & (0x10 >> col):
                pixels[row * 8 + col + 1] = color
    return tuple(pixels)


def font_pattern(character: str, color: int = 1) -> tuple[int, ...]:
    """One runtime-addressable 5x7 glyph in an 8x8 tile."""
    return tuple(
        color if row < 7 and col < 5 and FONT[character][row] & (0x10 >> col) else 0
        for row in range(8)
        for col in range(8)
    )


def reverse_font_pattern(character: str) -> tuple[int, ...]:
    """Reverse-video runtime glyph used by the active ICAO letter."""
    normal = font_pattern(character)
    return tuple(0 if pixel else 1 for pixel in normal)


def background_assets(canvas: list[list[int]]) -> tuple[bytes, bytes, dict[str, int], int]:
    tiles: list[tuple[int, ...]] = []
    indexes: dict[tuple[int, ...], int] = {}
    nametable = bytearray(1024)

    def add(pattern: tuple[int, ...], deduplicate: bool = True) -> int:
        if deduplicate and pattern in indexes:
            return indexes[pattern]
        index = len(tiles)
        if index >= 256:
            raise RuntimeError("background needs more than 256 tiles")
        tiles.append(pattern)
        if deduplicate:
            indexes[pattern] = index
        return index

    for tile_y in range(30):
        for tile_x in range(32):
            pixels = tuple(
                canvas[tile_y * 8 + row][tile_x * 8 + col]
                for row in range(8)
                for col in range(8)
            )
            nametable[tile_y * 32 + tile_x] = add(pixels)

    constants = {}
    constants["TILE_BLANK"] = add(tuple([0] * 64))
    for name in ("wait", "ok", "stale", "error"):
        constants[f"TILE_STATUS_{name.upper()}"] = add(icon_pattern(name), False)
    constants["TILE_DIGIT_0"] = len(tiles)
    for value in range(10):
        add(digit_pattern(value), False)
    constants["TILE_ERROR_BLANK"] = add(tuple([0] * 64), False)
    constants["TILE_ERROR_1"] = len(tiles)
    for value in range(1, 6):
        add(digit_pattern(value, 2), False)

    # Contiguous runtime character set for identity packets. Static labels may
    # deduplicate their glyphs differently, so these deliberately get stable
    # tile numbers of their own.
    constants["TILE_CHAR_SPACE"] = add(font_pattern(" "), False)
    constants["TILE_CHAR_HYPHEN"] = add(font_pattern("-"), False)
    constants["TILE_CHAR_0"] = len(tiles)
    for character in "0123456789":
        add(font_pattern(character), False)
    constants["TILE_CHAR_A"] = len(tiles)
    for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        add(font_pattern(character), False)
    constants["TILE_REVERSE_A"] = len(tiles)
    for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        add(reverse_font_pattern(character), False)

    nametable[STATUS_ROW * 32 + STATUS_COL] = constants["TILE_STATUS_WAIT"]
    nametable[COUNT_ROW * 32 + COUNT_COL] = constants["TILE_DIGIT_0"]
    nametable[ERROR_ROW * 32 + ERROR_COL] = constants["TILE_ERROR_BLANK"]
    for slot in range(8):
        col, row = panel_origin(slot)
        for dynamic_col in range(col + PANEL_CALLSIGN_OFFSET, col + PANEL_CALLSIGN_OFFSET + 8):
            nametable[row * 32 + dynamic_col] = constants["TILE_CHAR_SPACE"]
        for dynamic_col in range(col + PANEL_TYPE_OFFSET, col + PANEL_TYPE_OFFSET + 4):
            nametable[row * 32 + dynamic_col] = constants["TILE_CHAR_SPACE"]
        for dynamic_col in range(col + PANEL_ALT_OFFSET, col + PANEL_ALT_OFFSET + 3):
            nametable[(row + 1) * 32 + dynamic_col] = constants["TILE_BLANK"]
        for dynamic_col in range(col + PANEL_SPEED_OFFSET, col + PANEL_SPEED_OFFSET + 3):
            nametable[(row + 1) * 32 + dynamic_col] = constants["TILE_BLANK"]
    nametable[960:] = bytes(64)  # all quadrants use background palette zero
    chr_data = b"".join(tile_bytes(tile) for tile in tiles).ljust(4096, b"\0")

    def cell_address(name: str, row: int, col: int) -> None:
        address = 0x2000 + row * 32 + col
        constants[f"{name}_HI"] = address >> 8
        constants[f"{name}_LO"] = address & 0xFF

    cell_address("STATUS_ADDR", STATUS_ROW, STATUS_COL)
    cell_address("COUNT_ADDR", COUNT_ROW, COUNT_COL)
    cell_address("ERROR_ADDR", ERROR_ROW, ERROR_COL)
    cell_address("STARTUP_CODE_ADDR", STARTUP_CODE_ROW, STARTUP_CODE_COL)
    cell_address("STARTUP_MESSAGE_ADDR", STARTUP_MESSAGE_ROW, STARTUP_MESSAGE_COL)
    for slot in range(8):
        col, row = panel_origin(slot)
        cell_address(f"PANEL_CALL{slot}_ADDR", row, col + PANEL_CALLSIGN_OFFSET)
        cell_address(f"PANEL_TYPE{slot}_ADDR", row, col + PANEL_TYPE_OFFSET)
        cell_address(f"PANEL_ALT{slot}_ADDR", row + 1, col + PANEL_ALT_OFFSET)
        cell_address(f"PANEL_SPD{slot}_ADDR", row + 1, col + PANEL_SPEED_OFFSET)
    constants["SPRITE_OFFSET_X"] = SPRITE_OFFSET_X
    constants["SPRITE_OFFSET_Y"] = SPRITE_OFFSET_Y
    return chr_data, bytes(nametable), constants, len(tiles)


def startup_nametable(constants: dict[str, int]) -> bytes:
    """Build the controller-driven ICAO entry screen from runtime glyphs."""
    nametable = bytearray([constants["TILE_CHAR_SPACE"]] * 1024)

    def put_text(col: int, row: int, value: str) -> None:
        for offset, character in enumerate(value):
            if character == " ":
                tile = constants["TILE_CHAR_SPACE"]
            elif "A" <= character <= "Z":
                tile = constants["TILE_CHAR_A"] + ord(character) - ord("A")
            else:
                raise ValueError(f"unsupported startup character: {character!r}")
            nametable[row * 32 + col + offset] = tile

    put_text(11, 4, "NES RADAR")
    put_text(8, 7, "SELECT AIRPORT")
    put_text(9, 10, "ICAO")
    for index, character in enumerate(DEFAULT_ICAO):
        base = constants["TILE_REVERSE_A"] if index == 0 else constants["TILE_CHAR_A"]
        nametable[STARTUP_CODE_ROW * 32 + STARTUP_CODE_COL + index] = (
            base + ord(character) - ord("A")
        )
    put_text(9, 18, "UP DOWN CHANGE")
    put_text(8, 20, "LEFT RIGHT MOVE")
    put_text(9, 22, "A NEXT  B BACK")
    put_text(9, 24, "START CONFIRM")
    put_text(4, 27, "WORLDWIDE AIRPORT TRAFFIC")
    nametable[960:] = bytes(64)
    return bytes(nametable)


def make_startup_canvas() -> list[list[int]]:
    canvas = [[0 for _ in range(WIDTH)] for _ in range(HEIGHT)]
    text_cell(canvas, 11, 4, "NES RADAR")
    text_cell(canvas, 8, 7, "SELECT AIRPORT")
    text_cell(canvas, 9, 10, "ICAO")
    for index, character in enumerate(DEFAULT_ICAO):
        if index == 0:
            reverse_cell(canvas, STARTUP_CODE_COL + index, STARTUP_CODE_ROW, character)
        else:
            text_cell(canvas, STARTUP_CODE_COL + index, STARTUP_CODE_ROW, character)
    text_cell(canvas, 9, 18, "UP DOWN CHANGE")
    text_cell(canvas, 8, 20, "LEFT RIGHT MOVE")
    text_cell(canvas, 9, 22, "A NEXT  B BACK")
    text_cell(canvas, 9, 24, "START CONFIRM")
    text_cell(canvas, 4, 27, "WORLDWIDE AIRPORT TRAFFIC")
    return canvas


# Marker geometry inside one 8x16 pattern, centre at local (3, 7).
#
# The pinned C64U marker is a FILLED 11x11 diamond with the slot number
# knocked out of it in black, plus a five-pixel track stem. That exact shape
# cannot be reproduced here: a 45-degree diamond wide enough to hold a 3x5
# digit with the C64's clearance needs at least nine pixels of width, and an
# NES hardware sprite is eight. This is the closest single-sprite equivalent —
# a filled seven-wide, nine-tall diamond with the same knocked-out digit and
# the same eight track directions.
#
# Half-width of the diamond by vertical distance from centre. Rows within two
# of centre carry the digit, so they must stay at least two wide either side.
DIAMOND_HALF_WIDTH = (3, 2, 2, 1, 0)
DIGIT_ORIGIN = (2, 5)                       # 3x5 digit at cols 2..4, rows 5..9

# Track stems, drawn outside the diamond. North/south and the four diagonals
# follow the C64 exactly in direction. East and west have a single spare
# column each, so they use a five-pixel bar against that vertex; the vertex
# itself is already lit, so the bar reads as one solid flat edge.
STEM_PIXELS = {
    0: ((3, 0), (3, 1), (3, 2)),                                # N
    1: ((5, 4), (6, 3), (7, 2)),                                # NE
    2: ((6, 5), (6, 6), (6, 8), (6, 9), (7, 7)),                # E
    3: ((5, 10), (6, 11), (7, 12)),                             # SE
    4: ((3, 12), (3, 13), (3, 14)),                             # S
    5: ((1, 10), (0, 11)),                                      # SW
    6: ((0, 5), (0, 6), (0, 8), (0, 9)),                        # W
    7: ((1, 4), (0, 3)),                                        # NW
}


def diamond_pixels() -> set[tuple[int, int]]:
    """Filled diamond body, centre (3, 7)."""
    body = set()
    for offset, half in enumerate(DIAMOND_HALF_WIDTH):
        for sign in (-1, 1):
            y = 7 + sign * offset
            for x in range(3 - half, 3 + half + 1):
                body.add((x, y))
    return body


def digit_pixels(slot: int) -> set[tuple[int, int]]:
    """Pixels of the knocked-out slot number. Slots 0..7 display 1..8, which
    is what the C64U list and its markers show."""
    origin_x, origin_y = DIGIT_ORIGIN
    result = set()
    for y, bits in enumerate(DIGIT_3X5[slot + 1]):
        for x in range(3):
            if bits & (4 >> x):
                result.add((origin_x + x, origin_y + y))
    return result


def sprite_pattern(slot: int, sector: int | None) -> tuple[int, ...]:
    pixels = [0] * 128
    for x, y in diamond_pixels():
        pixels[y * 8 + x] = 1
    if sector is not None:
        for x, y in STEM_PIXELS[sector]:
            pixels[y * 8 + x] = 1
    # The number is transparent, exactly as on the C64U, so the black scope
    # shows through and an alert target's red body knocks out identically.
    for x, y in digit_pixels(slot):
        pixels[y * 8 + x] = 0
    return tuple(pixels)


def sprite_assets() -> tuple[bytes, int]:
    patterns = [sprite_pattern(slot, sector) for slot in range(8) for sector in range(8)]
    patterns.extend(sprite_pattern(slot, None) for slot in range(8))
    tiles = []
    for pattern in patterns:
        tiles.append(pattern[:64])
        tiles.append(pattern[64:])
    return b"".join(tile_bytes(tile) for tile in tiles).ljust(4096, b"\0"), len(tiles)


def png_bytes(canvas: list[list[int]]) -> bytes:
    # black, green, red, amber, white ($30 sprite digit color)
    colors = ((0, 0, 0), (106, 229, 91), (232, 78, 78), (248, 190, 70),
              (236, 238, 236))
    height = len(canvas)
    width = len(canvas[0])
    raw = bytearray()
    for row in canvas:
        raw.append(0)
        for pixel in row:
            raw.extend(colors[pixel])

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def overlay_fixture(canvas: list[list[int]]) -> list[list[int]]:
    result = [row[:] for row in canvas]
    targets = ((80, 54, 0, 0), (112, 34, 1, 1), (130, 80, 2, 2), (116, 116, 3, 3),
               (80, 130, 4, 4), (44, 116, 5, 5), (30, 80, 6, 6), (54, 54, 7, 7))
    for scene_x, scene_y, slot, sector in targets:
        x = scene_x + SCOPE_ORIGIN_X
        y = scene_y + SCOPE_ORIGIN_Y
        pattern = sprite_pattern(slot, sector)
        for py in range(16):
            for px in range(8):
                pixel = pattern[py * 8 + px]
                if pixel:
                    put(result, x - 3 + px, y - 7 + py, 2 if slot == 7 else 1)
    return result


def overlay_tile(canvas: list[list[int]], tile_x: int, tile_y: int, pattern: tuple[int, ...]) -> None:
    for py in range(8):
        for px in range(8):
            canvas[tile_y * 8 + py][tile_x * 8 + px] = pattern[py * 8 + px]


FIXTURE_IDENTITIES = (
    ("UAL123", "B738"),
    ("DAL456", "A321"),
    ("SWA789", "B737"),
    ("ASA246", "B739"),
    ("N721ZX", "C172"),
    ("FDX510", "B763"),
    ("SKW8821", "E175"),
    ("JBU808", "A220"),
)
FIXTURE_VALUES = (
    (12, 95), (18, 110), (24, 125), (30, 140),
    (36, 155), (42, 170), (48, 185), (54, 200),
)


def overlay_panel_fixture(canvas: list[list[int]]) -> list[list[int]]:
    """Overlay the dynamic identity and numeric fields used by the sender."""
    result = [row[:] for row in canvas]
    for slot, ((callsign, aircraft_type), (altitude, speed)) in enumerate(
        zip(FIXTURE_IDENTITIES, FIXTURE_VALUES)
    ):
        col, row = panel_origin(slot)
        for index, character in enumerate(callsign.ljust(8)):
            overlay_tile(result, col + PANEL_CALLSIGN_OFFSET + index, row, font_pattern(character))
        for index, character in enumerate(aircraft_type.ljust(4)):
            overlay_tile(result, col + PANEL_TYPE_OFFSET + index, row, font_pattern(character))
        for index, digit in enumerate(f"{altitude:03d}"):
            overlay_tile(result, col + PANEL_ALT_OFFSET + index, row + 1, digit_pattern(int(digit)))
        for index, digit in enumerate(f"{speed:03d}"):
            overlay_tile(result, col + PANEL_SPEED_OFFSET + index, row + 1, digit_pattern(int(digit)))
    return result


SPRITE_SHEET_SCALE = 3
SPRITE_SHEET_WIDTH = 9 * (8 * SPRITE_SHEET_SCALE + 4) + 4      # 256
SPRITE_SHEET_HEIGHT = 8 * (16 * SPRITE_SHEET_SCALE + 4) + 4    # 420


def sprite_sheet_preview() -> list[list[int]]:
    """Every slot (rows) against every sector plus no-track (columns)."""
    sheet = [[0 for _ in range(SPRITE_SHEET_WIDTH)] for _ in range(SPRITE_SHEET_HEIGHT)]
    scale = SPRITE_SHEET_SCALE
    for slot in range(8):
        for column in range(9):
            sector = column if column < 8 else None
            pattern = sprite_pattern(slot, sector)
            origin_x = 4 + column * (8 * scale + 4)
            origin_y = 4 + slot * (16 * scale + 4)
            for py in range(16):
                for px in range(8):
                    pixel = pattern[py * 8 + px]
                    if not pixel:
                        continue
                    color = 1
                    for sy in range(scale):
                        for sx in range(scale):
                            sheet[origin_y + py * scale + sy][origin_x + px * scale + sx] = color
    return sheet


def generate(output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    canvas = make_canvas()
    bg_chr, nametable, constants, bg_count = background_assets(canvas)
    sprite_chr, sprite_count = sprite_assets()
    (output_dir / "radar_bg.chr").write_bytes(bg_chr)
    (output_dir / "radar_sprites.chr").write_bytes(sprite_chr)
    (output_dir / "radar_nametable.bin").write_bytes(nametable)
    (output_dir / "startup_nametable.bin").write_bytes(startup_nametable(constants))
    include_lines = [f"{name} = ${value:02X}" for name, value in constants.items()]
    include_lines.extend(("SPRITE_UNKNOWN_BASE = $81", "SPRITE_TILE_COUNT = $90"))
    (output_dir / "assets.inc").write_text("\n".join(include_lines) + "\n")
    static_preview = [row[:] for row in canvas]
    overlay_tile(static_preview, STATUS_COL, STATUS_ROW, icon_pattern("wait"))
    overlay_tile(static_preview, COUNT_COL, COUNT_ROW, digit_pattern(0))
    overlay_tile(static_preview, ERROR_COL, ERROR_ROW, tuple([0] * 64))
    scene_preview = overlay_panel_fixture(overlay_fixture(canvas))
    overlay_tile(scene_preview, STATUS_COL, STATUS_ROW, icon_pattern("ok"))
    overlay_tile(scene_preview, COUNT_COL, COUNT_ROW, digit_pattern(8))
    overlay_tile(scene_preview, ERROR_COL, ERROR_ROW, tuple([0] * 64))
    (output_dir / "static_scope.png").write_bytes(png_bytes(static_preview))
    (output_dir / "startup_screen.png").write_bytes(png_bytes(make_startup_canvas()))
    (output_dir / "synthetic_scene_preview.png").write_bytes(png_bytes(scene_preview))
    (output_dir / "nes_direction_sprite_sheet.png").write_bytes(png_bytes(sprite_sheet_preview()))
    return {"background_tiles": bg_count, "sprite_tiles": sprite_count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    counts = generate(args.output_dir)
    print(f"background tiles: {counts['background_tiles']}/256")
    print(f"sprite tiles: {counts['sprite_tiles']}/256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
