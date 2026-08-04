#!/usr/bin/env python3
"""Split this mapper-3 iNES image into raw PRG and CHR programmer files."""

from __future__ import annotations

import argparse
from pathlib import Path


def split_cnrom(rom_path: Path, prg_path: Path, chr_path: Path) -> None:
    data = rom_path.read_bytes()
    if len(data) != 16 + 32768 + 32768:
        raise ValueError("expected a 65,552-byte CN-ROM image")
    if data[:8] != b"NES\x1a\x02\x04\x30\x00":
        raise ValueError("expected mapper 3 with 32 KiB PRG and 32 KiB CHR")

    prg_path.parent.mkdir(parents=True, exist_ok=True)
    chr_path.parent.mkdir(parents=True, exist_ok=True)
    prg_path.write_bytes(data[16:16 + 32768])
    chr_path.write_bytes(data[16 + 32768:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("prg", type=Path)
    parser.add_argument("chr", type=Path)
    args = parser.parse_args()
    split_cnrom(args.rom, args.prg, args.chr)


if __name__ == "__main__":
    main()
