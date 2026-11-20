"""List the exported function names of a WebAssembly module (stdlib only; `c_wasm`, docs/toolchain.md).

    python3 -I -B gate/rigor_lib/wasm_exports.py FILE.wasm [--expect NAME]...

Without `--expect`: prints the exported function names, one per line, in export-section order; exit 0.
With `--expect`: also compares them, as a set, with the given names; exit 1 (and the difference on stderr) if they
are not exactly equal. Exit 2 if FILE is not a well-formed binary module as far as this reader goes: the magic
`\\0asm`, version 1, then sections (one id byte, a u32 LEB128 size, the payload), each inside the file. Only the
export section (id 7) is decoded: a vector of (name, kind, index); kind 0 is a function. A module without an
export section exports nothing. Two export sections, a malformed or over-long LEB128, a name that is not UTF-8,
or a section or name that runs past its end are errors.

Self-contained (no `rigor_lib` import) so that it runs as a plain script, as the selftest and a reviewer use it.
"""

import argparse
import sys

MAGIC = b"\0asm"
VERSION = b"\x01\0\0\0"
EXPORT_SECTION = 7
KIND_FUNCTION = 0
KINDS = (0, 1, 2, 3, 4)   # function, table, memory, global, tag
_U32_BYTES = 5            # ceil(32 / 7): the longest LEB128 encoding of a u32


class Malformed(Exception):
    """The bytes are not a module this reader accepts."""


def read_u32(data, at, end):
    """The unsigned LEB128 u32 at `at` (before `end`) and the offset after it."""
    value = 0
    for i in range(_U32_BYTES):
        if at + i >= end:
            raise Malformed("truncated LEB128 at offset %d" % at)
        byte = data[at + i]
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            if value > 0xFFFFFFFF:
                raise Malformed("LEB128 at offset %d does not fit in 32 bits" % at)
            return value, at + i + 1
    raise Malformed("LEB128 at offset %d is longer than %d bytes" % (at, _U32_BYTES))


def sections(data):
    """(id, payload start, payload end) of every section, in file order, after checking the header."""
    if data[:4] != MAGIC:
        raise Malformed("bad magic: not a WebAssembly binary module")
    if data[4:8] != VERSION:
        raise Malformed("unsupported version %s (only 1)" % data[4:8].hex())
    found = []
    at = 8
    while at < len(data):
        sid = data[at]
        size, start = read_u32(data, at + 1, len(data))
        if start + size > len(data):
            raise Malformed("section %d at offset %d runs past the end of the file" % (sid, at))
        found.append((sid, start, start + size))
        at = start + size
    return found


def _export(data, at, end):
    """One export entry: (name, kind, index) and the offset after it."""
    length, at = read_u32(data, at, end)
    if at + length > end:
        raise Malformed("export name at offset %d runs past the end of the section" % at)
    try:
        name = data[at:at + length].decode("utf-8")
    except UnicodeDecodeError:
        raise Malformed("export name at offset %d is not UTF-8" % at) from None
    at += length
    if at >= end:
        raise Malformed("export %r has no kind" % name)
    kind = data[at]
    if kind not in KINDS:
        raise Malformed("export %r has unknown kind %d" % (name, kind))
    index, at = read_u32(data, at + 1, end)
    return (name, kind, index), at


def exports(data):
    """Every export (name, kind, index) of the module, in section order."""
    found = [(start, end) for sid, start, end in sections(data) if sid == EXPORT_SECTION]
    if len(found) > 1:
        raise Malformed("%d export sections (at most one is allowed)" % len(found))
    if not found:
        return []
    start, end = found[0]
    count, at = read_u32(data, start, end)
    entries = []
    for _ in range(count):
        entry, at = _export(data, at, end)
        entries.append(entry)
    if at != end:
        raise Malformed("%d trailing bytes after the last export" % (end - at))
    return entries


def function_exports(data):
    """The names of the exported functions, in section order."""
    return [name for name, kind, _ in exports(data) if kind == KIND_FUNCTION]


def main(argv=None):
    parser = argparse.ArgumentParser(description="List (and optionally check) the exported functions of a .wasm file.")
    parser.add_argument("file")
    parser.add_argument("--expect", action="append", default=None, metavar="NAME",
                        help="an expected exported function (repeat); exit 1 unless the set is exactly these")
    args = parser.parse_args(argv)
    try:
        with open(args.file, "rb") as handle:
            names = function_exports(handle.read())
    except OSError as error:
        print("wasm_exports: %s: %s" % (args.file, error.strerror), file=sys.stderr)
        return 2
    except Malformed as error:
        print("wasm_exports: %s: %s" % (args.file, error), file=sys.stderr)
        return 2
    for name in names:
        print(name)
    if args.expect is None:
        return 0
    missing = sorted(set(args.expect) - set(names))
    extra = sorted(set(names) - set(args.expect))
    if missing or extra or len(names) != len(set(names)):
        print("wasm_exports: %s: missing %s, unexpected %s" % (args.file, missing, extra), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
