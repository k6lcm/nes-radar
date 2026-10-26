# Changelog

## 0.6.0

- **The buttons follow nesp32's cartridge.** A looks the airport up, as
  Start does. On the scope B goes back to the editor, where Select used to.
  On the cartridge, Select is its menu from the editor and from the scope.
  B is only ever back a step and never leaves the program, so pressing it
  again and again can't. A and B no longer move along the four letters:
  Left and Right do.
- The splash says `V0.6.0`.

## 0.5.0

- **Needs a [nesp32](https://github.com/Armitage64/nesp32) on controller
  port 2.** The FTDI cable and the computer-side server are gone: the
  nesp32 fetches traffic from adsb.fi itself, over Wi-Fi, and looks up
  where an airport is on Wikidata.
- The 0.4.x cable and server stay available on the
  [`legacy/ftdi-0.4.x`](https://github.com/k6lcm/nes-radar/tree/legacy/ftdi-0.4.x)
  branch and the 0.4.4 release.
- The scope polls the nesp32 once a frame instead of listening to a
  stream, so there are no chunk gaps, no quiet window, no heartbeat and no
  pause request. Select goes straight to the editor, and the sprites keep
  rotating whatever the link is doing.
- The editor starts at the last airport the nesp32 found, which it keeps
  over power-off, instead of KSBA.
- The `LINK` field says `LIVE` when the scope is healthy, and `LIVE...`, its
  dots going one, two, three for half a second, each time new data comes in:
  a scene, or its aircraft's names. Errors are words instead of numbers:
  `NO ANSWER`, `BAD DATA`, `ADSB DOWN`. `IDLE`, `RECEIVING` and the
  numbered `ERROR 1`–`ERROR 5` were about the cable's packets and are gone.
- The cable's receiver, sender, packet parser and their state are removed
  from the ROM.
- New editor messages: `REQUESTING`, `LOOKUP FAILED`, `NO NESP32 ANSWER`,
  `NESP32 NO WI-FI`, `UPDATE NESP32`.
- The nesp32's link library is vendored in `nes_radar/vendor/nesp32`, so
  the ROM still builds with cc65 alone.
- The splash says `V0.5.0`.


## Server 0.4.4-build2

- Remains paired with the 0.4.4 ROM and does not change the serial protocol.
- Refreshes the bundled OurAirports ICAO database at startup when the newest
  cached copy is at least 30 days old.
- Keeps the existing database when both download sources fail and reports the
  refresh error in the server log.
- Uses the OurAirports GPS code when its ICAO field is blank, so airports such
  as KCMA remain available after an automatic refresh.
- Adds KCMA to the bundled offline airport database.

## 0.4.4

- Paired 16×16 aircraft targets now keep flickering through `LINK RECEIVING`.
  In its known-idle time the server sends a one-byte display heartbeat that
  advances the ROM's OAM-priority rotation and nothing else; scene data,
  sequence state, and CRCs are untouched.
- Needs the matching 0.4.4 ROM and 0.4.4 server for the visible fix. A 0.4.4
  server against a 0.4.3 ROM is safe — the heartbeat byte is ignored as
  pre-marker noise — but the sprites will still freeze on one priority in
  `RECEIVING`.
- There are no additional wiring, cartridge, or protocol changes from 0.4.3.
  Calibrated receive and reverse-UART routines and the sprite CHR are
  identical to a clean 0.4.3 build.

## 0.4.3

- Reverse channel is now 9,600 8N1 UART on OUT0, read on the host as RXD.
  Replaces the pulse-width channel that 0.3.1 read as FTDI CTS. A location
  request takes about 7 ms instead of about 4.3 seconds.
- **Requires a two-resistor cable.** OUT0 goes through its own 1 kΩ resistor
  to RXD; D0 keeps its 1 kΩ resistor to TXD. See `SIGNALING.md` for the full
  pinout and an upgrade checklist for an existing 0.3.1 cable.
- Forward path holds a 30 ms chunk gap after every eighth packet byte, so the
  ROM can wait for vblank and repaint the selection during reception. Display
  window drops from 448 to 360 fields to pay for it.
- Four LINK states instead of three: `IDLE` while the ROM owns the display
  window, `RECEIVING` while it is listening to the wire (the controller
  works here), `WAITING`, `ERROR`. `WAITING` no longer blanks the scope; it
  leaves the last complete scene up.
- `ERROR` shows the receiver's own numeric reason as `ERROR 1` through
  `ERROR 5` (framing, header, CRC, record validation, sequence).
- Source and native server builds carry a pinned Certifi CA bundle for HTTPS;
  users do not need to install certificates or set `SSL_CERT_FILE`.
- macOS Universal binary rebuilt with python.org's Python 3.14.7.

## 0.3.1

- Baseline hardware-accepted release: pulse-width reverse channel on CTS,
  one-resistor cable, 448-field display window, three LINK states.
- Source is tagged [`0.3.1`](https://github.com/k6lcm/nes-radar/tree/0.3.1); downloads live on that tag's [Release entry](https://github.com/k6lcm/nes-radar/releases).
