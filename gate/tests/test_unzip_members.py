"""toolchains/unzip_members.py: component-wise patterns, and an untrusted archive cannot write outside the tree."""

import importlib.util
import os
import stat
import unittest
import zipfile
from pathlib import Path

from tests.helpers import TempDirTestCase

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("unzip_members", ROOT / "toolchains" / "unzip_members.py")
um = importlib.util.module_from_spec(spec)
spec.loader.exec_module(um)


def add(zf, name, data=b"x", mode=0o644, link=None):
    info = zipfile.ZipInfo(name)
    info.external_attr = ((stat.S_IFLNK | 0o777) if link is not None else (stat.S_IFREG | mode)) << 16
    zf.writestr(info, link if link is not None else data)


class Unzip(TempDirTestCase):
    def build(self, entries):
        path = self.tmp / "a.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for entry in entries:
                add(zf, *entry[:1], **entry[1] if len(entry) > 1 else {})
        return path

    def run_extract(self, entries, patterns):
        self.count = getattr(self, "count", 0) + 1
        out = self.tmp / ("out" if self.count == 1 else "out%d" % self.count)
        out.mkdir()
        um.extract(self.build(entries), str(out), patterns)
        return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() or p.is_symlink())

    def refused(self, entries, patterns, text):
        with self.assertRaises(SystemExit) as caught:
            self.run_extract(entries, patterns)
        self.assertIn(text, str(caught.exception))

    def test_star_stays_inside_one_component(self):
        entries = [("inc/a.h",), ("inc/b.c",), ("inc/sub/c.h",), ("inc/x/y/d.h",), ("other/e.h",)]
        self.assertEqual(self.run_extract(entries, ["inc/*.h"]), ["inc/a.h"])

    def test_star_in_a_directory_component_and_directory_patterns(self):
        entries = [("a/include/x.h",), ("b/include/y.h",), ("b/lib/z.a",)]
        self.assertEqual(self.run_extract(entries, ["*/include"]), ["a/include/x.h", "b/include/y.h"])
        self.assertEqual(self.run_extract([("d/f",), ("d/g/h",)], ["d"]), ["d/f", "d/g/h"])

    def test_a_pattern_that_matches_nothing_fails_and_so_does_an_empty_list(self):
        self.refused([("a",)], ["b"], "no member matches: b")
        self.refused([("a",)], [], "no member patterns")

    def test_the_exec_bit_and_symlinks_are_restored(self):
        entries = [("t/run", {"mode": 0o755}), ("t/plain", {"mode": 0o600}), ("t/link", {"link": "run"})]
        self.run_extract(entries, ["t"])
        out = self.tmp / "out" / "t"
        self.assertEqual(stat.S_IMODE((out / "run").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((out / "plain").stat().st_mode), 0o644)
        self.assertEqual(os.readlink(out / "link"), "run")

    def test_absolute_and_escaping_names_are_refused(self):
        for name in ("/etc/x", "../x", "a/../../x", "a//b", "./a", "a\\b"):
            self.refused([(name,)], ["*"], "refusing member name")

    def test_a_repeated_name_is_refused(self):
        path = self.tmp / "dup.zip"
        with zipfile.ZipFile(path, "w") as zf:
            add(zf, "a/x", b"1")
            add(zf, "a/x", b"2")
        with self.assertRaises(SystemExit) as caught:
            um.extract(path, str(self.sub("o")), ["a"])
        self.assertIn("appears twice", str(caught.exception))

    def test_absolute_and_escaping_symlink_targets_are_refused(self):
        for target in ("/etc/passwd", "../../x", "..", "a/../../../x", ""):
            self.refused([("d/l", {"link": target})], ["d"], "refusing symlink")

    def test_a_relative_link_inside_the_tree_is_fine(self):
        self.run_extract([("d/e/l", {"link": "../f"}), ("d/f",)], ["d"])
        self.assertEqual(os.readlink(self.tmp / "out" / "d" / "e" / "l"), "../f")

    def test_a_path_through_a_symlink_of_the_archive_is_refused(self):
        self.refused([("d/l", {"link": "."}), ("d/l/x",)], ["d"], "runs through a symlink")
        self.refused([("d", {"link": "e"}), ("d/x",)], ["d"], "runs through a symlink")

    def test_an_existing_file_is_never_overwritten_or_followed(self):
        out = self.sub("out")
        (out / "victim").write_text("keep")
        os.symlink(out / "victim", out / "a")
        with self.assertRaises(OSError):
            um.extract(self.build([("a",)]), str(out), ["a"])
        self.assertEqual((out / "victim").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
