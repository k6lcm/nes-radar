# NES Radar Server 0.4.3

Paired with the NES Radar V0.4.3 ROM.

## Run it

**macOS.** Extract this zip, then double-click `start_nes_radar_server.command`
or run it from a terminal:

```text
./start_nes_radar_server.command
```

The binary is ad-hoc signed but not notarized, so the first launch is
blocked. Open **System Settings → Privacy & Security**, find the message
about `nes-radar-server`, and click **Open Anyway**. Once, then normal.

**Portable Python** (Windows, Linux). Needs Python 3.9+ and pyserial 3.5:

```text
python3 -m pip install -r requirements.txt
python3 start_nes_radar_server.py
```

The `.command` and `.bat` launchers just pass arguments through to the
server.

## Options

```text
--self-test    offline packaging check; run before wiring anything up
--help         all flags, including --port and the chunked-send controls
--version      prints 0.4.3
```

The chunked-send defaults (`--chunk-bytes 8`, `--chunk-gap 0.030`) are what
the V0.4.3 ROM expects; leave them alone unless you know why you'd change
them.

Stop with Ctrl-C. Needs outbound HTTPS to `opendata.adsb.fi`.

## More

Full project docs — hardware wiring, protocol, link states, upgrading from
0.3.1 — live in the repository:
[k6lcm/nes-radar](https://github.com/k6lcm/nes-radar). Third-party sources
and licenses are in `licenses/` and `THIRD_PARTY_NOTICES.md`.
