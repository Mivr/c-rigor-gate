"""rules/elf_check.py: the 16 KB LOAD alignment and the exact dynamic export list of an Android shared object.

The ELF files here are synthetic and minimal (one header, program headers, a dynamic symbol table); the real
shared object of examples/android is checked by selftest/android.sh.
"""

import importlib.util
import io
import os
import struct
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from tests.helpers import TempDirTestCase

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("elf_check", ROOT / "rules" / "elf_check.py")
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)

PAGE = 16384


def elf(loads=((0, 0, PAGE), (PAGE, PAGE, PAGE)), exports=("ANativeActivity_onCreate",), undefined=("malloc",),
        etype=ec.ET_DYN, machine=ec.EM_AARCH64):
    """An ELF64 file: header, program headers (offset, vaddr, align), then .dynstr, .dynsym and 3 section headers."""
    strtab = b"\0"
    entries = [(0, 0)]
    for name in list(undefined) + list(exports):
        entries.append((len(strtab), 0 if name in undefined else 1))
        strtab += name.encode() + b"\0"
    symtab = b"".join(ec._SYM.pack(n, 0x12, 0, shndx, 0, 0) for n, shndx in entries)
    phoff = ec._EHDR.size
    strtab_at = phoff + len(loads) * ec._PHDR.size
    symtab_at = strtab_at + len(strtab)
    shoff = symtab_at + len(symtab)
    shoff += -shoff % 8
    ehdr = ec._EHDR.pack(b"\x7fELF\x02\x01\x01" + b"\0" * 9, etype, machine, 1, 0, phoff, shoff, 0,
                         ec._EHDR.size, ec._PHDR.size, len(loads), ec._SHDR.size, 3, 0)
    phdrs = b"".join(ec._PHDR.pack(ec.PT_LOAD, 5, off, va, va, 0x100, 0x100, al) for off, va, al in loads)
    shdrs = (ec._SHDR.pack(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
             + ec._SHDR.pack(0, 3, 0, 0, strtab_at, len(strtab), 0, 0, 1, 0)                       # .dynstr (1)
             + ec._SHDR.pack(0, ec.SHT_DYNSYM, 0, 0, symtab_at, len(symtab), 1, 0, 8, ec._SYM.size))   # .dynsym (2), link 1
    body = ehdr + phdrs + strtab + symtab
    return body + b"\0" * (shoff - len(body)) + shdrs


class ProblemsTest(unittest.TestCase):
    ENTRY = ["ANativeActivity_onCreate"]

    def test_a_16k_aligned_object_with_exactly_the_entry_passes(self):
        self.assertEqual(ec.problems(elf(), PAGE, self.ENTRY), [])

    def test_a_4k_aligned_load_segment_fails(self):
        found = ec.problems(elf(loads=((0, 0, 4096), (PAGE, PAGE, PAGE))), PAGE, self.ENTRY)
        self.assertEqual(found, ["PT_LOAD at offset 0x0 is aligned to 4096, not 16384"])

    def test_every_segment_is_checked_not_only_the_first(self):
        found = ec.problems(elf(loads=((0, 0, PAGE), (PAGE, PAGE, 4096), (2 * PAGE, 2 * PAGE, 4096))), PAGE, self.ENTRY)
        self.assertEqual(len(found), 2)

    def test_offset_and_vaddr_must_agree_modulo_the_alignment(self):
        found = ec.problems(elf(loads=((0, 0, PAGE), (PAGE + 4096, PAGE, PAGE))), PAGE, self.ENTRY)
        self.assertEqual(len(found), 1)
        self.assertIn("disagree modulo 16384", found[0])

    def test_a_larger_alignment_is_fine(self):
        self.assertEqual(ec.problems(elf(loads=((0, 0, 65536),)), PAGE, self.ENTRY), [])

    def test_an_object_without_a_load_segment_fails(self):
        self.assertEqual(ec.problems(elf(loads=()), PAGE, self.ENTRY), ["no PT_LOAD segment"])

    def test_an_extra_defined_symbol_fails_and_an_undefined_one_does_not(self):
        found = ec.problems(elf(exports=("ANativeActivity_onCreate", "leaked"), undefined=("malloc", "free")), PAGE,
                            self.ENTRY)
        self.assertEqual(found, ["exports leaked, which is not in the allowed export list"])

    def test_a_missing_export_fails(self):
        found = ec.problems(elf(exports=()), PAGE, self.ENTRY)
        self.assertEqual(found, ["does not define the export ANativeActivity_onCreate"])

    def test_several_exports_must_all_be_defined_exactly(self):
        two = elf(exports=("a_entry", "b_entry"))
        self.assertEqual(ec.problems(two, PAGE, ["a_entry", "b_entry"]), [])
        self.assertEqual(len(ec.problems(two, PAGE, ["a_entry"])), 1)

    def test_not_a_shared_object_or_not_aarch64_fails(self):
        self.assertEqual(ec.problems(elf(etype=2), PAGE, self.ENTRY), ["not a shared object (e_type 2)"])
        self.assertEqual(ec.problems(elf(machine=62), PAGE, self.ENTRY), ["not AArch64 (e_machine 62)"])

    def test_garbage_is_unreadable_not_an_exception(self):
        for data in (b"", b"MZ" + b"\0" * 100, elf()[:70], elf()[:-10]):
            self.assertEqual(len(ec.problems(data, PAGE, self.ENTRY)), 1, data[:8])


class CommandTest(TempDirTestCase):
    def run_main(self, data, *flags):
        lib, out = self.tmp / "lib.so", self.tmp / "out.so"
        lib.write_bytes(data)
        err = io.StringIO()
        with redirect_stderr(err):
            code = ec.main(["elf_check.py", "--page-size", str(PAGE), *flags, str(lib), str(out)])
        return code, err.getvalue(), out

    def test_an_accepted_object_is_copied_byte_for_byte(self):
        data = elf()
        code, err, out = self.run_main(data, "--export", "ANativeActivity_onCreate")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.read_bytes(), data)

    def test_a_refused_object_writes_nothing_and_says_why(self):
        code, err, out = self.run_main(elf(loads=((0, 0, 4096),)), "--export", "ANativeActivity_onCreate")
        self.assertEqual(code, 1)
        self.assertIn("aligned to 4096, not 16384", err)
        self.assertFalse(out.exists())

    def test_bad_arguments_exit_2(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(ec.main(["elf_check.py"]), 2)
            self.assertEqual(ec.main(["elf_check.py", "a", "b"]), 2)
            self.assertEqual(ec.main(["elf_check.py", "--page-size", "16384", "a"]), 2)


if __name__ == "__main__":
    unittest.main()
