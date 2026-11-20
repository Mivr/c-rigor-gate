"""gate/rigor_lib/wasm_exports.py: the export section of a WebAssembly module (`c_wasm`, docs/toolchain.md).

The modules here are hand-made bytes. The real `tally_wasm.wasm` of examples/wasm is checked by selftest/toolchain.sh.
"""

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rigor_lib import wasm_exports as we
from tests.helpers import TempDirTestCase

SCRIPT = Path(we.__file__)
HEADER = b"\0asm\x01\0\0\0"


def leb(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def section(sid, payload):
    return bytes([sid]) + leb(len(payload)) + payload


def name(text):
    raw = text.encode("utf-8")
    return leb(len(raw)) + raw


def export_section(*entries):
    """entries: (name, kind, index)."""
    body = leb(len(entries)) + b"".join(name(n) + bytes([k]) + leb(i) for n, k, i in entries)
    return section(we.EXPORT_SECTION, body)


# A complete, valid module: one function () -> () with an empty body, one memory page, a custom section, and the
# exports `f` (function 0) and `memory` (memory 0).
TYPES = section(1, leb(1) + b"\x60\x00\x00")
FUNCS = section(3, leb(1) + leb(0))
MEMORY = section(5, leb(1) + b"\x00" + leb(1))
CODE = section(10, leb(1) + leb(2) + b"\x00\x0b")
CUSTOM = section(0, name("producers") + b"\x00")


def module(exports=(("f", 0, 0), ("memory", 2, 0))):
    middle = export_section(*exports) if exports is not None else b""
    return HEADER + CUSTOM + TYPES + FUNCS + MEMORY + middle + CODE


class ExportsTest(unittest.TestCase):
    def test_a_valid_module_lists_its_function_exports_only(self):
        self.assertEqual(we.exports(module()), [("f", 0, 0), ("memory", 2, 0)])
        self.assertEqual(we.function_exports(module()), ["f"])

    def test_function_exports_keep_section_order(self):
        data = module(exports=(("b", 0, 0), ("memory", 2, 0), ("a", 0, 0)))
        self.assertEqual(we.function_exports(data), ["b", "a"])

    def test_a_module_without_an_export_section_exports_nothing(self):
        self.assertEqual(we.exports(module(exports=None)), [])
        self.assertEqual(we.exports(HEADER), [])

    def test_a_non_minimal_leb128_within_five_bytes_is_accepted(self):
        payload = leb(1) + name("f") + b"\x00" + b"\x80\x80\x80\x80\x00"   # index 0 in five bytes
        size = bytes([0x80 | len(payload), 0x80, 0x00])                       # the section size in three
        self.assertEqual(we.exports(HEADER + bytes([we.EXPORT_SECTION]) + size + payload), [("f", 0, 0)])

    def test_a_multi_byte_size_is_decoded(self):
        long_name = "x" * 200   # the name length (200) and the section size need two LEB128 bytes
        self.assertEqual(we.function_exports(module(exports=((long_name, 0, 0),))), [long_name])

    def test_utf8_names_are_decoded(self):
        self.assertEqual(we.function_exports(module(exports=(("taksa_é", 0, 0),))), ["taksa_é"])


class MalformedTest(unittest.TestCase):
    def assertMalformed(self, data, words):
        with self.assertRaises(we.Malformed) as caught:
            we.exports(data)
        self.assertIn(words, str(caught.exception))

    def test_bad_magic(self):
        self.assertMalformed(b"\x7fELF\x01\0\0\0", "bad magic")
        self.assertMalformed(b"", "bad magic")
        self.assertMalformed(b"\0as", "bad magic")

    def test_bad_version(self):
        self.assertMalformed(b"\0asm\x02\0\0\0", "unsupported version")
        self.assertMalformed(b"\0asm\x01\0", "unsupported version")

    def test_truncated_leb128_section_size(self):
        self.assertMalformed(HEADER + b"\x07\x80", "truncated LEB128")
        self.assertMalformed(HEADER + b"\x07", "truncated LEB128")

    def test_truncated_leb128_inside_the_export_section(self):
        # The section is 3 bytes: count 1, name length 1, then a name length's continuation that never ends.
        self.assertMalformed(HEADER + section(we.EXPORT_SECTION, b"\x01\x81\x81"), "truncated LEB128")

    def test_an_export_index_cut_by_the_section_end(self):
        self.assertMalformed(HEADER + section(we.EXPORT_SECTION, leb(1) + name("f") + b"\x00\x80"), "truncated LEB128")

    def test_a_leb128_longer_than_five_bytes(self):
        self.assertMalformed(HEADER + b"\x07\x80\x80\x80\x80\x80\x00", "longer than 5 bytes")

    def test_a_leb128_beyond_32_bits(self):
        self.assertMalformed(HEADER + b"\x07\xff\xff\xff\xff\x7f", "does not fit in 32 bits")

    def test_a_section_past_the_end_of_the_file(self):
        self.assertMalformed(HEADER + b"\x07\x05\x01", "runs past the end of the file")

    def test_a_name_past_the_end_of_the_section(self):
        self.assertMalformed(HEADER + section(we.EXPORT_SECTION, leb(1) + leb(9) + b"ab"), "runs past the end of the section")

    def test_a_name_that_is_not_utf8(self):
        self.assertMalformed(HEADER + section(we.EXPORT_SECTION, leb(1) + leb(1) + b"\xff\x00\x00"), "not UTF-8")

    def test_an_entry_without_a_kind(self):
        self.assertMalformed(HEADER + section(we.EXPORT_SECTION, leb(1) + name("f")), "has no kind")

    def test_an_unknown_kind(self):
        self.assertMalformed(module(exports=(("f", 9, 0),)), "unknown kind 9")

    def test_fewer_entries_than_the_count(self):
        body = leb(2) + name("f") + b"\x00" + leb(0)
        self.assertMalformed(HEADER + section(we.EXPORT_SECTION, body), "truncated LEB128")

    def test_trailing_bytes_after_the_last_export(self):
        body = leb(1) + name("f") + b"\x00" + leb(0) + b"\x00"
        self.assertMalformed(HEADER + section(we.EXPORT_SECTION, body), "1 trailing bytes")

    def test_two_export_sections(self):
        self.assertMalformed(HEADER + export_section(("f", 0, 0)) + export_section(("g", 0, 0)), "2 export sections")


class CliTest(TempDirTestCase):
    def write(self, data):
        path = os.path.join(self.tmp, "m.wasm")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = we.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_function_exports(self):
        path = self.write(module(exports=(("b", 0, 0), ("memory", 2, 0), ("a", 0, 0))))
        self.assertEqual(self.call(path), (0, "b\na\n", ""))

    def test_expect_passes_on_the_same_set_in_any_order(self):
        path = self.write(module(exports=(("b", 0, 0), ("a", 0, 0))))
        self.assertEqual(self.call(path, "--expect", "a", "--expect", "b")[0], 0)

    def test_expect_fails_on_a_missing_or_an_extra_export(self):
        path = self.write(module())
        code, _, err = self.call(path, "--expect", "f", "--expect", "g")
        self.assertEqual(code, 1)
        self.assertIn("missing ['g']", err)
        code, _, err = self.call(path, "--expect", "memory")
        self.assertEqual(code, 1)
        self.assertIn("unexpected ['f']", err)

    def test_expect_fails_on_a_module_without_exports(self):
        code, out, _ = self.call(self.write(module(exports=None)), "--expect", "f")
        self.assertEqual((code, out), (1, ""))

    def test_a_malformed_file_exits_2(self):
        code, out, err = self.call(self.write(b"\x7fELF"), "--expect", "f")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("bad magic", err)

    def test_a_missing_file_exits_2(self):
        code, _, err = self.call(os.path.join(self.tmp, "nope.wasm"))
        self.assertEqual(code, 2)
        self.assertIn("nope.wasm", err)

    def test_runs_as_a_plain_script(self):
        path = self.write(module())
        done = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), path, "--expect", "f"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "f\n", ""))


if __name__ == "__main__":
    unittest.main()
