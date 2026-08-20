# NES Radar Protocol v2

The host-to-NES path uses length-delimited CRC packets with a calibrated
6502 UART receiver. v2 keeps the byte receiver, bit delays, byte guard, and
CRC implementation from v0 and extends only the validated payload records
so the LDV sidebar can show the ADS-B detail fields.

Electrical wiring, transport-level pacing, and the visible-state semantics
are in `../SIGNALING.md`. This document covers the packet envelope, the
per-type records, and the two NES-to-host requests.

## NES-to-host requests

Both requests are six bytes. The ROM bit-bangs them as 9,600 8N1 on OUT0
and the host reads them on RXD.

```text
location   $4E, ICAO[4], CHECK
pause      $50, $00 $00 $00 $00, CHECK      ->  50 00 00 00 00 F5
```

The four code bytes are uppercase ASCII. `CHECK` is the XOR of seed `$A5`,
the marker, and the four payload bytes. A zero payload cannot collide with
a location request, because the ICAO editor only ever emits `A`..`Z`.

### Transmit timing

```text
bit period    186 cycles, 9622.4 baud at 1.789773 MHz
mark guard    800 us nominal before the first start bit, 854 us measured
frame         7.2 ms
inter-byte    at least one full stop bit of mark
line rests at break, which read_controller and sample_line already leave
```

OUT0 high is mark and OUT0 low is space, so no inverter is needed in this
direction.

The transmit routine is 64-byte aligned because a delay loop straddling a
page boundary would silently drop the bit period to 8170 baud.
`tools/verify_tx_timing.py` checks it at its linked address for all 256
byte values, and `tools/verify_frame_bytes.py` demodulates the ROM's own
writes to `$4016` and compares the recovered bytes against the server's
`request_bytes()`, so the two sides are checked against each other rather
than against a restatement of the rule.

### Pause ownership

Select navigation is acted upon only during the guaranteed post-scene
display window of 360 fields (about 6.00 seconds at 60 Hz). The server
uses a 9.500-second scene-start interval, which leaves about 0.73 seconds
beyond the worst case of a maximum identity packet, a maximum scene, their
byte guards and chunk gaps, four display commits, and the complete window.

The ROM remains in framed packet receive mode while `pause_waiting` is set.
It does not expose the ICAO editor merely because Select was pressed. A
valid pause request stops the old scheduler, and the server replies with
the zero-record identity packet described below.

## Host-to-NES packets

```text
offset  size  field
0       1     marker      $A5
1       1     type        $01 scene, $02 identity, or $03 location result
2       1     version     $02
3       1     sequence    wraps modulo 256
4       1     type-specific flags
5       1     type-specific count
6       1     payload length
7       N     type-specific records
7+N     2     CRC-16/CCITT-FALSE, high byte first
```

CRC-16/CCITT-FALSE uses polynomial `$1021`, initial value `$FFFF`, no
reflection, and no final XOR. It covers `type` through the final payload
byte; the `$A5` marker and two transmitted CRC bytes are excluded. The
standard `123456789` check value is `$29B1`.

### Byte pacing

The host writes and flushes one byte at a time with a 5 ms guard between
bytes. Every eighth packet byte is instead followed by a 30 ms chunk gap,
so the ROM has room to wait for vblank and repaint the selection during a
packet. Both sides count the marker as byte 1, and no gap follows the last
byte. The ROM finds the boundary by counting bytes rather than timing the
line, because detecting a long gap would mean editing the hardware-proven
start-bit hunt inside `receive_byte`.

The server's `--chunk-bytes` and `--chunk-gap` control this and default to
8 and 0.030. `--chunk-bytes 0` is unsupported against the released ROM:
it can drop packet bytes and surface as CRC failure whenever controller
work consumes the missing gap.

## Scene packet `$01`

The compact scene packet is at most 81 bytes. Each nine-byte record is:

```text
SLOT_FLAGS, X, Y, TRACK, ALT_LO, ALT_HI, SPEED, VERTICAL_RATE, DISTANCE
```

- `SLOT_FLAGS` bits 0..2 select stable aircraft slot 0..7.
- Bit 3 means track is unavailable, bit 4 altitude is unavailable, bit 5
  speed is unavailable, and bit 6 marks an alert target. Bit 7 is reserved
  and zero.
- `X,Y` are final local NES coordinates. The current server emits 0..143,
  centred at `(72,72)`, using 71/9 pixels per nautical mile and clipping at
  radius 71. The receiver retains the 0..159 validation bound. The NES does
  no geodesy or trigonometry.
- `TRACK` maps 0..255 to 0..<360 degrees. The NES rounds it to one of
  eight 45-degree marker stems.
- `ALT_LO,ALT_HI` are little-endian unsigned altitude in hundreds of feet.
- `SPEED` is groundspeed in knots, clipped to 0..255.
- `VERTICAL_RATE` is signed two's-complement hundreds of feet per minute,
  limited to -99..+99. `$80` means unavailable.
- `DISTANCE` is tenths of a nautical mile, 0..99. `$FF` means unavailable.

Scene flag bit 0 is stale, bit 1 truncated, bit 2 upstream down, bit 3 bad
data, and bit 4 bad location. Bits 5..7 are reserved.

## Identity packet `$02`

Callsign, aircraft type, registration, squawk, and emitter category come
from the same raw ADS-B records already filtered and positioned by the
pinned C64U code. They are carried separately so unchanged strings do not
inflate every motion update. Identity flags must be zero. Each 25-byte
record is:

```text
SLOT, CALLSIGN[8], TYPE[4], REGISTRATION[6], SQUAWK[4], CATEGORY[2]
```

- `SLOT` is 0..7 and must be unique within the packet.
- `CALLSIGN` is eight uppercase ASCII characters, right-padded with spaces.
- `TYPE` is the four-character ICAO aircraft type, right-padded with
  spaces.
- `REGISTRATION`, `SQUAWK`, and `CATEGORY` are likewise fixed-width and
  space-padded. Missing upstream values remain blank.
- Allowed bytes are `A`..`Z`, `0`..`9`, space, and hyphen.
- A full eight-slot snapshot is 209 bytes including header and CRC.

Identity sequence numbers do not participate in motion-scene gap detection.
The sender transmits a full identity snapshot at startup and another
snapshot or partial update when a stable slot changes. Empty space-padded
fields clear a slot's displayed metadata.

A zero-record identity packet is the pause acknowledgement while the ROM
has both `navigation_requested` and `pause_waiting` set. After its header
and CRC validate, the ROM may enter the ICAO editor. At all other times the
same legal packet remains the existing no-op controller/display heartbeat.

## Location-result packet `$03`

The host resolves the request against the pinned C64U worldwide
OurAirports cache and returns one 13-byte packet before radar data:

```text
flags=0 accepted, flags=1 invalid
count=1
length=4
payload=the same four uppercase ICAO letters
```

The NES rejects a result whose payload does not match its submitted code
(surfaced as `ERROR 4`). A valid result switches from the startup screen
to the radar and resets scene sequence state. An invalid result returns to
the editor with `INVALID AIRPORT`. Location-result sequence numbers do not
participate in motion-scene sequencing.

The server leaves 300 ms after receiving a request for the reverse channel
to settle before it sends this packet.

## Receiver behavior

- A valid identity packet atomically updates callsign/type tiles in its
  own vblank and does not change scene sequence state.
- A location-result packet is CRC-protected and cannot select a different
  code from the one entered on the NES.
- A valid first scene establishes scene sequence state.
- An exact sequence duplicate is ignored.
- A sequence gap is rejected and shown as `ERROR 5`. The receiver
  resynchronizes sequence state to the rejected packet so the next
  sequential scene can be accepted.
- A bad CRC or malformed header cannot change OAM or the displayed target
  count. The old complete scene remains visible.
- Bytes before `$A5` are ignored, allowing marker resynchronization.

The receiver's rejection reason is visible in the LINK field:

```text
ERROR 1   UART stop-bit/framing failure
ERROR 2   packet type, version, flags, count, or length failure
ERROR 3   CRC-16 mismatch
ERROR 4   scene or identity record validation, or location-result mismatch
ERROR 5   scene sequence gap or out-of-order packet
```

The number surfaces an error path the receiver already had. It does not
weaken any check.

Visible link-state semantics, including the four-state `IDLE`/`RECEIVING`
split and what `WAITING` clears, are in `LINK_STATES.md`. None of that
changes the packet envelope or CRC protocol.
