# NES Radar ROM source

This builds the NES side of NES Radar: the ROM that draws the radar display
on the console and talks to a nesp32 through controller port 2. You only
need it if you want to build the ROM yourself — the ready-to-run `.nes`
file is on the [Releases page](https://github.com/k6lcm/nes-radar/releases).

Building requires the cc65 toolchain and Python 3; no Python packages are
required.

## Building

```text
make verify
```

builds the ROM and checks its size, iNES header and asset sizes.

```text
make hardware-images
```

emits separate 32 KiB PRG and CHR images for compatible flash programmers.

The link's cycle-timed routines are tested in
[nesp32](https://github.com/Armitage64/nesp32) (`apps/nes-radar`), which
builds this ROM from its submodule and runs it on a simulated console
against the nesp32's own RADAR service.

## The nesp32 link library

`vendor/nesp32/` is a copy of nesp32's link library for the console:
`nesp.inc` as it is, and `nesp_proto.inc` and `link.inc` as nesp32's tools
make them. `VERSION` names the nesp32 commit they came from. When nesp32's
link protocol changes, copy them again from a nesp32 checkout and commit
the result:

```text
tools/update_nesp32.sh /path/to/nesp32
```

`nes/radar_link.inc` is the ROM's side of the link: the hello, the airport,
the scope's loop and its exchanges.

## Versioning

The ROM stamps its name and version onto the splash screen, so a `.nes`
file or a flashed cartridge still says what it is when it turns up on its
own. `version_stamp` in `nes/nes_radar_scope_v3.s` holds it; bump it with
`CHANGELOG.md`.

## Reference

- `PROTOCOL.md` — the target and identity records the nesp32 sends, and
  the 0.4.x cable's packet envelope.
- `LAYOUT.md` — the screen layout.
