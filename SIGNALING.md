# NES Radar signaling reference

This document describes the signaling that the current NES Radar ROM and
server use successfully. It is a specification of the known-good link, not a
history of the experiments that led to it.

The implementation is split between
[`nes_radar/nes/nes_radar_scope_v3.s`](nes_radar/nes/nes_radar_scope_v3.s),
[`server/src/nes_radar_server.py`](server/src/nes_radar_server.py),
[`server/src/scene_protocol.py`](server/src/scene_protocol.py), and
[`server/src/nes_icao_request.py`](server/src/nes_icao_request.py).

## Proven configuration

The released configuration has been accepted on a real NTSC NES with a DTECH
DT-6555 5 V TTL cable (FT232RL-compatible) and the macOS server. The host-to-NES
path runs at 9,600 baud; the NES-to-host path uses deliberately slow,
pulse-width-coded messages.

The known-good electrical path is:

```text
host USB -> 5 V FT232R-compatible TTL cable -> NES controller port 2

host TXD -------------------------------> NES D0       (radar data)
host CTS <------------------------------- NES OUT0     (requests/control)
host GND -------------------------------- NES GND
```

The link is bidirectional, but the two directions are independent protocols.
It is not a conventional two-wire UART: only host-to-NES traffic is UART
framed. NES-to-host traffic is pulse-width coded and observed through CTS.

## Wiring and electrical behavior

Make all connections with the NES powered off and USB unplugged.

| 5 V FTDI lead | NES controller port 2 | Connection |
|---|---|---|
| GND (black on the documented FTDI cable) | pin 1, GND | direct |
| CTS# (brown) | pin 3, OUT0/LATCH | direct |
| TXD (orange) | pin 4, D0 | through a 1 kOhm series resistor |
| VCC +5 V (red) | none | disconnected and insulated |
| RXD (yellow) | none | disconnected and insulated |
| RTS# (green) | none | disconnected and insulated |

Use signal names and continuity, not colors, when the cable differs from the
documented FTDI part. Controller and extension cable colors are not
standardized.

Important electrical facts:

- Use a **5 V USB-to-TTL** adapter. A 3.3 V transmitter is not guaranteed to
  meet the HIGH threshold of every 5 V NES input buffer.
- Do not use true RS-232 voltage levels. Except for ground, their positive and
  negative swings are electrically incompatible with the NES.
- Never connect the adapter's +5 V output to the NES +5 V pin. That can connect
  or back-power two independent supplies.
- The 1 kOhm TXD resistor limits fault current during a miswire, contention, or
  a powered-USB/unpowered-NES condition. It does not materially degrade the
  known-good 9,600-baud signal.
- CTS is connected directly. OUT0 changes slowly in this protocol and the
  direct connection is hardware-proven with the 5 V cable.
- RXD is intentionally unused. The host reads OUT0 as the cable's CTS state,
  not as UART receive data.
- The NES controller-port input buffer inverts D0. The ROM inverts bit 0 after
  reading `$4017`, restoring normal UART polarity in software.

The documented DTECH cable's idle TX level measured 5.192 V. A genuine FTDI
`TTL-232R-5V-WE` is the preferred reproducible replacement. Other serial
adapters can differ in level, latency, and timing even when their APIs look the
same.

## Host-to-NES transport: 9,600-baud UART

The server opens the adapter as:

```text
9600 baud, 8 data bits, no parity, 1 stop bit (8N1)
hardware flow control off
software flow control off
idle HIGH
```

UART bytes are sent in the standard order: one LOW start bit, eight data bits
least-significant bit first, and one HIGH stop bit. CTS is not used as automatic
UART flow control; the server polls it separately for NES control messages.

The NES receiver is a calibrated, cycle-timed 6502 routine. It waits for a HIGH
idle level followed by a LOW start bit, samples the eight data bits, and rejects
the byte if the stop-bit sample is LOW. The sampling primitive is the preserved
hardware-proven timing and should not be casually edited or interleaved with
unbounded work.

For every sample the ROM uses the established controller-read sequence:

1. write 1 then 0 to `$4016`;
2. perform the fixed settling instructions;
3. read both `$4016` and `$4017`;
4. take D0 from `$4017` bit 0 and invert it.

Writing `$4016` also creates short OUT0/CTS activity. The reverse-channel
decoder rejects those ordinary controller strobes because they cannot satisfy
its long preamble and pulse widths.

### Required byte guard

The server writes and flushes one byte at a time, then leaves a **5 ms guard**
before the next byte. The ROM uses that already-budgeted quiet time for
controller-1 scanning without altering the calibrated UART sample loop.

With 8N1 framing and the default guard, one wire byte occupies approximately
6.04 ms: 1.04 ms of UART bits plus 5 ms of guard. The guard is part of the
known-good transport, not optional padding to remove for throughput.

After opening a serial port, the server forces break off/TX idle HIGH, clears
the output buffer, and waits 20 ms before signaling. Cleanup again requests TX
idle HIGH before closing the port.

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

It covers `type` through the final payload byte. The `$A5` marker and the two
transmitted CRC bytes are excluded.

Bytes before `$A5` are ignored, which lets the receiver regain packet alignment.
Once a marker is found, the ROM validates UART framing, type, version, flags,
count, length, CRC, and the type-specific records before changing the visible
scene.

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
  0..143 around `(72,72)` at 71/9 pixels per nautical mile and clips to radius
  71; the receiver's validation ceiling remains 159.
- `TRACK` maps 0..255 to 0..<360 degrees and is rounded on the NES to one of
  eight directions.
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

Only scene packets participate in motion sequence checking. The first accepted
scene establishes the sequence. An exact duplicate is ignored. A gap or
out-of-order value is rejected as an error, but the rejected sequence becomes
the recovery point so the following sequential scene can be accepted.

### Identity packet (`type $02`)

Identity metadata is sent separately so unchanged strings do not inflate every
motion update. A packet holds zero through eight 25-byte records and is at most
209 bytes:

```text
SLOT, CALLSIGN[8], TYPE[4], REGISTRATION[6], SQUAWK[4], CATEGORY[2]
```

Slots must be unique and in 0..7. Text is uppercase, fixed-width,
space-padded, and restricted to `A-Z`, `0-9`, space, and hyphen. Empty fields
clear the corresponding displayed metadata. Identity flags must be zero.

Identity sequences do not affect scene sequence tracking. A CRC-valid identity
packet updates identity tiles atomically in its own vblank.

A legal zero-record identity packet is also the pause acknowledgement, but only
while the ROM has an outstanding Select/navigation pause. Otherwise it remains
a harmless no-op heartbeat.

### Location-result packet (`type $03`)

The server answers an ICAO request with one 13-byte packet:

```text
flags:   0 = accepted, 1 = invalid
count:   1
length:  4
payload: the requested four uppercase ICAO letters
```

The ROM requires the returned code to match the code it submitted. An accepted
result opens the radar and resets scene sequence state. A rejected result
returns to the editor with `INVALID AIRPORT`. Location-result sequences do not
participate in scene sequencing.

## NES-to-host transport: OUT0 pulse widths on CTS

The reverse channel is intentionally slow so it survives USB CTS sampling and
cannot be confused with ordinary controller latch traffic. The server polls
CTS every 1 ms and accepts either electrical polarity.

### ICAO request

The NES sends six bytes, most-significant bit first:

```text
$4E, ICAO[4], CHECK
CHECK = $A5 XOR $4E XOR ICAO[0] XOR ICAO[1] XOR ICAO[2] XOR ICAO[3]
```

The wire shape is:

1. 500 ms idle gap;
2. 200 ms active leader;
3. 200 ms idle separator;
4. for each of 48 bits: 20 ms active means 0 or 60 ms active means 1, followed
   by a 20 ms idle delimiter;
5. 200 ms final idle.

The host's exercised decode windows deliberately allow USB and scheduling
jitter:

| Run | Accepted duration |
|---|---:|
| initial idle gap | at least 350 ms |
| active leader | 140..300 ms |
| idle separator | 140..300 ms |
| bit 0 active pulse | 10..40 ms |
| bit 1 active pulse | 45..85 ms |
| inter-bit idle | 10..45 ms |

The marker, uppercase-letter validation, and XOR check must all pass. A valid
frame also establishes the proved CTS idle polarity used to recognize later
pause requests.

### Select/navigation pause request

The NES does not immediately expose the ICAO editor while the server might
still be transmitting. It first requests exclusive ownership of the link:

```text
500 ms idle, 200 ms active leader, 200 ms idle separator,
100 ms active pause symbol, then idle
```

The server accepts the final active symbol only in the 85..130 ms window and
only with the idle polarity established by a valid ICAO frame. It then stops
the old scope schedule and transmits a zero-record identity packet as the pause
acknowledgement. Only after that CRC-valid acknowledgement does the ROM enter
the editor.

## Scheduling and ownership

The calibrated receiver cannot safely share arbitrary work with serial
sampling, so the server and ROM cooperate around explicit quiet windows.

- The default scene-start interval is **9.500 seconds**.
- After accepting a scene, the ROM owns a **448-field display window** (about
  7.47 seconds at 60 Hz) for four display commits, controller handling, and
  sprite animation.
- The server enforces a minimum interval that includes the maximum scene's
  UART time and byte guards, four video fields, the 448-field window, and a
  50 ms safety margin. The 9.500-second default leaves more than 1.4 seconds
  beyond the current worst-case scene/display work.
- Select is acted upon in this guaranteed post-scene window. Its framed
  preamble causes the server to stop the old scheduler before another scene
  can begin.
- A changed identity snapshot is sent before its scene. The server leaves a
  50 ms settling gap between the identity packet and the following scene.
- After receiving an ICAO request, the server leaves 300 ms for the reverse
  request to settle before returning the location-result packet.

These timings are part of the working link contract. Increasing throughput or
moving controller/display work into the byte receiver requires new hardware
acceptance.

## Receiver integrity and visible state

The NES commits only complete, validated information:

- bad UART framing, header values, CRC, records, or scene sequence produce
  `LINK ERROR`;
- a damaged packet never replaces the last complete scene;
- valid identity changes are applied atomically;
- an accepted scene swaps a complete motion snapshot into the display;
- exact scene duplicates do nothing;
- marker scanning allows recovery after line noise or a discarded packet.

The visible states are:

- `LINK RECEIVING`: a fresh, CRC-valid scene was accepted less than ten seconds
  ago and was not marked stale;
- `LINK WAITING`: startup, an accepted upstream-stale scene, or ten seconds
  without any valid packet;
- `LINK ERROR`: framing, header, CRC, record, sequence, or severe upstream
  failure.

Entering `WAITING` clears sprites, target rows, selected details, target count,
and scene sequence state. Static radar graphics, range, airport, and table slot
labels remain. `ERROR` retains the last complete scene briefly for diagnosis;
continued silence eventually moves to `WAITING` and clears it. A later valid
scene restores `RECEIVING`.

Transport activity and data freshness are separate: any CRC-valid packet
resets the no-packet timer, but an identity heartbeat cannot make stale ADS-B
scene data look current.

## Normal transaction sequence

```text
NES editor                 server/FTDI                 NES receiver
    |                           |                           |
    |-- ICAO pulse frame ------>|                           |
    |                           |-- location result ------->|
    |<---------------- accepted/rejected -------------------|
    |                           |                           |
    |                           |-- identity snapshot ----->|
    |                           |-- scene ----------------->|
    |<---------------------- radar display -----------------|
    |                           |                           |
    |-- Select pause frame ---->|                           |
    |                           |-- empty identity ack ---->|
    |<----------------------- ICAO editor ------------------|
```

## Validation boundary and known operating limits

The following claims are intentionally narrow:

- Real-hardware acceptance covers an **NTSC NES**, the documented
  **FT232R-compatible 5 V cable**, and the **macOS server**.
- PAL compatibility is not claimed. Some PAL consoles have additional
  controller-port protection diodes.
- Windows and Linux use the same Python signaling code, but remain the
  experimental host path until separately accepted on hardware.
- Other USB serial chipsets may work but have not inherited FT232R electrical
  or timing validation.
- USB detach/reattach recovery exists in the server lifecycle, but mid-session
  reconnect has not completed hardware acceptance.
- If the server process is restarted while the ROM is already on the scope or
  at `LINK WAITING`, reload the ROM before starting a new session. Cold
  resynchronization from that state is not currently supported.
- A successful host write proves only that bytes reached the adapter. It does
  not prove that the NES received them; `LINK RECEIVING` is the end-to-end
  indication.

When changing the transport, preserve the current executable/ROM pair as the
known-good reference and repeat real-console acceptance. Offline packet tests
alone cannot validate controller-port voltage levels, USB latency, or the
6502's cycle-timed sampling margin.
