# NES Radar Scope v2 Layout

The display contract is `assets/ldv/SPEC.md` followed by
`assets/ldv/ldv_screen.inc`. The background CHR, 960-byte nametable, 64-byte
attribute table, palette, field positions, widths, font bases, and four-frame
vblank split are used without layout changes.

The scope interior is 128×128 pixels at `(64,32)`, centred on `(128,96)`.
Host coordinates are local to that interior, centred on `(64,64)`, at exactly
7 pixels per nautical mile. The maximum displayed centre radius is 63 pixels.

V2 retains the previous 16×16 target marker: an 11×11 numbered diamond and
heading tail combined into one logical metasprite made from two adjacent 8×16
hardware sprites. Its LDV placement offsets are:

```text
OAM X left  = local X + 57
OAM X right = local X + 65
OAM Y       = local Y + 24
```

This preserves the host-projected centre exactly. It also means the display
reaches the eight-sprites-per-scanline limit at four complete targets rather
than the five-target capacity anticipated for a single-sprite design. The
selected marker stays in the first OAM pair. The remaining paired markers
rotate once per native video field during the host-silent display window,
creating classic NES overflow flicker.
