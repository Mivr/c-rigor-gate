"""Batched mutant actions (T064): `tool.py compile-batch` / `linkrun-batch` give, for every mutant, exactly the
record the one-mutant commands (`compile`, `linkrun`) give, and one mutant cannot change another's record.
A fake compiler and a fake linker stand in for clang: the object is the source text, the binary is a shell script."""

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from tests.test_mutate_tool import tool

COMPILER = """#!/bin/sh
# fake compiler: -c SRC -o OBJ; a source with BAD is rejected (status 1), with CRASH it dies (status 2)
src=$2; obj=$4
if grep -q CRASH "$src"; then echo "$src:1: crash" >&2; exit 2; fi
if grep -q BAD "$src"; then echo "$src:1: error: bad" >&2; exit 1; fi
cp "$src" "$obj"
"""
LINKER = """#!/bin/sh
# fake linker: OBJECT... -o BIN; the binary is the object (a shell script)
for a in "$@"; do last=$a; done
cp "$1" "$last"; chmod +x "$last"
"""
RESULT = """printf '%%s\\n' '{"id":"t/a","status":"%s","asserts":%d,"reason":"%s"}' > "$4"\n"""


def quiet(function, argv):
    """Run a tool command; (exit code or None, stderr)."""
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with contextlib.redirect_stderr(err):
        try:
            function(argv)
            code = None
        except SystemExit as stop:
            code = stop.code
        err.flush()
        return code, err.buffer.getvalue().decode("utf-8", "replace")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        for name, text in (("cc", COMPILER), ("ld", LINKER)):
            path = self.root / name
            path.write_text(text)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def path(self, *parts):
        return str(self.root.joinpath(*parts))

    def write(self, name, text):
        Path(self.path(name)).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path(name)).write_text(text)
        return self.path(name)

    def read(self, name):
        return Path(self.path(name)).read_bytes()


class CompileBatchTest(Base):
    SOURCE = "int f(void) { return 1 + 1; }\n"

    def specs(self):
        def spec(mid, replacement):
            begin = self.SOURCE.index("1 + 1")
            return {"id": mid, "begin": begin, "end": begin + 5, "original": "1 + 1", "replacement": replacement}
        return [spec("m1", "1 - 1"), spec("m2", "BAD"), spec("m3", "2 * 2")]

    def single(self, spec, tag, strict=False):
        src = self.write("src/f.c", self.SOURCE)
        one = self.write("one_%s.json" % tag, json.dumps(spec))
        argv = ["--spec", one, "--src", src, "--src-out", self.path("m_%s" % tag, "f.c"),
                "--obj", self.path("%s.o" % tag), "--info", self.path("%s.json" % tag),
                "--strict" if strict else "--lenient", "--", self.path("cc")]
        os.makedirs(self.path("m_%s" % tag))
        return quiet(tool.cmd_compile, argv)

    def batch(self, specs, strict=False):
        src = self.write("src/f.c", self.SOURCE)
        listing = self.write("specs.json", json.dumps({"mutants": specs}))
        argv = ["--specs", listing, "--strict" if strict else "--lenient"]
        for spec in specs:
            argv += ["--item", src, spec["id"], self.path("b_%s.o" % spec["id"]), self.path("b_%s.json" % spec["id"])]
        return quiet(tool.cmd_compile_batch, argv + ["--", self.path("cc")])

    def test_every_record_is_the_one_mutant_record(self):
        specs = self.specs()
        self.assertEqual(self.batch(specs)[0], None)
        for spec in specs:
            self.assertIsNone(self.single({k: v for k, v in spec.items() if k != "id"}, spec["id"])[0])
            self.assertEqual(self.read("b_%s.json" % spec["id"]), self.read("%s.json" % spec["id"]), spec["id"])
            self.assertEqual(self.read("b_%s.o" % spec["id"]), self.read("%s.o" % spec["id"]), spec["id"])

    def test_a_rejected_mutant_is_unviable_and_the_others_still_compile(self):
        self.batch(self.specs())
        self.assertEqual(json.loads(self.read("b_m2.json"))["status"], "unviable")
        self.assertEqual(json.loads(self.read("b_m1.json"))["status"], "ok")
        self.assertEqual(json.loads(self.read("b_m3.json"))["status"], "ok")
        self.assertNotEqual(json.loads(self.read("b_m1.json"))["hash"], json.loads(self.read("b_m3.json"))["hash"])

    def test_the_record_names_no_scratch_directory(self):
        self.batch(self.specs())
        detail = json.loads(self.read("b_m2.json"))["detail"]
        self.assertNotIn("/", detail)
        self.assertIn("error: bad", detail)

    def test_a_compiler_crash_fails_the_batch(self):
        specs = self.specs()
        specs[1]["replacement"] = "CRASH"
        code, _ = self.batch(specs)
        self.assertIsNotNone(code)

    def test_a_stale_spec_fails_the_batch(self):
        specs = self.specs()
        specs[2]["original"] = "9 + 9"
        self.assertIsNotNone(self.batch(specs)[0])

    def test_an_item_without_a_spec_fails_the_batch(self):
        specs = self.specs()
        src = self.write("src/f.c", self.SOURCE)
        listing = self.write("specs.json", json.dumps({"mutants": specs}))
        argv = ["--specs", listing, "--lenient", "--item", src, "zz", self.path("x.o"), self.path("x.json"),
                "--", self.path("cc")]
        self.assertIsNotNone(quiet(tool.cmd_compile_batch, argv)[0])


class LinkRunBatchTest(Base):
    def objects(self):
        pass_ = "#!/bin/sh\n" + RESULT % ("pass", 3, "")
        fail = "#!/bin/sh\n" + RESULT % ("fail", 2, "1 of 2 checks failed; first: a.c:3: CHECK(x): 5") + "exit 1\n"
        crash = "#!/bin/sh\nkill -SEGV $$\n"
        return {"pass": pass_, "fail": fail, "crash": crash}

    def batch(self, objs, command=None):
        argv = []
        for name in objs:
            argv += ["--item", "1", self.path("b_%s.json" % name), self.write("o_%s" % name, objs[name])]
        command = command or [self.path("ld"), tool.OBJECT_SLOT]
        return quiet(tool.cmd_linkrun_batch, argv + ["--"] + command)

    def single(self, name, text):
        obj = self.write("o_%s" % name, text)
        return quiet(tool.cmd_linkrun, ["--out", self.path("%s.json" % name), "--", self.path("ld"), obj])

    def test_every_record_is_the_one_mutant_record(self):
        objs = self.objects()
        self.assertIsNone(self.batch(objs)[0])
        for name, text in objs.items():
            self.assertIsNone(self.single(name, text)[0])
            self.assertEqual(self.read("b_%s.json" % name), self.read("%s.json" % name), name)

    def test_a_crash_is_only_its_own_record(self):
        self.batch(self.objects())
        self.assertEqual(json.loads(self.read("b_crash.json"))["rc"], -1)
        self.assertEqual(json.loads(self.read("b_pass.json"))["rc"], 0)
        self.assertIn('"status":"fail"', json.loads(self.read("b_fail.json"))["results"])

    def test_the_order_of_a_batch_changes_no_record(self):
        objs = self.objects()
        self.batch(objs)
        first = {name: self.read("b_%s.json" % name) for name in objs}
        self.batch(dict(reversed(list(objs.items()))))
        self.assertEqual(first, {name: self.read("b_%s.json" % name) for name in objs})

    def test_a_failed_link_fails_the_batch(self):
        broken = self.write("broken_ld", "#!/bin/sh\necho nope >&2\nexit 1\n")
        os.chmod(broken, 0o755)
        code, _ = self.batch(self.objects(), [broken, tool.OBJECT_SLOT])
        self.assertIsNotNone(code)

    def test_an_item_may_link_several_objects_in_order(self):
        first = self.write("o_first", "#!/bin/sh\n" + RESULT % ("pass", 1, "first"))
        second = self.write("o_second", "#!/bin/sh\n" + RESULT % ("pass", 1, "second"))
        ld = self.write("cat_ld", "#!/bin/sh\nfor a in \"$@\"; do last=$a; done\ncat \"$1\" > \"$last\"; chmod +x \"$last\"\n")
        os.chmod(ld, 0o755)
        argv = ["--item", "2", self.path("two.json"), first, second, "--", ld, tool.OBJECT_SLOT]
        self.assertIsNone(quiet(tool.cmd_linkrun_batch, argv)[0])
        self.assertIn('"reason":"first"', json.loads(self.read("two.json"))["results"])

    def test_a_malformed_item_fails_the_batch(self):
        for argv in (["--item", "2", "out", "o1", "--", self.path("ld"), tool.OBJECT_SLOT],
                     ["--item", "x", "out", "--", self.path("ld"), tool.OBJECT_SLOT],
                     ["--item", "0", "out", "--", self.path("ld"), tool.OBJECT_SLOT],
                     ["stray", "--", self.path("ld"), tool.OBJECT_SLOT]):
            with self.subTest(argv=argv):
                self.assertIsNotNone(quiet(tool.cmd_linkrun_batch, argv)[0])

    def test_the_command_needs_exactly_one_object_slot(self):
        self.assertIsNotNone(self.batch(self.objects(), [self.path("ld")])[0])
        self.assertIsNotNone(self.batch(self.objects(), [self.path("ld"), tool.OBJECT_SLOT, tool.OBJECT_SLOT])[0])


if __name__ == "__main__":
    unittest.main()
