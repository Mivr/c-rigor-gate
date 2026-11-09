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
    """The one-mutant record, for a group holding one test with no objects of its own."""
    SLOTS = [tool.TEST_SLOT, tool.OBJECT_SLOT]

    def objects(self):
        pass_ = "#!/bin/sh\n" + RESULT % ("pass", 3, "")
        fail = "#!/bin/sh\n" + RESULT % ("fail", 2, "1 of 2 checks failed; first: a.c:3: CHECK(x): 5") + "exit 1\n"
        crash = "#!/bin/sh\nulimit -c 0\nkill -SEGV $$\n"
        return {"pass": pass_, "fail": fail, "crash": crash}

    def batch(self, objs, command=None, extra=()):
        argv = list(extra) + ["--test", "one", "0"]
        for name in objs:
            argv += ["--item", "1", self.path("b_%s.json" % name), self.write("o_%s" % name, objs[name])]
        command = command or [self.path("ld")] + self.SLOTS
        return quiet(tool.cmd_linkrun_batch, argv + ["--"] + command)

    def run_of(self, name):
        return json.loads(self.read("b_%s.json" % name))["runs"]["one"]

    def single(self, name, text):
        obj = self.write("o_%s" % name, text)
        return quiet(tool.cmd_linkrun, ["--out", self.path("%s.json" % name), "--", self.path("ld"), obj])

    def test_every_record_is_the_one_mutant_record(self):
        objs = self.objects()
        self.assertIsNone(self.batch(objs)[0])
        for name, text in objs.items():
            self.assertIsNone(self.single(name, text)[0])
            self.assertEqual(self.run_of(name), json.loads(self.read("%s.json" % name)), name)

    def test_a_crash_is_only_its_own_record(self):
        self.batch(self.objects())
        self.assertEqual(self.run_of("crash")["rc"], -1)
        self.assertEqual(self.run_of("pass")["rc"], 0)
        self.assertIn('"status":"fail"', self.run_of("fail")["results"])

    def test_the_order_of_a_batch_changes_no_record(self):
        objs = self.objects()
        self.batch(objs)
        first = {name: self.read("b_%s.json" % name) for name in objs}
        self.batch(dict(reversed(list(objs.items()))))
        self.assertEqual(first, {name: self.read("b_%s.json" % name) for name in objs})

    def test_a_failed_link_fails_the_batch(self):
        broken = self.write("broken_ld", "#!/bin/sh\necho nope >&2\nexit 1\n")
        os.chmod(broken, 0o755)
        code, _ = self.batch(self.objects(), [broken] + self.SLOTS)
        self.assertIsNotNone(code)

    def test_an_item_may_link_several_objects_in_order(self):
        first = self.write("o_first", "#!/bin/sh\n" + RESULT % ("pass", 1, "first"))
        second = self.write("o_second", "#!/bin/sh\n" + RESULT % ("pass", 1, "second"))
        ld = self.write("cat_ld", "#!/bin/sh\nfor a in \"$@\"; do last=$a; done\ncat \"$1\" > \"$last\"; chmod +x \"$last\"\n")
        os.chmod(ld, 0o755)
        argv = ["--test", "one", "0", "--item", "2", self.path("two.json"), first, second, "--", ld] + self.SLOTS
        self.assertIsNone(quiet(tool.cmd_linkrun_batch, argv)[0])
        self.assertIn('"reason":"first"', json.loads(self.read("two.json"))["runs"]["one"]["results"])

    def test_a_malformed_command_line_fails_the_batch(self):
        ld = [self.path("ld")] + self.SLOTS
        for argv in (["--test", "one", "0", "--item", "2", "out", "o1", "--"] + ld,
                     ["--test", "one", "0", "--item", "x", "out", "--"] + ld,
                     ["--test", "one", "0", "--item", "0", "out", "--"] + ld,
                     ["--test", "one", "1", "--"] + ld,                               # a missing test object
                     ["--test", "one", "0", "--test", "one", "0", "--"] + ld,         # a test twice
                     ["--item", "1", "out", "o1", "--"] + ld,                         # no test
                     ["--test", "one", "0", "--prior", "p", "--"] + ld,               # a prior without an item
                     ["--stop-on", "sometimes", "--test", "one", "0", "--"] + ld,
                     ["--test", "one", "0", "stray", "--"] + ld):
            with self.subTest(argv=argv):
                self.assertIsNotNone(quiet(tool.cmd_linkrun_batch, argv)[0])

    def test_the_command_needs_exactly_one_object_slot_and_one_test_slot(self):
        ld = self.path("ld")
        for command in ([ld], [ld, tool.OBJECT_SLOT], [ld, tool.TEST_SLOT], [ld, tool.TEST_SLOT, tool.OBJECT_SLOT, tool.OBJECT_SLOT]):
            with self.subTest(command=command):
                self.assertIsNotNone(self.batch(self.objects(), command)[0])


class StopAtFirstKillTest(Base):
    """T121: the runs of a mutant stop at the first one that fails a check. Each fake test script logs its own run, and
    fails (a check failure, exit 1) when the mutant's object holds `#kill-<test>`, crashes on `#crash-<test>`."""

    def setUp(self):
        super().setUp()
        self.log = self.path("ran.log")
        open(self.log, "w").close()

    def object_of(self, name):
        script = ("#!/bin/sh\n"
                  "mid=$(grep '^#id-' \"$0\"); echo \"%(t)s $mid\" >> %(log)s\n"
                  "if grep -q '^#crash-%(t)s$' \"$0\"; then ulimit -c 0; kill -SEGV $$; fi\n"
                  "if grep -q '^#kill-%(t)s$' \"$0\"; then\n"
                  "  printf '%%s\\n' '{\"id\":\"t/a\",\"status\":\"fail\",\"asserts\":1,\"reason\":\"1 of 2 checks failed; first: a.c:3\"}' > \"$4\"; exit 1\n"
                  "fi\n"
                  "printf '%%s\\n' '{\"id\":\"t/a\",\"status\":\"pass\",\"asserts\":2,\"reason\":\"\"}' > \"$4\"\n") % {"t": name, "log": self.log}
        return self.write("t_" + name, script)

    def linker(self):
        """OBJECT... -o BIN: the binary is the objects' text one after another."""
        path = self.write("cat_ld", "#!/bin/sh\nfor a in \"$@\"; do last=$a; done\n: > \"$last\"\nn=$#; i=0\n"
                          "for a in \"$@\"; do i=$((i+1)); if [ $i -le $((n-2)) ]; then cat \"$a\" >> \"$last\"; echo >> \"$last\"; fi; done\n"
                          "chmod +x \"$last\"\n")
        os.chmod(path, 0o755)
        return path

    def run_group(self, tests, mutants, stop="assert", priors=None):
        """mutants: {name: text of the mutant's object}; returns {name: runs}."""
        argv = ["--stop-on", stop]
        for t in tests:
            argv += ["--test", t, "1", self.object_of(t)]
        for name, text in mutants.items():
            argv += ["--item", "1", self.path("m_%s.json" % name), self.write("o_" + name, "#id-%s\n%s\n" % (name, text))]
            if priors and name in priors:
                argv += ["--prior", priors[name]]
        code, err = quiet(tool.cmd_linkrun_batch, argv + ["--", self.linker(), tool.TEST_SLOT, tool.OBJECT_SLOT])
        self.assertIsNone(code, err)
        return {name: json.loads(self.read("m_%s.json" % name))["runs"] for name in mutants}

    def ran(self):
        return [line.split() for line in self.read("ran.log").decode().splitlines()]

    def test_the_tests_after_the_first_kill_are_skipped_and_say_who_killed(self):
        runs = self.run_group(["t1", "t2", "t3", "t4"], {"a": "#kill-t2"})["a"]
        self.assertEqual(list(runs), ["t1", "t2", "t3", "t4"])
        self.assertEqual(runs["t1"]["rc"], 0)
        self.assertEqual(runs["t2"]["rc"], 1)
        self.assertEqual(runs["t3"], {"killed_by": "t2"})
        self.assertEqual(runs["t4"], {"killed_by": "t2"})
        self.assertEqual(self.ran(), [["t1", "#id-a"], ["t2", "#id-a"]])   # t3 and t4 never ran

    def test_a_surviving_mutant_runs_every_test(self):
        runs = self.run_group(["t1", "t2", "t3"], {"s": "#nothing"})["s"]
        self.assertEqual([runs[t]["rc"] for t in ("t1", "t2", "t3")], [0, 0, 0])
        self.assertNotIn("killed_by", json.dumps(runs))
        self.assertEqual(len(self.ran()), 3)

    def test_a_kill_of_one_mutant_does_not_skip_the_runs_of_another(self):
        runs = self.run_group(["t1", "t2"], {"a": "#kill-t1", "s": "#nothing"})
        self.assertEqual(runs["a"]["t2"], {"killed_by": "t1"})
        self.assertEqual(runs["s"]["t2"]["rc"], 0)

    def test_a_crash_is_not_a_kill_that_stops_the_runs(self):
        """killed-assert wins over killed-crash whatever the order, so a crash must not hide a later failed check."""
        runs = self.run_group(["t1", "t2", "t3"], {"c": "#crash-t1\n#kill-t3"})["c"]
        self.assertEqual(runs["t1"]["rc"], -1)
        self.assertEqual(runs["t2"]["rc"], 0)
        self.assertEqual(runs["t3"]["rc"], 1)

    def test_stop_on_never_runs_everything(self):
        runs = self.run_group(["t1", "t2", "t3"], {"a": "#kill-t1"}, stop="never")["a"]
        self.assertEqual([runs[t]["rc"] for t in ("t1", "t2", "t3")], [1, 0, 0])

    def test_a_group_after_a_kill_runs_nothing_and_names_the_same_killer(self):
        first = self.run_group(["t1", "t2"], {"a": "#kill-t2", "s": "#nothing"})
        self.assertEqual(first["a"]["t1"]["rc"], 0)
        before = len(self.ran())
        priors = {"a": self.path("m_a.json"), "s": self.path("m_s.json")}
        for name in priors:   # the next group reads this group's records: keep them
            Path(priors[name]).replace(self.path("prior_%s.json" % name))
            priors[name] = self.path("prior_%s.json" % name)
        second = self.run_group(["t3", "t4"], {"a": "#kill-t2", "s": "#nothing"}, priors=priors)
        self.assertEqual(second["a"], {"t3": {"killed_by": "t2"}, "t4": {"killed_by": "t2"}})
        self.assertEqual([second["s"]["t3"]["rc"], second["s"]["t4"]["rc"]], [0, 0])
        self.assertEqual(len(self.ran()) - before, 2)   # only the survivor's two runs

    def test_a_prior_that_was_itself_skipped_keeps_the_original_killer(self):
        self.run_group(["t1"], {"a": "#kill-t1"})
        Path(self.path("m_a.json")).replace(self.path("g1.json"))
        self.run_group(["t2"], {"a": "#nothing"}, priors={"a": self.path("g1.json")})
        Path(self.path("m_a.json")).replace(self.path("g2.json"))
        third = self.run_group(["t3"], {"a": "#nothing"}, priors={"a": self.path("g2.json")})
        self.assertEqual(third["a"], {"t3": {"killed_by": "t1"}})

    def test_the_records_do_not_depend_on_where_the_tests_are_split(self):
        """Group by group, with priors, gives the records of one big group (the cache and the report rely on it)."""
        whole = self.run_group(["t1", "t2", "t3", "t4"], {"a": "#kill-t2"})["a"]
        self.run_group(["t1", "t2"], {"a": "#kill-t2"})
        Path(self.path("m_a.json")).replace(self.path("g1.json"))
        rest = self.run_group(["t3", "t4"], {"a": "#kill-t2"}, priors={"a": self.path("g1.json")})["a"]
        split = dict(json.loads(self.read("g1.json"))["runs"], **rest)
        self.assertEqual(split, whole)


if __name__ == "__main__":
    unittest.main()
