#!/usr/bin/env python3
"""Decode the reverse-channel frames straight out of the built ROM.

verify_tx_timing.py proves one byte leaves uart_tx_byte with the right bit
periods. It says nothing about which bytes the ROM chooses to send, and the
checksum rule is exactly the kind of arithmetic that agrees with itself while
disagreeing with the server.

So this runs send_location_request and send_pause_request on a cycle-accurate
6502 model, collects every write to $4016, demodulates the resulting line
states as 8N1, and compares the recovered bytes against
server/src/nes_icao_request.py. The expected values come from the server's own
request_bytes(), not from a restatement of the rule here, so a disagreement
between the two sides shows up as a failure rather than as two matching
mistakes.

What this does not prove: port voltage, USB latency, or that an FT232R agrees
with the model's idea of a bit period. Only a real console does that.

Usage:
    python tools/verify_frame_bytes.py nes_radar_scope_v3.nes \
        build/nes_radar_scope_v3.dbg
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "server", "src"))

from verify_tx_timing import Cpu, find_symbol, load_rom  # noqa: E402
import nes_icao_request  # noqa: E402

NTSC_HZ = 1789773.0
BIT_CYCLES = 186
JOY1 = 0x4016

# Both requests are six bytes: the pause marker with four zero-payload bytes,
# and the location marker with four uppercase-letter payload bytes.
PAUSE_MARKER = 0x50
FRAME_BYTES = 6
TEST_CODE = "KJFK"

# 800 us of mark before the first start bit, minus nothing. The ROM's guard
# unit is about 103 us rather than 100, so the real figure is above this.
MIN_GUARD_CYCLES = int(800e-6 * NTSC_HZ)


class FrameCpu(Cpu):
    """Cpu plus the opcodes the framing and guard routines use.

    Anything unmodeled still raises. That is deliberate: a new opcode in this
    path means the code changed and the model has to be extended rather than
    quietly mis-measuring.
    """

    def __init__(self, memory):
        Cpu.__init__(self, memory)
        self.done = False

    def push(self, value):
        self.write(0x0100 | self.sp, value)
        self.sp = (self.sp - 1) & 0xFF

    def pull(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.read(0x0100 | self.sp)

    def compare(self, register, operand):
        result = (register - operand) & 0xFF
        self.carry = 1 if register >= operand else 0
        self.set_nz(result)

    def step(self):
        opcode = self.read(self.pc)

        if opcode == 0x20:                      # JSR abs
            self.pc += 1
            target = self.fetch_word()
            ret = (self.pc - 1) & 0xFFFF
            self.push(ret >> 8)
            self.push(ret & 0xFF)
            self.pc = target
            self.cycles += 6
            return None
        if opcode == 0x60:                      # RTS
            self.pc += 1
            low = self.pull()
            high = self.pull()
            self.pc = (((high << 8) | low) + 1) & 0xFFFF
            self.cycles += 6
            if self.pc == 0x0000 or self.sp > 0xFD:
                self.done = True
            return "rts"
        if opcode == 0x4C:                      # JMP abs
            self.pc += 1
            self.pc = self.fetch_word()
            self.cycles += 3
            return None

        self.pc += 1
        if opcode == 0xA5:                      # LDA zp
            self.a = self.read(self.fetch())
            self.set_nz(self.a)
            self.cycles += 3
        elif opcode == 0xA6:                    # LDX zp
            self.x = self.read(self.fetch())
            self.set_nz(self.x)
            self.cycles += 3
        elif opcode == 0xE6:                    # INC zp
            addr = self.fetch()
            value = (self.read(addr) + 1) & 0xFF
            self.write(addr, value)
            self.set_nz(value)
            self.cycles += 5
        elif opcode == 0xE8:                    # INX
            self.x = (self.x + 1) & 0xFF
            self.set_nz(self.x)
            self.cycles += 2
        elif opcode == 0xBD:                    # LDA abs,x
            base = self.fetch_word()
            self.a = self.read((base + self.x) & 0xFFFF)
            self.set_nz(self.a)
            self.cycles += 4
        elif opcode == 0x9D:                    # STA abs,x
            base = self.fetch_word()
            self.write((base + self.x) & 0xFFFF, self.a)
            self.cycles += 5
        elif opcode == 0x5D:                    # EOR abs,x
            base = self.fetch_word()
            self.a ^= self.read((base + self.x) & 0xFFFF)
            self.set_nz(self.a)
            self.cycles += 4
        elif opcode == 0xC9:                    # CMP #imm
            self.compare(self.a, self.fetch())
            self.cycles += 2
        elif opcode == 0xE0:                    # CPX #imm
            self.compare(self.x, self.fetch())
            self.cycles += 2
        else:
            self.pc -= 1
            return Cpu.step(self)
        return None


def run(memory, entry, icao_addr, code):
    cpu = FrameCpu(memory)
    for index, letter in enumerate(code):
        cpu.mem[icao_addr + index] = ord(letter)
    cpu.pc = entry
    cpu.sp = 0xFD
    # Return address $FFFF, so the outermost RTS lands somewhere recognizable.
    cpu.mem[0x01FE] = 0xFF
    cpu.mem[0x01FF] = 0xFF
    guard = 0
    while not cpu.done:
        cpu.step()
        guard += 1
        if guard > 2000000:
            raise SystemExit("routine did not return")
    return cpu


def demodulate(writes):
    """Recover 8N1 bytes from a list of (cycle, line level) writes.

    The line rests at 0. A guard write raises it to 1, each byte is a 0 start
    bit, eight data bits least significant first, and a 1 stop bit. Every gap
    inside a byte has to be one bit period or the frame is not 9600.
    """
    values = []
    spacings = []
    guard_cycles = None
    interbyte = []
    last_mark = None
    index = 0
    while index < len(writes):
        cycle, level = writes[index]
        if level == 1:
            last_mark = cycle
            index += 1
            continue
        if index == len(writes) - 1:
            break                       # the final drop back to break
        if index + 9 >= len(writes):
            raise SystemExit("truncated frame at write {}".format(index))
        if last_mark is None:
            raise SystemExit("a start bit arrived with the line at break")
        gap = cycle - last_mark
        if guard_cycles is None:
            guard_cycles = gap
        else:
            interbyte.append(gap)
        bits = writes[index:index + 10]
        for step in range(9):
            spacings.append(bits[step + 1][0] - bits[step][0])
        data = 0
        for position in range(8):
            _, bit = bits[position + 1]
            data |= bit << position
        _, stop = bits[9]
        if stop != 1:
            raise SystemExit("byte {} has no stop bit".format(len(values)))
        values.append(data)
        last_mark = bits[9][0]
        index += 10
    return bytes(values), spacings, guard_cycles, interbyte


def check(name, cpu, expected):
    values, spacings, guard_cycles, interbyte = demodulate(cpu.writes)
    problems = []
    if values != expected:
        problems.append("bytes {} expected {}".format(values.hex(), expected.hex()))
    bad = sorted({gap for gap in spacings if gap != BIT_CYCLES})
    if bad:
        problems.append("bit periods {} cycles, expected {}".format(bad, BIT_CYCLES))
    if guard_cycles is None or guard_cycles < MIN_GUARD_CYCLES:
        problems.append("guard {} cycles, expected at least {}".format(
            guard_cycles, MIN_GUARD_CYCLES))
    short = [gap for gap in interbyte if gap < BIT_CYCLES]
    if short:
        problems.append("inter-byte mark {} cycles, under one stop bit".format(short))

    print("{}:".format(name))
    print("  bytes        {}".format(" ".join("{:02X}".format(v) for v in values)))
    print("  guard        {} cycles, {:.0f} us".format(
        guard_cycles, guard_cycles / NTSC_HZ * 1e6))
    print("  inter-byte   {} cycles minimum".format(min(interbyte) if interbyte else 0))
    print("  frame time   {:.1f} ms".format(
        (cpu.writes[-1][0] - cpu.writes[0][0]) / NTSC_HZ * 1000.0))
    if cpu.writes[-1][1] != 0:
        problems.append("the line was left at mark, not returned to break")
    for problem in problems:
        print("  FAIL: {}".format(problem))
    print()
    return not problems


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    rom_path, dbg_path = argv[1], argv[2]

    memory = load_rom(rom_path)
    icao_addr = find_symbol(dbg_path, "icao_code")
    location = find_symbol(dbg_path, "send_location_request")
    pause = find_symbol(dbg_path, "send_pause_request")
    print("icao_code at ${:04X}".format(icao_addr))
    print("send_location_request at ${:04X}".format(location))
    print("send_pause_request at ${:04X}".format(pause))
    print()

    # The location frame's expected bytes come from the server, so this is a
    # cross-check of the two sides rather than of one side against itself.
    expected_location = nes_icao_request.request_bytes(TEST_CODE)

    checksum = nes_icao_request.CHECK_SEED ^ PAUSE_MARKER
    expected_pause = bytes((PAUSE_MARKER, 0, 0, 0, 0, checksum))

    ok = True
    ok &= check("location request {}".format(TEST_CODE),
                run(bytearray(memory), location, icao_addr, TEST_CODE),
                expected_location)
    ok &= check("pause request",
                run(bytearray(memory), pause, icao_addr, TEST_CODE),
                expected_pause)

    # Every ICAO code the editor can produce, not just one.
    failures = []
    for first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for last in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            code = first + "Q" + "Z" + last
            cpu = run(bytearray(memory), location, icao_addr, code)
            values, _, _, _ = demodulate(cpu.writes)
            if values != nes_icao_request.request_bytes(code):
                failures.append(code)
    print("swept 676 ICAO codes through the checksum")
    if failures:
        ok = False
        print("  FAIL: {} disagreed with the server, first {}".format(
            len(failures), failures[:8]))
    print()

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
