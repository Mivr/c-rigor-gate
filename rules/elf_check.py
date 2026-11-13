"""Check an Android shared object, and copy it to its output only if every check holds (stdlib only).

    elf_check.py --page-size 16384 [--export NAME]... LIB OUT

Runs in the `android_so` action (rules/android.bzl) on an RE worker, and in the unit tests on synthetic files.
Exit 0 and OUT written, or exit 1 with the reasons on stderr and no OUT:

  * LIB is a little-endian ELF64 shared object (ET_DYN), AArch64 (EM_AARCH64);
  * every PT_LOAD segment has p_align >= the page size and p_offset and p_vaddr agree modulo p_align
    (a 4 KB-aligned segment cannot be mapped on a 16 KB page device, Android 15+);
  * the dynamic symbol table DEFINES exactly the `--export` names (no more, none missing): a shared object
    exports its entry point and nothing else.
"""

import struct
import sys

ET_DYN, EM_AARCH64, PT_LOAD, SHT_DYNSYM = 3, 183, 1, 11
_EHDR = struct.Struct("<16sHHIQQQIHHHHHH")
_PHDR = struct.Struct("<IIQQQQQQ")
_SHDR = struct.Struct("<IIQQQQIIQQ")
_SYM = struct.Struct("<IBBHQQ")
SHN_UNDEF = 0


class Bad(Exception):
    pass


def _header(data):
    if len(data) < _EHDR.size or data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise Bad("not a little-endian ELF64 file")
    fields = _EHDR.unpack_from(data)
    return {"type": fields[1], "machine": fields[2], "phoff": fields[5], "shoff": fields[6],
            "phnum": fields[10], "shnum": fields[12]}


def load_segments(data):
    """[(p_offset, p_vaddr, p_align)] of every PT_LOAD segment."""
    head = _header(data)
    found = []
    for index in range(head["phnum"]):
        at = head["phoff"] + index * _PHDR.size
        if at + _PHDR.size > len(data):
            raise Bad("program header %d is outside the file" % index)
        p_type, _, offset, vaddr, _, _, _, align = _PHDR.unpack_from(data, at)
        if p_type == PT_LOAD:
            found.append((offset, vaddr, align))
    return found


def defined_dynamic_symbols(data):
    """The sorted names of the symbols the dynamic symbol table defines (section index not SHN_UNDEF)."""
    head = _header(data)
    sections = []
    for index in range(head["shnum"]):
        at = head["shoff"] + index * _SHDR.size
        if at + _SHDR.size > len(data):
            raise Bad("section header %d is outside the file" % index)
        sections.append(_SHDR.unpack_from(data, at))
    names = []
    for _, kind, _, _, offset, size, link, _, _, entsize in sections:
        if kind != SHT_DYNSYM:
            continue
        if entsize != _SYM.size or link >= len(sections):
            raise Bad("a malformed dynamic symbol table")
        strtab = sections[link]
        for at in range(offset, offset + size, _SYM.size):
            name, _, _, shndx, _, _ = _SYM.unpack_from(data, at)
            if shndx == SHN_UNDEF:
                continue
            start = strtab[4] + name
            end = data.index(b"\0", start)
            if name != 0:
                names.append(data[start:end].decode("ascii", "replace"))
    return sorted(names)


def problems(data, page_size, exports):
    """Every reason `data` is not an acceptable Android shared object; empty when it is."""
    try:
        head = _header(data)
        found = []
        if head["type"] != ET_DYN:
            found.append("not a shared object (e_type %d)" % head["type"])
        if head["machine"] != EM_AARCH64:
            found.append("not AArch64 (e_machine %d)" % head["machine"])
        segments = load_segments(data)
        if not segments:
            found.append("no PT_LOAD segment")
        for offset, vaddr, align in segments:
            if align < page_size:
                found.append("PT_LOAD at offset 0x%x is aligned to %d, not %d" % (offset, align, page_size))
            elif offset % align != vaddr % align:
                found.append("PT_LOAD at offset 0x%x: offset and vaddr 0x%x disagree modulo %d" % (offset, vaddr, align))
        symbols = defined_dynamic_symbols(data)
    except (Bad, struct.error, ValueError) as exc:
        return ["unreadable: %s" % exc]
    for name in sorted(set(symbols) - set(exports)):
        found.append("exports %s, which is not in the allowed export list" % name)
    for name in sorted(set(exports) - set(symbols)):
        found.append("does not define the export %s" % name)
    return found


def main(argv):
    page_size, exports, paths = None, [], []
    args = list(argv[1:])
    while args:
        arg = args.pop(0)
        if arg == "--page-size" and args:
            page_size = int(args.pop(0))
        elif arg == "--export" and args:
            exports.append(args.pop(0))
        else:
            paths.append(arg)
    if page_size is None or len(paths) != 2:
        sys.stderr.write(__doc__)
        return 2
    with open(paths[0], "rb") as handle:
        data = handle.read()
    found = problems(data, page_size, exports)
    if found:
        sys.stderr.write("%s: not an acceptable Android shared object:\n" % paths[0])
        sys.stderr.write("".join("  " + line + "\n" for line in found))
        return 1
    with open(paths[1], "wb") as handle:
        handle.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
