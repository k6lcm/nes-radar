#!/usr/bin/env python3
"""Generate the 16x16 target-marker CHR and assembly includes used by the ROM."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_assets import (          # noqa: E402
    DIGIT_3X5,
    FONT,
    SCOPE_ORIGIN_X,
    SCOPE_ORIGIN_Y,
    make_canvas,
    overlay_panel_fixture,
    png_bytes,
    put,
    tile_bytes,
)

# --------------------------------------------------------------------------
# Geometry, measured pixel-for-pixel off the pinned C64U direction sheet.
# --------------------------------------------------------------------------

BOX = 16                        # two 8x16 hardware sprites, side by side
CENTRE = (7, 7)                 # marker centre inside the 16x16 box
DIAMOND_HALF = 5                # C64U diamond is 11x11, true 45 degrees
DIGIT_DX = (-1, 0, 1)           # digit occupies centre columns -1..+1
DIGIT_DY = (-2, -1, 0, 1, 2)    # and centre rows -2..+2
# A C64U stem is five pixels starting one pixel outside the diamond edge.
# The edge sits five pixels out along a cardinal but only two along a
# diagonal, because the body is |dx|+|dy| <= 5.
CARDINAL_STEM_STEPS = range(6, 11)
DIAGONAL_STEM_STEPS = range(3, 8)

# Unit vectors in the engine's sector order: sector = ((track+16)&255) >> 5.
SECTOR_VECTORS = (
    (0, -1),    # 0 N
    (1, -1),    # 1 NE
    (1, 0),     # 2 E
    (1, 1),     # 3 SE
    (0, 1),     # 4 S
    (-1, 1),    # 5 SW
    (-1, 0),    # 6 W
    (-1, -1),   # 7 NW
)
SECTOR_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# Every stem lies wholly in one half of the box, so the two halves can be
# banked independently. That is what keeps the set inside the CHR budget.
LEFT_VARIANTS = (None, 0, 4, 6, 5, 7)       # plain, N, S, W, SW, NW
RIGHT_VARIANTS = (None, 2, 1, 3)            # plain, E, NE, SE
SECTOR_VARIANTS = tuple(
    (LEFT_VARIANTS.index(s) if s in LEFT_VARIANTS else 0,
     RIGHT_VARIANTS.index(s) if s in RIGHT_VARIANTS else 0)
    for s in range(8)
)
NO_TRACK_VARIANTS = (0, 0)

LEFT_PAIRS_PER_SLOT = len(LEFT_VARIANTS)    # 6
RIGHT_PAIRS_PER_SLOT = len(RIGHT_VARIANTS)  # 4
LEFT_PAIR_BASE = 0
RIGHT_PAIR_BASE = 8 * LEFT_PAIRS_PER_SLOT   # 48
TOTAL_PAIRS = RIGHT_PAIR_BASE + 8 * RIGHT_PAIRS_PER_SLOT   # 80
TOTAL_TILES = TOTAL_PAIRS * 2                              # 160
STARTUP_LETTER_PAIR_BASE = TOTAL_PAIRS
STARTUP_LETTER_COUNT = 26
STARTUP_LETTER_TILES = STARTUP_LETTER_COUNT * 2
TOTAL_CHR_TILES = TOTAL_TILES + STARTUP_LETTER_TILES       # 212

# Screen placement. The centre lands on the host coordinate exactly, and no
# value can underflow or wrap: scene X 0..159 gives 1..168, scene Y gives
# 32..191.
OFFSET_X_LEFT = SCOPE_ORIGIN_X - CENTRE[0]          # 1
OFFSET_X_RIGHT = OFFSET_X_LEFT + 8                  # 9
OFFSET_Y = SCOPE_ORIGIN_Y - CENTRE[1] - 1           # 32


def diamond_pixels() -> set[tuple[int, int]]:
    cx, cy = CENTRE
    body = set()
    for dy in range(-DIAMOND_HALF, DIAMOND_HALF + 1):
        half = DIAMOND_HALF - abs(dy)
        for dx in range(-half, half + 1):
            body.add((cx + dx, cy + dy))
    return body


def digit_pixels(slot: int) -> set[tuple[int, int]]:
    """Slots 0..7 display 1..8, as on the C64U list and its markers."""
    cx, cy = CENTRE
    rows = DIGIT_3X5[slot + 1]
    return {
        (cx + DIGIT_DX[x], cy + DIGIT_DY[y])
        for y, bits in enumerate(rows)
        for x in range(3)
        if bits & (4 >> x)
    }


def stem_pixels(sector: int) -> set[tuple[int, int]]:
    """Five-pixel C64U stem, clipped to the 16x16 box."""
    cx, cy = CENTRE
    ux, uy = SECTOR_VECTORS[sector]
    steps = DIAGONAL_STEM_STEPS if (ux and uy) else CARDINAL_STEM_STEPS
    pixels = set()
    for step in steps:
        x, y = cx + ux * step, cy + uy * step
        if 0 <= x < BOX and 0 <= y < BOX:
            pixels.add((x, y))
    return pixels


def composite(slot: int, sector: int | None) -> list[list[int]]:
    grid = [[0] * BOX for _ in range(BOX)]
    for x, y in diamond_pixels():
        grid[y][x] = 1
    if sector is not None:
        for x, y in stem_pixels(sector):
            grid[y][x] = 1
    for x, y in digit_pixels(slot):     # knocked out, exactly as on the C64U
        grid[y][x] = 0
    return grid


def half_pattern(slot: int, sector: int | None, right: bool) -> tuple[int, ...]:
    """One 8x16 hardware sprite: the left or right half of the composite."""
    grid = composite(slot, sector)
    base = 8 if right else 0
    return tuple(grid[y][base + x] for y in range(BOX) for x in range(8))


def sprite_chr() -> bytes:
    tiles: list[tuple[int, ...]] = []
    for slot in range(8):
        for sector in LEFT_VARIANTS:
            pattern = half_pattern(slot, sector, right=False)
            tiles.append(pattern[:64])
            tiles.append(pattern[64:])
    for slot in range(8):
        for sector in RIGHT_VARIANTS:
            pattern = half_pattern(slot, sector, right=True)
            tiles.append(pattern[:64])
            tiles.append(pattern[64:])
    assert len(tiles) == TOTAL_TILES, len(tiles)
    blank = tuple([0] * 64)
    for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        glyph = [0] * 64
        for row, bits in enumerate(FONT[character]):
            for col in range(5):
                if bits & (0x10 >> col):
                    glyph[(row + 1) * 8 + col + 1] = 1
        tiles.extend((tuple(glyph), blank))
    assert len(tiles) == TOTAL_CHR_TILES, len(tiles)
    return b"".join(tile_bytes(t) for t in tiles).ljust(4096, b"\0")


def left_pair(slot: int, variant: int) -> int:
    return LEFT_PAIR_BASE + slot * LEFT_PAIRS_PER_SLOT + variant


def right_pair(slot: int, variant: int) -> int:
    return RIGHT_PAIR_BASE + slot * RIGHT_PAIRS_PER_SLOT + variant


def oam_tile(pair: int) -> int:
    """8x16 mode: bit 0 selects pattern table $1000, bits 7..1 the pair."""
    return (pair << 1) | 1


def include_text() -> str:
    """Equates only, so this can be included anywhere in the source."""
    return "\n".join((
        "; Generated by tools/generate_metasprites.py -- do not edit.",
        "; 16x16 two-sprite marker set matching the pinned C64U geometry.",
        f"META_LEFT_PAIR_BASE   = ${LEFT_PAIR_BASE:02X}",
        f"META_RIGHT_PAIR_BASE  = ${RIGHT_PAIR_BASE:02X}",
        f"META_LEFT_PER_SLOT    = ${LEFT_PAIRS_PER_SLOT:02X}",
        f"META_RIGHT_PER_SLOT   = ${RIGHT_PAIRS_PER_SLOT:02X}",
        f"META_PAIR_COUNT       = ${TOTAL_PAIRS:02X}",
        f"META_TILE_COUNT       = ${TOTAL_TILES:02X}",
        f"STARTUP_LETTER_TILE_BASE = ${(STARTUP_LETTER_PAIR_BASE << 1) | 1:02X}",
        f"STARTUP_LETTER_COUNT  = ${STARTUP_LETTER_COUNT:02X}",
        f"SPRITE_TILE_COUNT     = ${TOTAL_CHR_TILES:02X}",
        f"META_OFFSET_X_LEFT    = ${OFFSET_X_LEFT:02X}",
        f"META_OFFSET_X_RIGHT   = ${OFFSET_X_RIGHT:02X}",
        f"META_OFFSET_Y         = ${OFFSET_Y:02X}",
        f"META_NO_TRACK_LEFT    = ${NO_TRACK_VARIANTS[0]:02X}",
        f"META_NO_TRACK_RIGHT   = ${NO_TRACK_VARIANTS[1]:02X}",
        "",
    ))


def tables_text() -> str:
    """Byte tables. Include these inside a RODATA segment."""
    left = ", ".join(f"${v:02X}" for v, _ in SECTOR_VARIANTS)
    right = ", ".join(f"${r:02X}" for _, r in SECTOR_VARIANTS)
    names = ", ".join(SECTOR_NAMES)
    return "\n".join((
        "; Generated by tools/generate_metasprites.py -- do not edit.",
        f"; sector order: {names}",
        "; index with sector = ((track + 16) & 255) >> 5",
        "meta_left_variant:",
        f"    .byte {left}",
        "meta_right_variant:",
        f"    .byte {right}",
        "",
    ))


def sheet_preview(scale: int = 3, pad: int = 4) -> list[list[int]]:
    cell = BOX * scale + pad
    width = 9 * cell + pad
    height = 8 * cell + pad
    sheet = [[0] * width for _ in range(height)]
    for slot in range(8):
        for column in range(9):
            sector = column if column < 8 else None
            grid = composite(slot, sector)
            ox = pad + column * cell
            oy = pad + slot * cell
            for y in range(BOX):
                for x in range(BOX):
                    if not grid[y][x]:
                        continue
                    for sy in range(scale):
                        for sx in range(scale):
                            sheet[oy + y * scale + sy][ox + x * scale + sx] = 1
    return sheet


def scene_preview() -> list[list[int]]:
    canvas = overlay_panel_fixture(make_canvas())
    targets = ((80, 54, 0, 0), (112, 34, 1, 1), (130, 80, 2, 2), (116, 116, 3, 3),
               (80, 130, 4, 4), (44, 116, 5, 5), (30, 80, 6, 6), (54, 54, 7, 7))
    for scene_x, scene_y, slot, sector in targets:
        grid = composite(slot, sector)
        left = scene_x + SCOPE_ORIGIN_X - CENTRE[0]
        top = scene_y + SCOPE_ORIGIN_Y - CENTRE[1]
        colour = 2 if slot == 7 else 1
        for y in range(BOX):
            for x in range(BOX):
                if grid[y][x]:
                    put(canvas, left + x, top + y, colour)
    return canvas


def generate(output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "radar_sprites_16.chr").write_bytes(sprite_chr())
    (output_dir / "assets_metasprite.inc").write_text(include_text())
    (output_dir / "assets_metasprite_tables.inc").write_text(tables_text())
    (output_dir / "nes_metasprite_sheet.png").write_bytes(png_bytes(sheet_preview()))
    (output_dir / "metasprite_scene_preview.png").write_bytes(png_bytes(scene_preview()))
    return {"pairs": TOTAL_PAIRS, "tiles": TOTAL_CHR_TILES}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    counts = generate(args.output_dir)
    print(f"metasprite pairs: {counts['pairs']}/128")
    print(f"metasprite tiles: {counts['tiles']}/256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
