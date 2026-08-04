# NES Radar ROM 0.3-beta1 source

This is the source used for the 0.3-beta1 CN-ROM image. Building it requires the
cc65 toolchain and Python 3; no Python packages are required.

The checked release ROM is distributed separately as
`nes_radar_0_3_beta1.nes`.

Build and verify with:

```text
make verify
```

The build produces bytes identical to the public beta ROM. `make
hardware-images` also emits separate 32 KiB PRG and CHR images for compatible
flash programmers.

See `PROTOCOL.md` and `LINK_STATES.md` for the paired server protocol and link
states.
