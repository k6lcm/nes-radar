# LINK state definitions

The visible field is nine tiles wide and has four states.

`IDLE` and `RECEIVING` are both healthy. They differ in whether the ROM is
running its own display window or listening to the wire.

## IDLE

A fresh, CRC-valid traffic scene was accepted less than ten seconds ago,
the host did not mark its upstream data stale, and the ROM is inside its
display window. The scene's target sprites, table rows, selected-aircraft
details, and count are visible.

This is the state where sprite-flicker rotation starts. It runs once per
field, so with more than four targets the ones beyond the
eight-sprites-per-scanline limit take turns during `IDLE`. The rotation
counter continues to tick when the state changes, so `WAITING` and
`ERROR` also animate for as long as the last accepted scene is still on
screen.

## RECEIVING

The display window has expired and the ROM is listening for the next
packet, either waiting for the marker or taking bytes. It is entered at
the end of the 360-field window and leaves when a scene is accepted.

The controller works here. That was not true when this state was
introduced, and it is the whole point of the chunk gaps in `SIGNALING.md`.
The pad is serviced from two places, because the ROM is in two different
situations:

- **Waiting for the marker.** `service_idle_if_vblank` splits the work
  across the vblank boundary. The selection move and the panel rebuild
  are RAM work and run outside vblank, and the PPU write happens on the
  next vblank, so the repaint lands one frame after the press. Both
  halves are gated on an actual press, so the hunt only goes blind to the
  wire when there is something to do.
- **Taking bytes.** The host holds a 30 ms gap after every eighth packet
  byte and the ROM repaints there, about every 73 ms.

While no packet is in flight, the host sends a one-byte display heartbeat
every 25 ms. Each heartbeat advances the same OAM-priority rotation used in
`IDLE`, so the unchanged two-sprite aircraft do not freeze at one overflow
priority while the link says `RECEIVING`. The heartbeat changes no scene data
and stops before the next packet marker.

The state changes at the window boundary rather than at the first start
bit, so the one to three seconds spent waiting for the packet sit inside
`RECEIVING` along with the packet. The ROM cannot repaint this field
mid-packet to correct that: `write_link_during_vblank` would have to wait
for vblank, and between bytes there is only the 5 ms guard. The chunk
gaps are long enough, but spending one on the LINK text rather than the
selection is not worth it.

## WAITING

The radar is waiting for current traffic. This is shown:

- before the first accepted traffic scene;
- after ten seconds without a valid packet; or
- immediately when an accepted scene carries the upstream-stale flag.

Entering `WAITING` clears the scene sequence state and nothing else. The
last complete scene stays on screen: targets, table rows,
selected-aircraft details, and the count all remain, and the `LINK` field
is what says the data is old. A scope that erases itself the moment the
host pauses reads as broken, and the aircraft that were there a moment
ago are the best information available. The sequence state still has to
go, because the server restarts its numbering on a fresh stream and a
retained one would make the first scene back look like a sequence error.

A later fresh scene replaces the targets and changes the state to `IDLE`.

`WAITING` and `ERROR` both own the field outright. Neither is overwritten
when the display window expires, because both describe a link that is not
delivering, and showing `RECEIVING` over either would claim activity the
player has no way to check.

## ERROR

A UART framing, packet header, CRC-16, record validation, scene sequence,
or severe upstream error occurred. A damaged packet never replaces the
last complete scene.

The link field retains the receiver's numeric reason as `ERROR 1` through
`ERROR 5`:

- `ERROR 1`: UART stop-bit/framing failure
- `ERROR 2`: packet type, version, flags, count, or length failure
- `ERROR 3`: CRC-16 mismatch
- `ERROR 4`: scene or identity record validation, or location-result
  mismatch against the code the NES submitted
- `ERROR 5`: scene sequence gap or out-of-order packet

The number is the receiver's own rejection path surfaced to the screen. It
does not weaken any check and it does not require a separate diagnostic
ROM.

A plain, unnumbered `LINK ERROR` is a different signal: it comes from an
accepted scene the host marked as a severe upstream failure (bad ADS-B
data, bad location, or upstream service down), not from a rejected packet.

A chunk-gap mismatch — a server run with `--chunk-bytes 0` against the
released ROM — is unsupported and typically surfaces here. The ROM
services the pad in the missing gap; if that service commits a
directional repaint, the following packet byte is lost and the packet
fails CRC as `ERROR 3`. If the controller has no work pending, the
service returns quickly and the byte can still land inside the ordinary
5 ms guard. Do not rely on that path.

If fresh traffic recovers, the next accepted scene changes the state to
`IDLE`. If silence continues to the ten-second threshold, the state
changes to `WAITING`, which — as above — clears the scene sequence state
and leaves the last scene on screen.
