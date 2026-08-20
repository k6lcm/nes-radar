#!/usr/bin/env python3
"""Cycle-verify the bit-bang UART transmit routine in the built ROM.

Executes uart_tx_byte on a small cycle-accurate 6502 model and measures the
spacing between consecutive writes to $4016. Every gap must be 186 cycles,
which is 9600 baud at the NTSC 1.789773 MHz master rate to within 0.23
percent.

Why this exists rather than a hand count: a taken branch costs one extra
cycle when it crosses a page boundary. The delay loops here are two bytes
from their branch target, so whether a loop costs 5 or 6 cycles per iteration
depends on where the linker happened to place it. Hand counting cannot see
that, the failure is silent, and the symptom on hardware would be garbled
bytes with no obvious cause. The model below charges the penalty, so moving
code around can never quietly break the baud rate again.

This proves the instruction timing only. It says nothing about port voltage,
USB latency, or whether the FT232R agrees. Only a real console does that.

Usage:
    python tools/verify_tx_timing.py nes_radar_scope_v3.nes \
        build/nes_radar_scope_v3.dbg
"""

import sys

NTSC_HZ = 1789773.0
TARGET_BAUD = 9600.0
EXPECTED_CYCLES = 186
JOY1 = 0x4016
PRG_BASE = 0x8000
INES_HEADER = 16


class Cpu:
    """Just enough 6502 to run a straight-line bit-bang routine.

    Only the opcodes uart_tx_byte uses are implemented. Anything else raises,
    which is the point: an unimplemented opcode means the routine changed and
    the model has to be extended rather than silently mis-measuring.
    """

    def __init__(self, memory):
        self.mem = memory
        self.a = 0
        self.x = 0
        self.y = 0
        self.pc = 0
        self.sp = 0xFD
        self.carry = 0
        self.zero = 0
        self.cycles = 0
        self.writes = []

    def read(self, addr):
        return self.mem[addr & 0xFFFF]

    def write(self, addr, value):
        if addr == JOY1:
            self.writes.append((self.cycles, value & 0x01))
        self.mem[addr & 0xFFFF] = value & 0xFF

    def fetch(self):
        value = self.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return value

    def fetch_word(self):
        low = self.fetch()
        return low | (self.fetch() << 8)

    def set_nz(self, value):
        self.zero = 1 if (value & 0xFF) == 0 else 0

    def branch(self, taken):
        offset = self.fetch()
        if offset >= 0x80:
            offset -= 0x100
        self.cycles += 2
        if not taken:
            return
        target = (self.pc + offset) & 0xFFFF
        self.cycles += 1
        # A taken branch costs one more cycle when the target is on a
        # different page than the instruction following the branch.
        if (target & 0xFF00) != (self.pc & 0xFF00):
            self.cycles += 1
        self.pc = target

    def step(self):
        opcode = self.fetch()

        if opcode == 0xA9:                      # LDA #imm
            self.a = self.fetch()
            self.set_nz(self.a)
            self.cycles += 2
        elif opcode == 0xA2:                    # LDX #imm
            self.x = self.fetch()
            self.set_nz(self.x)
            self.cycles += 2
        elif opcode == 0xA0:                    # LDY #imm
            self.y = self.fetch()
            self.set_nz(self.y)
            self.cycles += 2
        elif opcode == 0x85:                    # STA zp
            self.write(self.fetch(), self.a)
            self.cycles += 3
        elif opcode == 0x8D:                    # STA abs
            self.write(self.fetch_word(), self.a)
            self.cycles += 4
        elif opcode == 0x46:                    # LSR zp
            addr = self.fetch()
            value = self.read(addr)
            self.carry = value & 1
            value >>= 1
            self.write(addr, value)
            self.set_nz(value)
            self.cycles += 5
        elif opcode == 0x69:                    # ADC #imm
            operand = self.fetch()
            total = self.a + operand + self.carry
            self.carry = 1 if total > 0xFF else 0
            self.a = total & 0xFF
            self.set_nz(self.a)
            self.cycles += 2
        elif opcode == 0x88:                    # DEY
            self.y = (self.y - 1) & 0xFF
            self.set_nz(self.y)
            self.cycles += 2
        elif opcode == 0xCA:                    # DEX
            self.x = (self.x - 1) & 0xFF
            self.set_nz(self.x)
            self.cycles += 2
        elif opcode == 0xD0:                    # BNE
            self.branch(self.zero == 0)
        elif opcode == 0xF0:                    # BEQ
            self.branch(self.zero == 1)
        elif opcode == 0xEA:                    # NOP
            self.cycles += 2
        elif opcode == 0x60:                    # RTS
            low = self.read(0x0100 | ((self.sp + 1) & 0xFF))
            high = self.read(0x0100 | ((self.sp + 2) & 0xFF))
            self.sp = (self.sp + 2) & 0xFF
            self.pc = ((high << 8) | low) + 1
            self.cycles += 6
            return "rts"
        else:
            raise NotImplementedError(
                "opcode ${:02X} at ${:04X} is not modeled".format(
                    opcode, (self.pc - 1) & 0xFFFF))
        return None


def load_rom(path):
    with open(path, "rb") as rom:
        data = rom.read()
    if len(data) != 65552:
        raise SystemExit("expected a 65552 byte ROM, got {}".format(len(data)))
    memory = bytearray(0x10000)
    prg = data[INES_HEADER:INES_HEADER + 0x8000]
    memory[PRG_BASE:PRG_BASE + 0x8000] = prg
    return memory


def find_symbol(dbg_path, name):
    needle = 'name="{}"'.format(name)
    with open(dbg_path, "r", encoding="utf-8", errors="replace") as dbg:
        for line in dbg:
            if not line.startswith("sym\t"):
                continue
            if needle not in line:
                continue
            for field in line.strip().split(","):
                if field.startswith("val="):
                    return int(field[4:], 16)
    raise SystemExit("symbol {} not found in {}".format(name, dbg_path))


def run_routine(memory, entry, value):
    cpu = Cpu(memory)
    cpu.a = value
    cpu.pc = entry
    # Plant a sentinel return address so the routine's RTS ends the run.
    cpu.sp = 0xFD
    cpu.mem[0x01FE] = 0xFF
    cpu.mem[0x01FF] = 0xFF
    cpu.sp = 0xFD
    guard = 0
    while True:
        if cpu.step() == "rts":
            break
        guard += 1
        if guard > 200000:
            raise SystemExit("routine did not return")
    return cpu


def check_value(memory, entry, value):
    cpu = run_routine(bytearray(memory), entry, value)
    writes = cpu.writes
    if len(writes) != 10:
        return False, "expected 10 writes to $4016, saw {}".format(len(writes)), []

    expected_bits = [0]                                  # start bit
    expected_bits += [(value >> i) & 1 for i in range(8)]  # LSB first
    expected_bits += [1]                                 # stop bit
    actual_bits = [bit for _, bit in writes]
    if actual_bits != expected_bits:
        return False, "wrong bit pattern: {} vs {}".format(
            "".join(map(str, actual_bits)),
            "".join(map(str, expected_bits))), []

    gaps = [writes[i + 1][0] - writes[i][0] for i in range(9)]
    bad = [g for g in gaps if g != EXPECTED_CYCLES]
    if bad:
        return False, "bit periods {}".format(gaps), gaps
    return True, "", gaps


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    rom_path, dbg_path = argv[1], argv[2]

    memory = load_rom(rom_path)
    entry = find_symbol(dbg_path, "uart_tx_byte")
    print("uart_tx_byte at ${:04X}".format(entry))

    failures = []
    gaps_seen = set()
    for value in range(256):
        ok, message, gaps = check_value(memory, entry, value)
        if not ok:
            failures.append((value, message))
        else:
            gaps_seen.update(gaps)

    print("checked all 256 byte values")
    if failures:
        print()
        print("FAIL")
        for value, message in failures[:8]:
            print("  0x{:02X}: {}".format(value, message))
        if len(failures) > 8:
            print("  ... and {} more".format(len(failures) - 8))
        return 1

    period = EXPECTED_CYCLES
    baud = NTSC_HZ / period
    error = 100.0 * (baud - TARGET_BAUD) / TARGET_BAUD
    frame_drift = 9.5 * (NTSC_HZ / TARGET_BAUD - period)

    print("bit period:       {} cycles, uniform across every bit".format(period))
    print("actual baud:      {:.1f}".format(baud))
    print("error vs 9600:    {:+.3f} percent".format(error))
    print("drift at stop:    {:+.1f} cycles, {:.1f} percent of a bit".format(
        -frame_drift, abs(frame_drift) / period * 100.0))
    print("byte time:        {:.3f} ms".format(10 * period / NTSC_HZ * 1000.0))
    print()
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
