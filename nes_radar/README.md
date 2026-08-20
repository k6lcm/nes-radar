# NES Radar ROM source

This builds the NES side of NES Radar: the ROM that draws the radar display
on the console and receives aircraft data from the server through the
controller port. You only need it if you want to build the ROM yourself —
the ready-to-run `.nes` file is on the
[Releases page](https://github.com/k6lcm/nes-radar/releases), and running it
needs no toolchain at all.

Building requires the cc65 toolchain and Python 3; no Python packages are
required.

## Building

```text
make verify
```

builds the ROM, checks its size and iNES header and asset sizes, and runs
the two reverse-channel verifiers.

The verifiers are not optional extras. The transmit routine's bit period
depends on its own linked address, because a delay loop straddling a page
boundary costs an extra cycle per iteration and drops 9,600 baud to 8,170
— silently, with the ROM still sending and the host still seeing bytes.
`tools/verify_tx_timing.py` charges that penalty on a cycle-accurate model
and checks all 256 byte values. `tools/verify_frame_bytes.py` demodulates
the ROM's own writes to `$4016` and compares the result against the
server's `request_bytes()`, so it detects the two sides disagreeing rather
than restating one side's rule.

```text
make hardware-images
```

emits separate 32 KiB PRG and CHR images for compatible flash programmers.

## Versioning

The ROM stamps its name and version onto the splash screen, so a `.nes`
file or a flashed cartridge still says what it is when it turns up on its
own. `version_stamp` in `nes/nes_radar_scope_v3.s` holds it.

The ROM and the server are a required-matched pair — the chunk gaps and
the reverse channel both depend on it — so their version numbers move
together. Four places hold it: `version_stamp` here, `server/VERSION`,
`APP_VERSION` in `server/src/nes_radar_server.py`, and the docstring in
`server/start_nes_radar_server.py`. `server/VERSION` also names every
archive `packaging/build_release.py` produces, so changing it renames the
release artifacts.

## Reference

- `PROTOCOL.md` — packet envelope, records, and the two NES-to-host
  requests.
- `LINK_STATES.md` — the four visible link states and the numbered
  `ERROR 1`–`ERROR 5` reporting.
- `../SIGNALING.md` — electrical, timing, and framing contract.
