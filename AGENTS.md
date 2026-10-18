# Notes for AI assistants (and people)

## This repository and nesp32

NES Radar lives in two repositories. Read this before changing anything.

- **k6lcm/nes-radar (here)** is the source of truth for the ROM:
  `nes_radar/nes/nes_radar_scope_v3.s`, `nes_radar/nes/radar_link.inc`
  and everything else that ends up in the `.nes` file, including the
  nesp32 cartridge build (code under `.ifdef CART`).
- **[Armitage64/nesp32](https://github.com/Armitage64/nesp32)** has
  nes-radar as a git submodule at `third_party/nes-radar`. It builds the
  ROM for its cartridge and tests (`apps/nes-radar`), and has the
  firmware's RADAR service that the ROM talks to.
- From 0.5.0 `main` is for a nesp32 only. The FTDI cable and its server
  are on the **`legacy/ftdi-0.4.x`** branch (0.4.x releases). FTDI fixes
  go there and nowhere else; never merge it into `main` or the other way.

## Where a change goes

| Change | Where | Then |
|---|---|---|
| The ROM: screens, buttons, LINK, bugs | here | release it; then in nesp32, a PR that moves the submodule to the new commit |
| Cartridge-only behaviour (`CART`) | here | nesp32's `tests/test_cart.py` covers it |
| nesp32's link protocol (`proto/nesp.toml`, `nes/lib/` in nesp32) | nesp32 | here: `nes_radar/tools/update_nesp32.sh /path/to/nesp32`, commit `nes_radar/vendor/nesp32/` |
| Firmware, RADAR service, other nesp32 apps | nesp32 only | nothing here, unless the protocol changed |
| Needs both (e.g. a new RADAR request) | both | here first, then nesp32's PR also moves the submodule |

## Rules

- `nes_radar/vendor/nesp32/` is generated. Never edit it by hand: run
  `tools/update_nesp32.sh`. nesp32's `make -C apps/nes-radar verify` fails
  when the copy differs from nesp32's own.
- Push here **before** pushing a nesp32 commit that points at a new
  commit here. The submodule must never point at a commit GitHub doesn't
  have.
- Merge PRs here with a **merge commit**, not squash, so the commit nesp32
  points at stays on `main`.
- Bump the version in `version_stamp` (`nes_radar/nes/nes_radar_scope_v3.s`,
  shown on the splash) and `CHANGELOG.md` together. Releases attach the
  ROM and a `SHA256SUMS`.
- The easiest place to work is `third_party/nes-radar` inside a nesp32
  checkout: it is a full clone, so nesp32's tests
  (`make -C apps/nes-radar test`, `pytest tests/test_cart.py tests/test_radar.py`)
  run against your change before anything is pushed.
- Test on hardware before a release: the standalone ROM on a flash
  cartridge, and nesp32's cartridge (`make cart` in nesp32).

## Building

```sh
cd nes_radar
make verify     # needs cc65 (ca65, ld65) and Python 3
```
