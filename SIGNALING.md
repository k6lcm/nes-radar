# NES Radar signaling reference

This document specifies the electrical, timing, framing, packet, and
link-ownership contract between the NES ROM and the host server. It is a
specification of the working link, not a history of the experiments that led
to it. See [`CHANGELOG.md`](CHANGELOG.md) for what changed between releases.

The implementation is split between
[`nes_radar/nes/nes_radar_scope_v3.s`](nes_radar/nes/nes_radar_scope_v3.s),
[`server/src/nes_radar_server.py`](server/src/nes_radar_server.py),
[`server/src/scene_protocol.py`](server/src/scene_protocol.py),
[`server/src/nes_uart_request.py`](server/src/nes_uart_request.py) (the
reverse-channel decoder), and
[`server/src/nes_icao_request.py`](server/src/nes_icao_request.py) (the
shared request types).

## Validation status

Real-hardware acceptance covers an **NTSC NES**, an **FT232R-compatible 5 V
cable**, and the **macOS server**. PAL compatibility is not claimed. Windows
and Linux use the same Python signaling code but remain the experimental host
path until separately accepted on hardware.

## Wiring and electrical behavior

Make all connections with the NES powered off and USB unplugged.

| 5 V FTDI lead | NES controller port 2 | Connection |
|---|---|---|
| GND | pin 1, GND | direct |
| RXD | pin 3, OUT0/LATCH | through its own 1 kOhm series resistor |
| TXD | pin 4, D0 | through a separate 1 kOhm series resistor |
| VCC +5 V | none | disconnected and insulated |
| CTS# | none | disconnected and insulated |
| RTS# | none | disconnected and insulated |

Two separate 1 kOhm resistors, one in each signal direction. RXD and TXD are
not joined. A correct cable measures approximately 1 kOhm on each signal and
approximately 2 kOhm through the two-resistor loop.

Identify every lead by its signal name and by continuity, never by wire
color. Serial-adapter and controller-extension cables are not standardized
on any color scheme.

Electrical facts:

- Use a **5 V USB-to-TTL** adapter. A 3.3 V transmitter is not guaranteed to
  meet the HIGH threshold of every 5 V NES input buffer.
- Do not use true RS-232 voltage levels. Except for ground, their positive and
  negative swings are electrically incompatible with the NES.
- Never connect the adapter's +5 V output to the NES +5 V pin. That can
  connect or back-power two independent supplies.
- The 1 kOhm series resistors limit fault current during a miswire,
  contention, or the common case where USB is powered while the NES is off.
  Neither materially degrades the 9,600-baud signal.
- The NES controller-port input buffer inverts D0. The ROM inverts bit 0
  after reading `$4017`, restoring normal UART polarity in software.
- The reverse direction needs no inverter: OUT0 high is UART mark, OUT0 low
  is space.

A hardware-accepted FT232R adapter and cable idle at approximately 5.2 V on
TX. Other serial adapters can differ in level, latency, and timing even when
their APIs look the same.

### Upgrading from a 0.3.1 cable

The reverse channel moved from OUT0-to-CTS pulses to OUT0-to-RXD UART with
0.4.3. OUT0 now needs its own series resistor. With the NES powered off and
USB unplugged:

1. Remove OUT0 from CTS.
2. Add a 1 kOhm resistor in series between OUT0 and RXD.
3. Leave the existing 1 kOhm resistor between D0 and TXD in place.
4. Confirm CTS, RTS, and VCC are disconnected and individually insulated.
5. Verify orientation and continuity before power.

## Host-to-NES transport: 9,600-baud UART

The server opens the adapter as:

```text
9600 baud, 8 data bits, no parity, 1 stop bit (8N1)
hardware flow control off
software flow control off
idle HIGH
```

UART bytes are sent in the standard order: one LOW start bit, eight data
bits least-significant bit first, and one HIGH stop bit. CTS is not
connected.

The NES receiver is a calibrated, cycle-timed 6502 routine. It waits for a
HIGH idle level followed by a LOW start bit, samples the eight data bits,
and rejects the byte if the stop-bit sample is LOW. The sampling primitive
is hardware-proven and should not be casually edited or interleaved with
unbounded work.

For every sample the ROM uses the established controller-read sequence:

1. write 1 then 0 to `$4016`;
2. perform the fixed settling instructions;
3. read both `$4016` and `$4017`;
4. take D0 from `$4017` bit 0 and invert it.

Writing `$4016` also creates short OUT0 activity of about 2 us per strobe.
The host's reverse-channel decoder cannot be fooled by it: a 2 us pulse is
about 52 times too narrow to frame a 9,600-baud bit, and measured strobes
produce zero bytes at the host.

### Byte guard

The server writes and flushes one byte at a time, then leaves a **5 ms
guard** before the next byte. The ROM uses that already-budgeted quiet time
for controller-1 scanning without altering the calibrated UART sample loop.

With 8N1 framing and the default guard, one wire byte occupies approximately
6.04 ms: 1.04 ms of UART bits plus 5 ms of guard. The guard is part of the
transport, not optional padding to remove for throughput.

### Chunk gaps

Every eighth byte of a packet is followed by a **30 ms gap** instead of the
5 ms guard, controlled by the server's `--chunk-bytes` and `--chunk-gap`.
Both sides count the marker as byte 1, so the gaps fall after packet bytes
8, 16, 24 and so on, and no gap follows the last byte.

This exists because a PPU write has to happen inside vblank, and vblank
comes around every 16.7 ms. Five milliseconds is not long enough to wait for
one, so before chunk gaps the ROM could read the controller during a packet
but never act on it. Thirty milliseconds covers the worst case: a full frame
of vblank waiting plus about 1.3 ms of writing.

The ROM finds the boundary by counting bytes, not by timing the line. That
is deliberate: detecting a long gap would mean changing the start-bit hunt
inside `receive_byte`, and that routine's sampling phase is hardware-proven
and fails silently when disturbed.

### Receive-phase display heartbeat

Once the protected 360-field display window and four display commits have
finished, the server uses otherwise idle time before the next scene to send a
single `$5A` byte every 25 ms. This byte is outside the `$A5` packet envelope.
The ROM accepts it only in the marker hunt, advances the existing paired-sprite
OAM priority once, and resumes listening. No sprite pattern, position, traffic
record, sequence state, freshness state, or CRC packet is changed.

The server leaves 25 ms after every display heartbeat, covering the ROM's
worst-case vblank wait and OAM DMA, and stops heartbeats before the next packet
deadline. A legacy ROM safely ignores `$5A` as pre-marker noise; the animation
improvement requires the matching ROM and server.

Cost, measured on the reference host: a 72-byte scene goes from 0.394 s to
0.589 s and a 209-byte identity packet from 1.130 s to 1.788 s. In exchange
the selection repaints about every 73 ms during reception.

After opening a serial port, the server forces break off, sets TX idle HIGH,
clears the output buffer, and waits 20 ms before signaling. Cleanup again
requests TX idle HIGH before closing the port.

## Host-to-NES packet envelope

Every packet uses this envelope:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 1 | marker `$A5` |
| 1 | 1 | type: `$01` scene, `$02` identity, `$03` location result |
| 2 | 1 | protocol version `$02` |
| 3 | 1 | sequence, modulo 256 |
| 4 | 1 | type-specific flags |
| 5 | 1 | type-specific record count |
| 6 | 1 | payload length in bytes |
| 7 | N | payload |
| 7+N | 2 | CRC-16, high byte first |

The CRC is CRC-16/CCITT-FALSE:

```text
polynomial:  0x1021
initial:     0xFFFF
reflected:   no
final XOR:   none
check value: 0x29B1 for ASCII "123456789"
```

It covers `type` through the final payload byte. The `$A5` marker and the
two transmitted CRC bytes are excluded.

Bytes before `$A5` are ignored, which lets the receiver regain packet
alignment. Once a marker is found, the ROM validates UART framing, type,
version, flags, count, length, CRC, and the type-specific records before
changing the visible scene.

### Scene packet (`type $01`)

A scene contains zero through eight 9-byte motion records and is at most 81
bytes on the wire:

```text
SLOT_FLAGS, X, Y, TRACK, ALT_LO, ALT_HI, SPEED, VERTICAL_RATE, DISTANCE
```

`SLOT_FLAGS` uses:

| Bit | Meaning |
|---:|---|
| 0..2 | stable slot 0..7 |
| 3 | track unavailable |
| 4 | altitude unavailable |
| 5 | speed unavailable |
| 6 | alert target |
| 7 | reserved, must be zero |

Record fields:

- `X,Y` are host-computed NES-local coordinates. The current server emits
  0..143 around `(72,72)` at 71/9 pixels per nautical mile and clips to
  radius 71; the receiver's validation ceiling remains 159.
- `TRACK` maps 0..255 to 0..<360 degrees and is rounded on the NES to one
  of eight directions.
- `ALT_LO,ALT_HI` are a little-endian unsigned altitude in hundreds of feet.
- `SPEED` is groundspeed in knots, clipped to 0..255.
- `VERTICAL_RATE` is signed two's-complement hundreds of feet per minute in
  -99..+99; `$80` means unavailable.
- `DISTANCE` is tenths of a nautical mile in 0..99; `$FF` means unavailable.

Scene flags are:

| Bit | Mask | Meaning |
|---:|---:|---|
| 0 | `$01` | upstream scene is stale |
| 1 | `$02` | more targets existed than could be sent |
| 2 | `$04` | upstream service is down |
| 3 | `$08` | upstream data is bad |
| 4 | `$10` | location is bad |
| 5..7 |  | reserved, must be zero |

Only scene packets participate in motion sequence checking. The first
accepted scene establishes the sequence. An exact duplicate is ignored. A
gap or out-of-order value is rejected as an error, but the rejected sequence
becomes the recovery point so the following sequential scene can be
accepted.

### Identity packet (`type $02`)

Identity metadata is sent separately so unchanged strings do not inflate
every motion update. A packet holds zero through eight 25-byte records and
is at most 209 bytes:

```text
SLOT, CALLSIGN[8], TYPE[4], REGISTRATION[6], SQUAWK[4], CATEGORY[2]
```

Slots must be unique and in 0..7. Text is uppercase, fixed-width,
space-padded, and restricted to `A-Z`, `0-9`, space, and hyphen. Empty
fields clear the corresponding displayed metadata. Identity flags must be
zero.

Identity sequences do not affect scene sequence tracking. A CRC-valid
identity packet updates identity tiles atomically in its own vblank.

A legal zero-record identity packet is also the pause acknowledgement, but
only while the ROM has an outstanding Select/navigation pause. Otherwise it
remains a harmless no-op heartbeat.

### Location-result packet (`type $03`)

The server answers an ICAO request with one 13-byte packet:

```text
flags:   0 = accepted, 1 = invalid
count:   1
length:  4
payload: the requested four uppercase ICAO letters
```

The ROM requires the returned code to match the code it submitted. An
accepted result opens the radar and resets scene sequence state. A rejected
result returns to the editor with `INVALID AIRPORT`. Location-result
sequences do not participate in scene sequencing.

## NES-to-host transport: 9,600-baud UART on RXD

The ROM bit-bangs ordinary 9,600 8N1 UART on OUT0 and the host reads it as
RXD data. Only the modulation is the reverse of the forward path: OUT0 high
is mark, low is space.

### Frames

Both requests are six bytes: a marker, four payload bytes, and an XOR
checksum seeded with `$A5` over the marker and payload.

```text
location   4E, four ICAO letters A-Z, checksum
pause      50, 00 00 00 00, checksum            ->  50 00 00 00 00 F5
```

Worked examples, taken from the cycle-accurate verifier and from a real
console capture:

```text
KJFK   4E 4B 4A 46 4B E7
KSBA   4E 4B 53 42 41 F0
pause  50 00 00 00 00 F5
```

A zero payload cannot collide with a location request because the ICAO
editor only ever emits `A-Z`.

### Transmit timing

The NES has no UART hardware, so the routine is cycle-counted:

```text
bit period      186 cycles, every bit of every byte
baud            9622.4, 0.23 percent fast at the 1.789773 MHz NTSC rate
mark guard      800 us nominal before the first start bit, 854 us measured
frame           7.2 ms
inter-byte      at least one full stop bit of mark
line left at    break, as read_controller and sample_line already leave it
```

A location request takes about 7.2 ms. The 6502 cannot receive and transmit
at once, so the console is deaf for the duration; that window is short
enough not to matter in practice.

The transmit routine's timing depends on its own address. Both delay loops
are three bytes and a taken branch costs an extra cycle across a page
boundary, so a loop straddling a page would run the bit period from 186
cycles to 219, which is 8170 baud. The routine is 64-byte aligned to
prevent that, and `nes_radar/tools/verify_tx_timing.py` re-checks it at its
linked address for all 256 byte values. The failure mode is silent: the ROM
still sends and the host still sees bytes, and some fraction of them are
wrong. Do not move or edit around this routine without re-running that
tool.

### What the host actually sees

The decoder is written against three measured behaviors, not against an
ideal wire.

**Break zeros around every burst.** The ROM rests OUT0 low, which is a
break, and the FT232R reports a break as a `0x00`. Both edges produce at
least one, so a six-byte frame arrives padded with break bytes at each end:

```text
00 4E 4B 53 42 41 F0 00   00 4E 4B 53 42 41 F0 00
```

They are treated as ordinary noise and scanned past.

**Controller strobes are silence, not noise.** At about 2 us they are far
too narrow to frame a bit, and measured strobes produced zero bytes at the
host.

**Starting mid-frame is possible.** Both markers sit inside the ASCII
letter range, so a scanner that begins reading partway through a location
frame can mistake a payload letter for a marker. Resync is therefore
byte-at-a-time and forward: a checksum failure advances one byte rather
than discarding the buffer, because a good frame is often sitting one byte
later.

The checksum alone is a weak filter at six bytes, so the payload is
validated too. A location payload must be four letters `A-Z`, which is all
the ICAO editor can emit, and a pause payload must be four zeros.

### Decoder behavior

```text
poll interval     2 ms
burst gap         250 ms of quiet ends a burst and discards its residue
buffer ceiling    256 bytes
```

The FTDI latency timer is 16 ms, so a 7 ms frame lands in one or two of its
windows; the 250 ms burst gap is generous against the roughly 32 ms worst
case for a frame split across two windows. Discarding a stale partial burst
stops a leftover byte from pairing with the head of the next burst to form
a frame that was never sent.

The reader's buffer deliberately outlives a single call. One read can
return two complete bursts — the first real console capture did exactly
that — and a reader that rebuilt its buffer per call would return the first
frame and silently drop the second.

## Scheduling and ownership

The calibrated receiver cannot safely share arbitrary work with serial
sampling, so the server and ROM cooperate around explicit quiet windows.

- The default scene-start interval is **9.500 seconds**.
- After accepting a scene, the ROM owns a **360-field display window**
  (about 6.00 seconds at 60 Hz) for four display commits, controller
  handling, and sprite animation.
- The server enforces a minimum interval that includes the maximum scene
  and the maximum identity packet, their UART time and byte guards, one
  chunk gap per chunk edge, four video fields, the 360-field window, and a
  50 ms safety margin. The 9.500-second default leaves about 0.73 seconds
  beyond the worst case.
- `DISPLAY_WINDOW_FRAMES` appears in both `nes/nes_radar_scope_v3.s` and
  `nes_radar_server.py` and the two must agree.
- Select is acted upon in this guaranteed post-scene window. Its framed
  request causes the server to stop the old scheduler before another scene
  can begin.
- A changed identity snapshot is sent before its scene. The server leaves a
  50 ms settling gap between the identity packet and the following scene.
- After receiving a request, the server leaves 300 ms for the reverse
  channel to settle before returning the location-result packet.

These timings are part of the working link contract. Increasing throughput
or moving controller/display work into the byte receiver requires new
hardware acceptance.

## Receiver integrity and visible state

The NES commits only complete, validated information:

- bad UART framing, header values, CRC, records, or scene sequence produce
  an error state;
- a damaged packet never replaces the last complete scene;
- valid identity changes are applied atomically;
- an accepted scene swaps a complete motion snapshot into the display;
- exact scene duplicates do nothing;
- marker scanning allows recovery after line noise or a discarded packet.

Four link states are visible in the `LINK` field:

- `IDLE`: a fresh, CRC-valid scene was accepted less than ten seconds ago,
  was not marked stale, and the ROM is inside its display window.
- `RECEIVING`: the display window has expired and the ROM is listening to
  the wire. The controller works here, serviced from the chunk gaps and
  from the marker hunt. Host display heartbeats keep the ordinary OAM-priority
  rotation moving without changing the paired aircraft sprites.
- `WAITING`: startup, an accepted upstream-stale scene, or ten seconds
  without any valid packet. Only the scene sequence state is cleared; the
  last complete scene stays on screen.
- `ERROR 1` through `ERROR 5`: the receiver's reason for rejecting a
  packet.

```text
ERROR 1   UART stop-bit/framing failure
ERROR 2   packet type, version, flags, count, or length failure
ERROR 3   CRC-16 mismatch
ERROR 4   scene or identity record validation, or location-result mismatch
ERROR 5   scene sequence gap or out-of-order packet
```

`WAITING` and `ERROR` own the link field outright and are not overwritten
when the display window expires. Static radar graphics, range, airport, and
table slot labels always remain visible.

Transport activity and data freshness are separate: any CRC-valid packet
resets the no-packet timer, but an identity heartbeat cannot make stale
ADS-B scene data look current.

Full state semantics are in
[`nes_radar/LINK_STATES.md`](nes_radar/LINK_STATES.md).

## Normal transaction sequence

```text
NES editor                 server/FTDI                 NES receiver
    |                           |                           |
    |-- ICAO request ---------->|                           |
    |                           |-- location result ------->|
    |<---------------- accepted/rejected -------------------|
    |                           |                           |
    |                           |-- identity snapshot ----->|
    |                           |-- scene ----------------->|
    |<---------------------- radar display -----------------|
    |                           |                           |
    |-- Select pause request -->|                           |
    |                           |-- empty identity ack ---->|
    |<----------------------- ICAO editor ------------------|
```

## Validation boundary and known operating limits

- Real-hardware acceptance covers an **NTSC NES**, an
  **FT232R-compatible 5 V cable**, and the **macOS server**.
- PAL compatibility is not claimed. Some PAL consoles have additional
  controller-port protection diodes.
- Windows and Linux use the same Python signaling code, but remain the
  experimental host path until separately accepted on hardware.
- Other USB serial chipsets may work but have not inherited FT232R
  electrical or timing validation.
- USB detach/reattach recovery exists in the server lifecycle, but
  mid-session reconnect has not completed hardware acceptance.
- If the server process is restarted while the ROM is already on the scope
  or at `LINK WAITING`, reload the ROM before starting a new session. Cold
  resynchronization from that state is not currently supported.
- A successful host write proves only that bytes reached the adapter. It
  does not prove that the NES received them; `LINK RECEIVING` and
  `LINK IDLE` are the end-to-end indication.
- An intermittent `LINK ERROR` has been observed on hardware and recovers
  automatically on later valid traffic. The receiver's integrity guarantees
  hold throughout: a rejected packet never replaces the last complete
  scene. See the known-issue note in `README.md`.

When changing the transport, preserve the current executable/ROM pair as
the known-good reference and repeat real-console acceptance. Offline packet
tests alone cannot validate controller-port voltage levels, USB latency, or
the 6502's cycle-timed sampling margin.
