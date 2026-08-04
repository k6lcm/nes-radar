# NES Radar Protocol v2

The host-to-NES path retains v0's length-delimited CRC packets and exact
9600-baud receive primitive. V2 extends only the validated payload records so
the LDV sidebar can show the ADS-B detail fields. The cycle-timed byte receiver,
bit delays, byte guard, and CRC implementation are unchanged.

## NES-to-host ICAO request

After the user presses Start, the NES emits:

```text
$4E, ICAO[4], CHECK
```

The four code bytes are uppercase ASCII. `CHECK` is the XOR of seed `$A5`,
marker `$4E`, and the four letters. Bytes are sent most-significant bit first
using the repository's exercised OUT0 pulse-width convention:

- 500 ms LOW idle gap;
- 200 ms HIGH leader, then 200 ms LOW;
- 20 ms HIGH for bit 0 or 60 ms HIGH for bit 1;
- 20 ms LOW between bits.

The decoder measures transitions and accepts either CTS polarity. Controller-1
poll strobes are too short to match the leader or data pulses.

## NES-to-host Select pause request

After a checksum-valid ICAO request has established CTS idle polarity, Select
emits a framed pause request: 500 ms idle, 200 ms active leader, 200 ms idle
separator, and a 100 ms active pause symbol. The server accepts 85–130 ms for
the final symbol only after the full gap/leader/separator has validated. This
prevents USB-sampled controller latch traffic from imitating Select.

Select navigation is acted upon only during the guaranteed 448-field post-scene
display window. The server uses a 9.500-second scene-start interval, leaving
more than 1.4 seconds after the worst-case scene, four display commits, and the
complete window. The valid preamble stops the old scheduler after about 900 ms.

The ROM remains in framed packet receive mode while `pause_waiting` is set. It
does not expose the ICAO editor merely because Select was pressed.

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
reflection, and no final XOR. It covers `type` through the final payload byte;
the `$A5` marker and two transmitted CRC bytes are excluded. The standard
`123456789` check value is `$29B1`.

## Scene packet `$01`

The compact scene packet is at most 81 bytes. Each nine-byte record is:

```text
SLOT_FLAGS, X, Y, TRACK, ALT_LO, ALT_HI, SPEED, VERTICAL_RATE, DISTANCE
```

- `SLOT_FLAGS` bits 0..2 select stable aircraft slot 0..7.
- Bit 3 means track is unavailable, bit 4 altitude is unavailable, bit 5 speed
  is unavailable, and bit 6 marks an alert target. Bit 7 is reserved and zero.
- `X,Y` are final local NES coordinates. The current server emits 0..143,
  centred at `(72,72)`, using 71/9 pixels per nautical mile and clipping at
  radius 71. The receiver retains the 0..159 validation bound. The NES does no
  geodesy or trigonometry.
- `TRACK` maps 0..255 to 0..<360 degrees. The NES rounds it to one of eight
  45-degree marker stems.
- `ALT_LO,ALT_HI` are little-endian unsigned altitude in hundreds of feet.
- `SPEED` is groundspeed in knots, clipped to 0..255.
- `VERTICAL_RATE` is signed two's-complement hundreds of feet per minute,
  limited to -99..+99. `$80` means unavailable.
- `DISTANCE` is tenths of a nautical mile, 0..99. `$FF` means unavailable.

Scene flag bit 0 is stale, bit 1 truncated, bit 2 upstream down, bit 3 bad
data, and bit 4 bad location. Bits 5..7 are reserved.

## Identity packet `$02`

Callsign, aircraft type, registration, squawk, and emitter category come from
the same raw ADS-B records already filtered and positioned by the pinned C64U
code. They are carried separately so unchanged strings do not inflate every
motion update. Identity flags must be zero. Each 25-byte record is:

```text
SLOT, CALLSIGN[8], TYPE[4], REGISTRATION[6], SQUAWK[4], CATEGORY[2]
```

- `SLOT` is 0..7 and must be unique within the packet.
- `CALLSIGN` is eight uppercase ASCII characters, right-padded with spaces.
- `TYPE` is the four-character ICAO aircraft type, right-padded with spaces.
- `REGISTRATION`, `SQUAWK`, and `CATEGORY` are likewise fixed-width and
  space-padded. Missing upstream values remain blank.
- Allowed bytes are `A`..`Z`, `0`..`9`, space, and hyphen.
- A full eight-slot snapshot is 209 bytes including header and CRC.

Identity sequence numbers do not participate in motion-scene gap detection.
The sender transmits a full identity snapshot at startup and another snapshot
or partial update when a stable slot changes. Empty space-padded fields clear a
slot's displayed metadata.

A zero-record identity packet is the pause acknowledgement in this combined
experiment only while the ROM has both `navigation_requested` and
`pause_waiting` set. After its header and CRC validate, the ROM may enter the
ICAO editor. At all other times the same legal packet remains the existing
no-op controller/display heartbeat.

## Location-result packet `$03`

The host resolves the request against the pinned C64U worldwide OurAirports
cache and returns one 13-byte packet before radar data:

```text
flags=0 accepted, flags=1 invalid
count=1
length=4
payload=the same four uppercase ICAO letters
```

The NES rejects a result whose payload does not match its submitted code. A
valid result switches from the startup screen to the radar and resets scene
sequence state. An invalid result returns to the editor with `INVALID AIRPORT`.
Location-result sequence numbers do not participate in motion-scene sequencing.

Receiver behavior:

- A valid identity packet atomically updates callsign/type tiles in its own
  vblank and does not change scene sequence state.
- A location-result packet is CRC-protected and cannot select a different code
  from the one entered on the NES.
- A valid first scene establishes scene sequence state.
- An exact sequence duplicate is ignored.
- A sequence gap is rejected and shown as an error. The receiver resynchronizes
  sequence state to the rejected packet so the next sequential scene can be
  accepted.
- A bad CRC or malformed header cannot change OAM or the displayed target
  count. The old complete scene remains visible.
- Bytes before `$A5` are ignored, allowing marker resynchronization.

Visible link-state semantics are documented in `LINK_STATES.md`. They do not
change the packet envelope or CRC protocol. In particular, `WAITING` clears
the rendered target state after transport timeout or an accepted upstream-
stale scene, while `ERROR` never commits a damaged packet.
