# NES Radar Server 0.3.1

This server is paired with the NES Radar 0.3.1 ROM. It receives airport
codes from the NES, retrieves nearby traffic from adsb.fi, and sends the radar
scene through the supported controller-port serial adapter.

## Quick start

1. Connect the USB serial/NES controller-port interface.
2. Start the server before pressing Start in the NES airport editor.
3. Select the intended serial device from the numbered list.
4. Enter an ICAO code on the NES and press Start.

With no serial devices attached, the server waits and rescans. It lists every
serial port reported by the operating system, including its description, USB
VID:PID, and serial number when available. It does not restrict the choice by
manufacturer or USB ID.

To bypass the device menu, supply an exact port:

```text
nes-radar-server --port /dev/cu.usbserial-EXAMPLE
nes-radar-server.exe --port COM4
```

The host needs outbound HTTPS access to `opendata.adsb.fi`. Stop the server
with Ctrl-C. Use `--help` for all options, `--version` to show the version, and
`--self-test` for an offline packaging check.

## Changing airports

Keep the same server process running. While the scope is active, press Select.
The return to the ICAO editor takes about one second while the ROM and server
complete a pause handshake. Enter the new code and press Start.

If the entire server process is stopped or restarted while the ROM is already
on the scope or `LINK WAITING`, reload the ROM before starting a new session.
Cold recovery from that state is not supported yet.

## Portable Python source

Python 3.9 or newer is required:

```text
python3 -m pip install -r requirements.txt
python3 start_nes_radar_server.py --self-test
python3 start_nes_radar_server.py
```

On Windows, `py -3` may be used instead of `python3`. The `.command` and `.bat`
launchers forward command-line arguments after dependencies are installed.

The default stream shows aircraft within 9 nautical miles and sends at most
eight targets. The macOS build is ad-hoc signed, but it is not Developer ID
signed or notarized. If macOS blocks it, first try opening it normally, then use
**System Settings → Privacy & Security → Open Anyway**. Hardware acceptance was
performed with an FT232R-compatible interface; other serial hardware may need
separate electrical and timing validation.

See `THIRD_PARTY_NOTICES.md` and `licenses/` for third-party source and license
details. `packaging/` and `requirements-build.txt` are retained so native
executables can be rebuilt from this source tree.
