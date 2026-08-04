# NES Radar

**NES Radar turns a real Nintendo Entertainment System into a live air traffic scope.**

Type any airport's four-letter ICAO code on the NES controller, press Start, and the aircraft actually flying near that airport *right now* appear as moving targets on your TV.

It works for airports worldwide. Point it at your local field and watch the approach traffic line up, or at KLAX and watch it get busy.

![NES Radar scope screen](assets/nes-radar-scope.png)

The NES can't reach the Internet, so a small server on your computer fetches live traffic from [adsb.fi](https://adsb.fi) and streams it down the controller cable. The NES sends your airport choice back up the same cable.

---

## What you need

This is a hardware project, not a download-and-play ROM.

- A real NES and a flash cartridge to load the ROM
- An FTDI USB serial cable, wired to controller port 2 (see below)
- A 1 kΩ resistor
- A computer to run the server — on a Mac it's a self-contained binary with nothing to install; Windows and Linux run from Python source
- An Internet connection

An **FT232R-compatible** adapter is what this project is tested against. The server lists every serial device it finds and lets you pick, but other adapters may behave differently, electrically or in timing.

## Wiring

### Get a 5 V TTL cable

**Connect your vintage NES to your modern computer at your own risk. The authors of this project are not responsible for damage caused by this experimental project.**

Use a **5 V USB-to-TTL serial cable**. The recommended reproducible part is the genuine [FTDI `TTL-232R-5V-WE`](https://ftdichip.com/products/ttl-232r-5v-we/), which uses the wire colors below. Hardware acceptance for this project was done with a **DTECH DT-6555** 5 V TTL cable (FT232RL-compatible), whose idle TX was measured at **5.192 V**. Others may work but use at your own risk.

**Do not use a 3.3 V adapter.** Its 3.3 V TX output is not a reliably guaranteed logic high for every 5 V NES input buffer. A genuine FTDI `TTL-232R-3V3` has 5 V-tolerant inputs but it may not drive the NES reliably. The USB ID `0403:6001` identifies the FT232R family; it does **not** tell you whether a cable is 3.3 V or 5 V.

You can use an old controller cable or purchase a new replacement controller cable or controller extension which can be cut to size.

### Connections

With the NES powered off and USB unplugged, connect to **controller port 2**:

| Cable lead | NES controller port 2 | Connection |
|---|---|---|
| GND — black | pin 1 — GND | direct |
| CTS# — brown | pin 3 — OUT0/LATCH | direct |
| TXD — orange | pin 4 — D0 | **through a 1 kΩ series resistor** |
| VCC +5 V — red | — | **not connected; insulate** |
| RXD — yellow | — | not connected; insulate |
| RTS# — green | — | not connected; insulate |

Plug a normal controller into **port 1** — that's what you use to enter the airport code.

Full port pinout, **viewed looking into the jack on the front of the console**:

```
               .-
pin 1 GND  -- |o\
pin 2 CLK  -- |o o\ -- pin 5 +5V
pin 3 OUT0 -- |o o| -- pin 6 D3
pin 4 D0   -- |o o| -- pin 7 D4
               '--'
```

> **Check your orientation before soldering.** The plug's mating face and its
> wire/solder side are mirrored. Confirm you are counting pins in the direction
> above — not from the back of the connector. See the
> [NESdev controller port pinout](https://www.nesdev.org/wiki/Controller_port_pinout).

> **Go by signal name, not wire color.** The colors above apply only to the
> specified FTDI cable. An original Nintendo controller cable uses different
> colors — including brown for GND — and third-party extension cables may use
> anything. Identify NES-side wires by continuity and pin number, never by color
> alone. See the [NESdev serial cable page](https://www.nesdev.org/wiki/Serial_Cable_Construction).

### Why each line

Both signal wires carry traffic. TXD → D0 is the host-to-NES path that streams the radar scenes. CTS ← OUT0 is the NES-to-host path that sends your ICAO code and the Select button's pause request. Leaving CTS disconnected gets you a scope that never accepts an airport.

The 1 kΩ series resistor on TXD limits current during a miswire, output contention, or — most likely — when the USB cable is powered while the NES is off. It does not meaningfully affect the signal at 9600 baud. CTS needs no resistor with a 5 V cable; the OUT0 pulses are slow and the connection was hardware-tested direct.

NESdev's general-purpose cable ties OUT0 to both RX and CTS. NES Radar reads it on **CTS only** — the NES-to-host signalling is pulse-width timed rather than UART framed, so RXD stays disconnected here. That difference is deliberate.

> Note: the raw NES bit is inverted relative to the connector voltage by the console's controller-port input buffer. This is expected and the protocol accounts for it.

### Before you power anything on

- **Never connect the red +5 V lead to pin 5.** That puts two independent 5 V supplies against each other and can back-power equipment.
- Use a **TTL UART** cable only. Never connect the NES to true RS-232 signalling apart from GND — those swing to ±12 V and will damage it.
- Insulate the red, yellow, and green leads **separately**, so none can touch ground or another signal.
- Verify continuity, and check for shorts to pin 5, before applying power.
- Power down the NES and unplug USB before assembling or changing any wiring.

This wiring was accepted on an **NTSC** NES. Some PAL consoles have additional protection diodes on the controller port; PAL compatibility is not claimed.

## Running the server

### macOS

The macOS build is a self-contained Universal 2 binary — it carries its own Python and pyserial, so there's nothing to install. It is ad-hoc signed but **not notarized**, so macOS will warn you about it.

```
cd NES-Radar-0.3-beta1-macos-universal
xattr -dr com.apple.quarantine .
./start_nes_radar_server.command
```

The `xattr` line clears the quarantine flag macOS puts on files downloaded from the web. Do it only after checking your download against `SHA256SUMS`. If you'd rather not, first try opening the launcher normally, then use **System Settings → Privacy & Security → Open Anyway** if macOS blocks it.

Sanity check before wiring anything up:

```
./nes-radar-server --self-test
```

### Windows and Linux

There is no prebuilt binary for Windows or Linux — both run from the Python source package, which needs:

- **Python 3.9 or newer**
- **pyserial 3.5** — `pip install -r requirements.txt`

pyserial is what talks to the USB adapter, so the server won't start without it. The macOS binary has it baked in; the source package does not.

```
# Windows
start_nes_radar_server.bat

# Linux
python3 start_nes_radar_server.py
```

Real-hardware acceptance has been done on macOS. Treat Windows and Linux as the experimental path.

## Using it

1. Load the ROM on the NES.
2. Start the server and pick your serial device from the numbered list.
3. Enter an airport ICAO code on the NES and press Start.

**Changing airports.** Press Select on the scope, wait about a second for the ICAO editor, type the next code, press Start. Leave the server running the whole time — a pause handshake keeps the old traffic from scrambling the editor.

**Reading the link.** The screen shows `LINK RECEIVING` when traffic is flowing, `LINK WAITING` when the server has gone quiet, and `LINK ERROR` when something broke. If the server stops sending, stale aircraft clear off the scope rather than sitting there looking live.

**If you restart the server** while the ROM is already on the scope or at `LINK WAITING`, reload the ROM before starting a new session.

**If the server is transmitting but the ROM stays at `LINK WAITING`,** check the D0 connection and the common ground. The host can confirm bytes written to the adapter, but it cannot prove the NES received them.

## Limits

- The scope covers **9 nautical miles** and shows at most **eight aircraft**. More than four markers sharing scanlines use deliberate NES sprite-priority flicker.
- USB detach and reattach mid-session has not completed hardware acceptance.
- The macOS binary is ad-hoc signed, but it is not Developer ID signed or notarized.
- Live traffic needs outbound HTTPS to adsb.fi.

The README inside each download repeats the limitations relevant to that package.

## Repository layout

| Path | What it is |
|---|---|
| `nes_radar/` | The buildable 0.3-beta1 NES ROM source, build files, protocol documentation, and required runtime assets. |
| `server/` | The 0.3-beta1 Python server source, launchers, and native packaging files. |
| `executables/` | The hardware-tested ROM, macOS Universal package, portable Python server package, and SHA-256 hashes. |

Internal experiments, historical regression fixtures, generated previews, and
build environments are retained in the private development archive rather than
the public repository.

## License

See `THIRD_PARTY_NOTICES.md` and `licenses/` inside any release package. The server uses pyserial (BSD); reference material from the C64 Ultimate radar project is GPL-3.0.
