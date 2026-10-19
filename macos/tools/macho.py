#!/usr/bin/env python3
"""Read the reviewed thin Mach-O images without requiring Xcode command tools."""
import argparse
import json
from pathlib import Path
import struct


def read_image(data):
    if len(data) < 32 or struct.unpack_from("<I", data)[0] != 0xfeedfacf:
        raise ValueError("Expected a thin 64-bit Mach-O image")
    _, cpu, _, filetype, count, size, _, _ = struct.unpack_from("<8I", data)
    end = 32 + size
    if end > len(data) or count > size // 8:
        raise ValueError("Invalid Mach-O load-command bounds")
    offset, segments, symtab = 32, [], None
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError("Truncated Mach-O load command")
        command, length = struct.unpack_from("<II", data, offset)
        if length < 8 or offset + length > end:
            raise ValueError("Invalid Mach-O load command")
        if command == 0x19:
            if length < 72:
                raise ValueError("Truncated Mach-O segment")
            vm, _, position, length_in_file = struct.unpack_from("<QQQQ", data, offset + 24)
            if position + length_in_file > len(data):
                raise ValueError("Mach-O segment outside file")
            segments.append((vm, position, length_in_file))
        if command == 2:
            if length != 24 or symtab is not None:
                raise ValueError("Invalid Mach-O symbol table")
            symtab = struct.unpack_from("<4I", data, offset + 8)
        offset += length
    if offset != end or symtab is None:
        raise ValueError("Missing or inconsistent Mach-O symbol table")
    position, count, strings, string_size = symtab
    if position < end or strings < end or position + count * 16 > len(data) or strings + string_size > len(data):
        raise ValueError("Mach-O symbol table outside file")
    symbols = []
    for index in range(count):
        name, kind, _, _, address = struct.unpack_from("<IBBHQ", data, position + index * 16)
        if kind & 0xe0 or not name:
            continue  # STAB/debug entries and anonymous symbols.
        if name >= string_size:
            raise ValueError("Mach-O symbol name outside string table")
        terminator = data.find(b"\0", strings + name, strings + string_size)
        if terminator == -1:
            raise ValueError("Unterminated Mach-O symbol name")
        symbols.append((data[strings + name:terminator].decode("utf-8"), address, kind))
    exports = sorted({name for name, _, kind in symbols if kind & 1 and kind & 0x0e in {2, 0x0e, 0x0a}})
    return {"architectures": [{0x1000007: "x86_64", 0x100000c: "arm64"}.get(cpu, f"cpu_{cpu:x}")],
            "filetype": filetype, "segments": segments, "symbols": symbols, "exports": exports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    try:
        info = read_image(args.binary.read_bytes())
        print(json.dumps({key: info[key] for key in ["architectures", "filetype", "exports"]}))
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"{error}\n")
