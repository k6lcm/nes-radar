# Changelog

## 0.4.4

- Keep the existing paired 16×16 aircraft sprite-priority rotation moving
  during `LINK RECEIVING`. The server sends a one-byte display heartbeat only
  in the known idle interval before the next packet; sprite artwork and scene
  data are unchanged.

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
