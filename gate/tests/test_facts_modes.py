"""Gate `mode-divergence` (T023): the scan of called functions and `rigor facts --modes`, on hand-made files."""

import json
import shutil
import subprocess
import sys

from rigor_lib import cscan, facts_modes
from tests.helpers import GATE_DIR, TempDirTestCase, read_json, run_rigor
from tests.test_facts import facts, unit

ROOT = "buck-out/v2/art/toolchains/0123456789abcdef/__sysroot__/tree/usr/include"


def calls_of(text):
    collector = facts_modes._call_collector(cscan)((ROOT,))
    collector.scan(text)
    return sorted((name, line) for name, _, line in collector.calls)


def mark(path, line=1, flags=""):
    return '# %d "%s"%s\n' % (line, path, flags)


def calls_doc(label, units):
    return {"schema": 1, "label": label, "units": [
        {"name": n, "calls": [{"name": c, "file": "p/a.c", "line": l} for c, l in calls]} for n, calls in units]}


class ScanCase(TempDirTestCase):
    def test_calls_and_non_calls(self):
        text = mark("a.c") + "int f(int x) { if (x) { g(x); } while (h (x)) { } return sizeof(x) + (int)(x); }\n"
        self.assertEqual(calls_of(text), [("f", 1), ("g", 1), ("h", 1)])

    def test_a_call_across_lines_and_macro_expansions_count(self):
        text = mark("a.c") + "int f(void) { return g\n(1); }\n"
        self.assertEqual(calls_of(text), [("f", 1), ("g", 2)])

    def test_system_text_and_strings_are_not_product_calls(self):
        text = (mark("a.c") + "int f(void) { return puts(\"g(1)\"); }\n"
                + mark(ROOT + "/stdio.h", 1, " 1 3") + "int inner(void) { return hidden(); }\n"
                + mark("a.c", 2, " 2"))
        self.assertEqual(calls_of(text), [("f", 1), ("puts", 1)])

    def test_the_script_writes_a_calls_file(self):
        pre = self.tmp / "a.i"
        pre.write_text(mark("a.c") + "int f(void) { return g(); }\n", encoding="utf-8")
        out = self.tmp / "calls.json"
        done = subprocess.run([sys.executable, "-I", "-B", str(GATE_DIR / "rigor_lib" / "facts_modes.py"), "scan",
                               "--label", "//p:lib", "--cscan",
                               str(GATE_DIR / "rigor_lib" / "cscan.py"), "--system-root", ROOT, "--unit", "a.c.o", str(pre),
                               "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["label"], "//p:lib")
        self.assertEqual([(c["name"], c["line"]) for c in doc["units"][0]["calls"]], [("f", 1), ("g", 1)])


class ModesCase(TempDirTestCase):
    def put(self, mode, name, document, calls=()):
        directory = self.sub(mode)
        label = document["label"]
        (directory / (name + ".json")).write_text(json.dumps(document), encoding="utf-8")
        (directory / (name + ".calls.json")).write_text(
            json.dumps(calls_doc(label, calls) if isinstance(calls, (list, tuple)) else calls), encoding="utf-8")

    def both(self, release, san, label="//p:lib"):
        self.put("release", "lib", facts(label, [release[0]]), release[1])
        self.put("san", "lib", facts(label, [san[0]]), san[1])

    def modes(self, code):
        out = self.tmp / "out.json"
        outcome = run_rigor(["facts", "--modes", self.tmp / "release", self.tmp / "san", "--out", out])
        self.assertExit(outcome, code)
        return read_json(out) if out.exists() else None

    def internal_error(self):
        result = self.modes(2)
        self.assertEqual([f["rule"] for f in result["findings"]], ["internal-error"])
        self.assertEqual(result["status"], "FAIL")

    def items(self, code):
        result = self.modes(code)
        return sorted((f["only_in"], f["item_kind"], f["item"], f["line"]) for f in result["findings"])

    def test_identical_modes_are_green(self):
        u = unit(pragmas=[], identifiers=[("__builtin_trap", 4)])
        self.both((u, [("a.c.o", [("f", 1)])]), (u, [("a.c.o", [("f", 1)])]))
        self.assertEqual(self.items(0), [])

    def test_symbol_facts_are_not_compared(self):
        self.both((unit(defined=["f"], undefined=["x"]), [("a.c.o", [])]),
                  (unit(defined=["f", "__asan_init"], undefined=["__asan_report"]), [("a.c.o", [])]))
        self.assertEqual(self.items(0), [])

    def test_every_kind_of_item_in_either_mode(self):
        release = unit(identifiers=[("__asm__", 9)])
        san = unit(pragmas=[(3, "clang diagnostic push")], attributes=[("optnone", 5)],
                   line_directives=[("x.c", 7)], identifiers=[("__builtin_trap", 6)])
        self.both((release, [("a.c.o", [("hook", 2)])]), (san, [("a.c.o", [("other", 8)])]))
        self.assertEqual(self.items(1), [
            ("release", "call", "hook", 2), ("release", "identifier", "__asm__", 9),
            ("san", "attribute", "optnone", 5), ("san", "call", "other", 8),
            ("san", "identifier", "__builtin_trap", 6), ("san", "line-directive", "x.c", 7),
            ("san", "pragma", "clang diagnostic push", 3)])

    def test_the_same_item_on_another_line_is_a_divergence_in_both(self):
        self.both((unit(), [("a.c.o", [("f", 1)])]), (unit(), [("a.c.o", [("f", 2)])]))
        self.assertEqual(self.items(1), [("release", "call", "f", 1), ("san", "call", "f", 2)])

    def test_finding_fields(self):
        self.both((unit(), [("a.c.o", [])]), (unit(), [("a.c.o", [("f", 2)])]))
        finding = self.modes(1)["findings"][0]
        self.assertEqual((finding["rule"], finding["target"], finding["unit"], finding["file"]),
                         ("mode-divergent-code", "//p:lib", "a.c.o", "p/a.c"))
        self.assertEqual(self.modes(1)["gate"], "mode-divergence")

    def test_third_party_facts_are_skipped(self):
        for mode in ("release", "san"):
            directory = self.sub(mode)
            third = facts("gate//third_party/x:x", [unit()], kind="c_third_party")
            (directory / "x.json").write_text(json.dumps(third), encoding="utf-8")
            (directory / "x.calls.json").write_text("{}", encoding="utf-8")
        self.both((unit(), [("a.c.o", [])]), (unit(), [("a.c.o", [])]))
        self.assertEqual(self.items(0), [])

    def test_fail_closed(self):
        u = (unit(), [("a.c.o", [])])
        self.both(u, u)
        self.put("san", "extra", facts("//p:extra", [unit()]), [("a.c.o", [])])
        self.internal_error()   # a target with no release twin

    def test_unit_in_one_mode_only(self):
        self.put("release", "lib", facts("//p:lib", [unit("a.c.o"), unit("b.c.o")]), [("a.c.o", []), ("b.c.o", [])])
        self.put("san", "lib", facts("//p:lib", [unit("a.c.o")]), [("a.c.o", [])])
        self.internal_error()

    def test_missing_calls_label_mismatch_schema_and_junk(self):
        u = (unit(), [("a.c.o", [])])
        for name, mutate in (
                ("no calls", lambda d: (d / "lib.calls.json").unlink()),
                ("stray file", lambda d: (d / "note.txt").write_text("x", encoding="utf-8")),
                ("bad json", lambda d: (d / "lib.calls.json").write_text("{", encoding="utf-8")),
                ("label", lambda d: (d / "lib.calls.json").write_text(
                    json.dumps(calls_doc("//p:other", [("a.c.o", [])])), encoding="utf-8")),
                ("schema", lambda d: (d / "lib.calls.json").write_text(
                    json.dumps(dict(calls_doc("//p:lib", [("a.c.o", [])]), schema=2)), encoding="utf-8")),
                ("extra unit", lambda d: (d / "lib.calls.json").write_text(
                    json.dumps(calls_doc("//p:lib", [("a.c.o", []), ("z.c.o", [])])), encoding="utf-8")),
                ("bad call", lambda d: (d / "lib.calls.json").write_text(json.dumps(
                    {"schema": 1, "label": "//p:lib", "units": [{"name": "a.c.o", "calls": [{"name": 1}]}]}),
                    encoding="utf-8")),
                ("facts schema", lambda d: (d / "lib.json").write_text(
                    json.dumps(dict(facts("//p:lib", [unit()]), schema=2)), encoding="utf-8"))):
            with self.subTest(name):
                for mode in ("release", "san"):
                    shutil.rmtree(self.tmp / mode, ignore_errors=True)
                self.both(u, u)
                mutate(self.tmp / "san")
                self.internal_error()

    def test_empty_missing_and_mixed_arguments(self):
        self.sub("release")
        self.sub("san")
        self.internal_error()
        outcome = run_rigor(["facts", "--modes", self.tmp / "nope", self.tmp / "nope2"])
        self.assertExit(outcome, 2)
        outcome = run_rigor(["facts", "--modes", self.tmp, self.tmp, "--gate", "symbols"])
        self.assertExit(outcome, 2)
        self.assertExit(run_rigor(["facts", "--gate", "symbols"]), 2)
