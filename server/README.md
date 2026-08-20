# NES Radar Server 0.4.4

Paired with the NES Radar V0.4.4 ROM.

## Run it

**macOS.** Extract this zip, then double-click `start_nes_radar_server.command`
or run it from a terminal:

```text
./start_nes_radar_server.command
```

The binary is ad-hoc signed but not notarized, so the first launch is
blocked. Open **System Settings → Privacy & Security**, find the message
about `nes-radar-server`, and click **Open Anyway**. Once, then normal.

**Portable Python** (Windows, Linux, or source development on macOS). Needs
Python 3.9+. Install the pinned runtime dependencies in a virtual environment;
this also works with Homebrew's externally managed Python:

```text
# macOS or Linux
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python start_nes_radar_server.py
```

```text
# Windows Command Prompt
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python start_nes_radar_server.py
```

The `.command` and `.bat` launchers just pass arguments through to the
server.

## Options

```text
--self-test    offline packaging check; run before wiring anything up
--help         all flags, including --port and the chunked-send controls
--version      prints 0.4.4
```

The chunked-send defaults (`--chunk-bytes 8`, `--chunk-gap 0.030`) are what
the V0.4.4 ROM expects; leave them alone unless you know why you'd change
them.

The matching server also sends one-byte display heartbeats in the idle part of
`LINK RECEIVING`. They keep the ROM's existing paired-sprite priority rotation
moving and stop before the next traffic packet.

Stop with Ctrl-C. Needs outbound HTTPS to `opendata.adsb.fi`. Native builds
carry their own trusted CA certificate bundle; users do not need to install
Python certificates or set `SSL_CERT_FILE`.

## More

Full project docs — hardware wiring, protocol, link states, upgrading from
0.3.1 — live in the repository:
[k6lcm/nes-radar](https://github.com/k6lcm/nes-radar). Third-party sources
and licenses are in `licenses/` and `THIRD_PARTY_NOTICES.md`.
