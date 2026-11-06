"""Tests for `rigor facts` (gates semantic-suppressions and symbols) on hand-made facts."""

import json
import os

from tests.helpers import TempDirTestCase, read_json, run_rigor

GLOBAL = """
[global]
deny = ["kill", "exit", "fopen", "open"]
trusted = ["//ctest:ctest"]
"""
POLICY = GLOBAL + """
[module."//p:lib"]
allow = ["memcpy"]
"""
WITH_TEST = POLICY + '[module."//p:test"]\n'

LIBC = "kill\nexit\nfopen\nmemcpy\nopen\nwrite\nprintf\n"


def unit(name="a.c.o", defined=(), undefined=(), weak=(), pragmas=(), attributes=(), identifiers=()):
    return {"name": name, "defined": sorted(defined), "weak": sorted(weak), "undefined": sorted(undefined),
            "pragmas": [{"file": "p/a.c", "line": n, "text": t} for n, t in pragmas],
            "attributes": [{"name": a, "file": "p/a.c", "line": n} for a, n in attributes],
            "identifiers": [{"name": a, "file": "p/a.c", "line": n} for a, n in identifiers]}


def facts(label, units, deps=(), kind="c_library"):
    return {"schema": 1, "label": label, "kind": kind, "deps": sorted(deps), "units": units}


CTEST = facts("//ctest:ctest", [unit("ctest.c.o", defined=["ctest_run", "ctest_check"],
                                     undefined=["kill", "exit", "fork"])])


class FactsCase(TempDirTestCase):
    def run_gate(self, gate, targets, policy=POLICY, libc=LIBC, expect_code=None, extra=()):
        fdir = self.sub("facts")
        for index, document in enumerate(targets):
            (fdir / ("f%d.json" % index)).write_text(json.dumps(document), encoding="utf-8")
        pol = self.tmp / "policy.toml"
        pol.write_text(policy, encoding="utf-8")
        lib = self.tmp / "libc.symbols"
        lib.write_text(libc or "", encoding="utf-8")
        out = self.tmp / ("%s.json" % gate)
        argv = ["facts", "--gate", gate, "--facts", fdir, "--policy", pol, "--out", out]
        if libc is not None:
            argv += ["--libc", lib]
        outcome = run_rigor(argv + list(extra))
        if expect_code is not None:
            self.assertExit(outcome, expect_code)
        return outcome, (read_json(out) if out.exists() else None)

    def rules(self, gate, targets, code, **kw):
        outcome, result = self.run_gate(gate, targets, expect_code=code, **kw)
        return sorted((f["rule"], f.get("symbol") or f.get("name") or f.get("dep") or f.get("target"))
                      for f in result["findings"])

    def sem(self, units, code, label="//p:lib", **kw):
        return self.rules("semantic-suppressions", [facts(label, units), CTEST], code, **kw)

    def sym(self, targets, code, **kw):
        if "policy" not in kw:   # every product module listed, //p:lib may use memcpy
            kw["policy"] = GLOBAL + "".join(
                '[module."%s"]\n%s' % (t["label"], 'allow = ["memcpy"]\n' if t["label"] == "//p:lib" else "")
                for t in targets)
        return self.rules("symbols", targets + [CTEST], code, **kw)

    # ---- semantic-suppressions -----------------------------------------------------------
    def test_clean_is_green(self):
        self.assertEqual(self.sem([unit()], 0), [])

    def test_pragma(self):
        self.assertEqual(self.sem([unit(pragmas=[(3, "clang diagnostic ignored \"-Wall\"")])], 1),
                         [("pragma", "//p:lib")])

    def test_pragma_operator_and_asm(self):
        got = self.sem([unit(identifiers=[("_Pragma", 1), ("__pragma", 2), ("asm", 3), ("__asm__", 4), ("__asm", 5)])], 1)
        self.assertEqual([rule for rule, _ in got], ["inline-asm"] * 3 + ["pragma-operator"] * 2)

    def test_forbidden_attributes(self):
        names = ["optnone", "no_instrument_function", "no_profile_instrument_function",
                 "disable_sanitizer_instrumentation", "no_sanitize", "weak", "alias", "constructor",
                 "destructor", "section", "used", "visibility"]
        got = self.sem([unit(attributes=[(n, 1) for n in names])], 1)
        self.assertEqual(sorted(name for _, name in got), sorted(names))
        self.assertEqual({rule for rule, _ in got}, {"forbidden-attribute"})

    def test_dunder_attribute_spelling_is_the_same_attribute(self):
        self.assertEqual(self.sem([unit(attributes=[("__no_sanitize__", 1), ("__weak__", 2)])], 1),
                         [("forbidden-attribute", "no_sanitize"), ("forbidden-attribute", "weak")])

    def test_harmless_attributes_are_fine(self):
        self.assertEqual(self.sem([unit(attributes=[("noreturn", 1), ("__noreturn__", 1), ("unused", 2),
                                                    ("format", 3), ("printf", 3), ("clang", 4)])], 0), [])

    def test_guarded_builtins_need_the_module_to_allow_them(self):
        ids = [("__builtin_trap", 1), ("__builtin_unreachable", 2)]
        self.assertEqual(self.sem([unit(identifiers=ids)], 1),
                         [("forbidden-builtin", "__builtin_trap"), ("forbidden-builtin", "__builtin_unreachable")])
        allowed = POLICY + '\n[module."//core:assert"]\nallow_builtins = ["__builtin_trap", "__builtin_unreachable"]\n'
        self.assertEqual(self.sem([unit(identifiers=ids)], 0, label="//core:assert", policy=allowed), [])

    def test_builtin_allowed_for_one_module_is_not_allowed_for_another(self):
        allowed = POLICY + '\n[module."//core:assert"]\nallow_builtins = ["__builtin_trap"]\n'
        self.assertEqual(self.sem([unit(identifiers=[("__builtin_trap", 1)])], 1, policy=allowed),
                         [("forbidden-builtin", "__builtin_trap")])
        self.assertEqual(self.sem([unit(identifiers=[("__builtin_unreachable", 1)])], 1,
                                  label="//core:assert", policy=allowed),
                         [("forbidden-builtin", "__builtin_unreachable")])

    def test_unknown_scanner_identifier_fails_closed(self):
        outcome, _ = self.run_gate("semantic-suppressions",
                                   [facts("//p:lib", [unit(identifiers=[("__builtin_exit", 1)])]), CTEST])
        self.assertExit(outcome, 2)

    def test_trusted_modules_are_scanned_too(self):
        trusted = facts("//ctest:ctest", [unit("ctest.c.o", pragmas=[(1, "once")])])
        outcome, result = self.run_gate("semantic-suppressions", [trusted], expect_code=1)
        self.assertEqual(result["findings"][0]["rule"], "pragma")

    def test_findings_are_deterministic_and_located(self):
        targets = [facts("//p:lib", [unit(pragmas=[(9, "a"), (2, "b")], identifiers=[("asm", 4)])]), CTEST]
        first, second = self.run_gate("semantic-suppressions", targets)[0], None
        out = self.tmp / "semantic-suppressions.json"
        before = out.read_bytes()
        self.run_gate("semantic-suppressions", targets)
        self.assertEqual(out.read_bytes(), before)
        found = read_json(out)["findings"]
        self.assertEqual({f["file"] for f in found}, {"p/a.c"})
        self.assertEqual(sorted(f["line"] for f in found), [2, 4, 9])

    # ---- symbols ---------------------------------------------------------------------------
    def lib(self, **kw):
        return facts("//p:lib", [unit(**kw)])

    def test_symbols_clean(self):
        self.assertEqual(self.sym([self.lib(defined=["f"], undefined=["memcpy"])], 0), [])

    def test_denied_symbol(self):
        self.assertEqual(self.sym([self.lib(defined=["f"], undefined=["kill"])], 1), [("denied-symbol", "kill")])

    def test_denied_symbol_beats_allow(self):
        policy = POLICY.replace('allow = ["memcpy"]', 'allow = ["memcpy", "kill"]')
        self.assertEqual(self.sym([self.lib(undefined=["kill"])], 1, policy=policy), [("denied-symbol", "kill")])

    def test_exempt_symbol_is_allowed_for_that_module_only(self):
        policy = POLICY.replace('allow = ["memcpy"]', 'deny_exempt = ["fopen"]')
        self.assertEqual(self.sym([self.lib(undefined=["fopen"])], 0, policy=policy), [])
        other = facts("//p:test", [unit(undefined=["fopen"])], kind="c_test")
        policy += '[module."//p:test"]\n'
        self.assertEqual(self.sym([self.lib(), other], 1, policy=policy), [("denied-symbol", "fopen")])

    def test_undeclared_symbol(self):
        self.assertEqual(self.sym([self.lib(undefined=["mystery"])], 1), [("undeclared-symbol", "mystery")])

    def test_dependency_exports_are_allowed_but_not_transitive(self):
        base = facts("//p:base", [unit(defined=["base_f"])])
        mid = facts("//p:mid", [unit(defined=["mid_f"], undefined=["base_f"])], deps=["//p:base"])
        top = facts("//p:top", [unit(undefined=["mid_f", "base_f"])], deps=["//p:mid"])
        policy = GLOBAL + '[module."//p:base"]\n[module."//p:mid"]\n[module."//p:top"]\n'
        self.assertEqual(self.sym([base, mid, top], 1, policy=policy), [("undeclared-symbol", "base_f")])

    def test_symbols_of_the_own_other_units_are_fine(self):
        target = facts("//p:lib", [unit("a.c.o", defined=["a"], undefined=["b"]), unit("b.c.o", defined=["b"])])
        self.assertEqual(self.sym([target], 0), [])

    def test_test_module_may_use_the_trusted_runtime(self):
        test = facts("//p:test", [unit(defined=["main"], undefined=["ctest_run"])], deps=["//ctest:ctest"], kind="c_test")
        self.assertEqual(self.sym([test], 0), [])

    def test_exit_in_a_test_is_denied(self):
        test = facts("//p:test", [unit(defined=["main"], undefined=["ctest_run", "exit"])], deps=["//ctest:ctest"], kind="c_test")
        self.assertEqual(self.sym([test], 1), [("denied-symbol", "exit")])

    def test_defining_a_libc_symbol_is_a_collision(self):
        self.assertEqual(self.sym([self.lib(defined=["write", "f"])], 1), [("symbol-collision", "write")])

    def test_defining_a_trusted_symbol_is_a_collision(self):
        self.assertEqual(self.sym([self.lib(defined=["ctest_run"])], 1), [("symbol-collision", "ctest_run")])

    def test_weak_definition(self):
        self.assertEqual(self.sym([self.lib(defined=["f"], weak=["f"])], 1), [("weak-symbol", "f")])

    def test_trusted_module_is_not_checked(self):
        self.assertEqual(self.sym([], 0), [])  # CTEST alone: kill/exit/fork are fine there

    def test_module_not_in_policy(self):
        self.assertEqual(self.sym([facts("//p:new", [unit()])], 1, policy=GLOBAL), [("module-not-in-policy", "//p:new")])

    def test_policy_module_without_facts(self):
        self.assertEqual(self.sym([], 1, policy=WITH_TEST), [("policy-module-without-facts", "//p:lib"),
                                                             ("policy-module-without-facts", "//p:test")])

    def test_trusted_module_without_facts_is_a_finding(self):
        outcome, result = self.run_gate("symbols", [self.lib()], expect_code=1)
        self.assertIn("trusted-module-without-facts", [f["rule"] for f in result["findings"]])

    def test_dependency_without_facts(self):
        target = facts("//p:lib", [unit()], deps=["//p:ghost"])
        self.assertEqual(self.sym([target], 1), [("missing-dep-facts", "//p:ghost")])

    # ---- inputs: everything odd is exit 2 and never leaves a PASS behind -------------------
    def test_internal_errors(self):
        good = [self.lib(), CTEST]
        cases = {
            "unknown top key": [dict(self.lib(), extra=1), CTEST],
            "bad schema": [dict(self.lib(), schema=2), CTEST],
            "bool schema": [dict(self.lib(), schema=True), CTEST],
            "bad kind": [dict(self.lib(), kind="cxx_library"), CTEST],
            "bad label": [dict(self.lib(), label="p:lib"), CTEST],
            "duplicate label": good + [self.lib()],
            "weak not defined": [self.lib(weak=["x"]), CTEST],
            "bad symbol": [self.lib(undefined=["a b"]), CTEST],
            "unit key": [facts("//p:lib", [dict(unit(), more=1)]), CTEST],
            "duplicate units": [facts("//p:lib", [unit(), unit()]), CTEST],
            "negative line": [facts("//p:lib", [unit(pragmas=[(-1, "x")])]), CTEST],
        }
        for name, targets in cases.items():
            with self.subTest(name):
                self.setUp()
                outcome, result = self.run_gate("symbols", targets)
                self.assertExit(outcome, 2)
                self.assertEqual(result["findings"][0]["rule"], "internal-error")

    def test_stray_and_empty_inputs(self):
        outcome, _ = self.run_gate("symbols", [])
        self.assertExit(outcome, 2)
        self.setUp()
        fdir = self.sub("facts")
        (fdir / "good.json").write_text(json.dumps(CTEST), encoding="utf-8")
        (fdir / "notes.txt").write_text("x", encoding="utf-8")
        pol = self.tmp / "p.toml"
        pol.write_text(POLICY, encoding="utf-8")
        lib = self.tmp / "l"
        lib.write_text(LIBC, encoding="utf-8")
        argv = ["facts", "--gate", "symbols", "--facts", fdir, "--policy", pol, "--libc", lib]
        self.assertExit(run_rigor(argv), 2)
        os.remove(fdir / "notes.txt")
        os.symlink(fdir / "good.json", fdir / "link.json")
        self.assertExit(run_rigor(argv), 2)

    def test_symbols_gate_needs_libc(self):
        outcome, _ = self.run_gate("symbols", [self.lib(), CTEST], libc=None)
        self.assertExit(outcome, 2)

    def test_empty_libc_is_an_error(self):
        outcome, _ = self.run_gate("symbols", [self.lib(), CTEST], libc="")
        self.assertExit(outcome, 2)

    def test_stale_pass_is_replaced_on_internal_error(self):
        out = self.tmp / "symbols.json"
        out.write_text('{"status":"PASS"}', encoding="utf-8")
        outcome, result = self.run_gate("symbols", [], expect_code=2)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["gate"], "symbols")

    def test_bad_policies(self):
        bad = {
            "no global": '[module."//p:lib"]\n',
            "no deny": '[global]\ntrusted = []\n',
            "unknown key": POLICY + '[extra]\nx = 1\n',
            "exempt not denied": POLICY + '[module."//p:x"]\ndeny_exempt = ["memcpy"]\n',
            "trusted and listed": POLICY + '[module."//ctest:ctest"]\n',
            "bad builtin": POLICY + '[module."//p:x"]\nallow_builtins = ["__builtin_abort"]\n',
            "module key": POLICY + '[module."//p:x"]\nallows = []\n',
            "duplicate": POLICY.replace('deny = ["kill", "exit"', 'deny = ["kill", "kill", "exit"'),
            "not toml": "[[[",
            "bad label": POLICY + '[module."p-x"]\n',
        }
        for name, text in bad.items():
            with self.subTest(name):
                self.setUp()
                outcome, _ = self.run_gate("symbols", [self.lib(), CTEST], policy=text)
                self.assertExit(outcome, 2)

    def test_gate_choice_is_required_and_checked(self):
        self.assertExit(run_rigor(["facts", "--facts", self.tmp, "--policy", self.tmp]), 2)
        self.assertExit(run_rigor(["facts", "--gate", "tests", "--facts", self.tmp, "--policy", self.tmp]), 2)
