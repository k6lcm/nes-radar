# NES Radar ROM 0.3.1 source

This builds the NES side of NES Radar: the ROM that draws the radar display on
the console and receives aircraft data from the server through the controller
port. You only need it if you want to build the ROM yourself — the ready-to-run
`.nes` file is in `executables/`, and running it needs no toolchain at all.

Building requires the cc65 toolchain and Python 3; no Python packages are
required.

The ROM stamps its name and version onto the splash screen, so a `.nes` file or
a flashed cartridge still says what it is when it turns up on its own. When
bumping the version, change `version_stamp` in `nes/nes_radar_scope_v3.s`
alongside this file and `server/VERSION`.

Build and verify with:

```text
make verify
```

`make hardware-images` also emits separate 32 KiB PRG and CHR images for
compatible flash programmers.

See `PROTOCOL.md` and `LINK_STATES.md` for the paired server protocol and link
states.
