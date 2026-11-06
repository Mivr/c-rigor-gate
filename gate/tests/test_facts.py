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


def unit(name="a.c.o", defined=(), undefined=(), weak=(), pragmas=(), attributes=(), identifiers=(),
         line_directives=(), mutable=()):
    return {"name": name, "defined": sorted(defined), "weak": sorted(weak), "undefined": sorted(undefined),
            "mutable": sorted(mutable),
            "pragmas": [{"file": "p/a.c", "line": n, "text": t} for n, t in pragmas],
            "attributes": [{"name": a, "file": "p/a.c", "line": n} for a, n in attributes],
            "identifiers": [{"name": a, "file": "p/a.c", "line": n} for a, n in identifiers],
            "line_directives": [{"name": a, "file": "p/a.c", "line": n} for a, n in line_directives]}


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

    def test_line_directive_is_a_finding(self):
        self.assertEqual(self.sem([unit(line_directives=[("buck-out/x/stdio.h", 3)])], 1),
                         [("line-directive", "buck-out/x/stdio.h")])

    def test_unknown_scanner_identifier_fails_closed(self):
        # Every `__builtin_*` is now a builtin the table decides (T014); a name that is neither
        # watched nor a macro/include fact means scanner and table drifted.
        for name in ("printf", "__builtin", "#pragma once"):
            with self.subTest(name=name):
                self.setUp()
                outcome, _ = self.run_gate("semantic-suppressions",
                                           [facts("//p:lib", [unit(identifiers=[(name, 1)])]), CTEST])
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


MBED = "gate//third_party/mbedtls:mbedtls"
PERMIT = 'third_party = ["%s"]\n' % MBED
TP_ALLOWED = MBED + "\n"
TP_PREFIXES = "mbedtls_\npsa_\n"
PEER = "gate//third_party/tls_peer:tls_peer"
TP_TEST_ALLOWED = PEER + "\n"


def tp_facts(label=MBED, units=None):
    """What the `c_third_party` facts target writes: symbols only, from the objects."""
    units = units or [unit("ssl_tls.c.o", defined=["mbedtls_ssl_read", "mbedtls_ssl_write", "psa_crypto_init"],
                           undefined=["memcpy", "getrandom", "fopen"])]
    return facts(label, units, kind="c_third_party")


class ThirdPartyFactsCase(TempDirTestCase):
    run_gate = FactsCase.run_gate
    rules = FactsCase.rules

    def tp_dir(self, allowed=TP_ALLOWED, prefixes=TP_PREFIXES, test_allowed=TP_TEST_ALLOWED):
        directory = self.sub("tp")
        (directory / "ALLOWED_LABELS").write_text(allowed, encoding="utf-8")
        (directory / "ALLOWED_TEST_LABELS").write_text(test_allowed, encoding="utf-8")
        (directory / "RESERVED_PREFIXES").write_text(prefixes, encoding="utf-8")
        return directory

    def tsym(self, targets, code, permit=True, tp=None, **kw):
        tp = tp_facts() if tp is None else tp
        if "policy" not in kw:
            kw["policy"] = GLOBAL + "".join(
                '[module."%s"]\n%s' % (t["label"], PERMIT if permit else "")
                for t in targets)
        extra = kw.pop("extra", ["--third-party", self.tp_dir()])
        return self.rules("symbols", targets + [CTEST, tp], code, extra=extra, **kw)

    def user(self, undefined=("mbedtls_ssl_read",), defined=("f",), deps=(MBED,)):
        return facts("//p:user", [unit(defined=defined, undefined=undefined)], deps=deps)

    def test_a_permitted_module_may_use_the_library_s_exports(self):
        self.assertEqual(self.tsym([self.user(undefined=["mbedtls_ssl_read", "psa_crypto_init"])], 0), [])

    def test_a_dependency_without_policy_permission_fails(self):
        self.assertEqual(self.tsym([self.user()], 1, permit=False),
                         [("third-party-not-permitted", MBED), ("undeclared-symbol", "mbedtls_ssl_read")])

    def test_permission_is_per_module(self):
        other = facts("//p:other", [unit(undefined=["mbedtls_ssl_write"])], deps=[MBED])
        policy = GLOBAL + '[module."//p:user"]\n' + PERMIT + '[module."//p:other"]\n'
        self.assertEqual(self.tsym([self.user(), other], 1, policy=policy),
                         [("third-party-not-permitted", MBED), ("undeclared-symbol", "mbedtls_ssl_write")])

    def test_a_symbol_the_library_does_not_export_is_undeclared(self):
        self.assertEqual(self.tsym([self.user(undefined=["mbedtls_ssl_read", "mbedtls_made_up"])], 1),
                         [("undeclared-symbol", "mbedtls_made_up")])

    def test_exports_need_a_direct_dependency(self):
        self.assertEqual(self.tsym([self.user(deps=[])], 1), [("undeclared-symbol", "mbedtls_ssl_read")])

    def test_exports_are_not_transitive(self):
        mid = facts("//p:mid", [unit(defined=["mid_f"], undefined=["mbedtls_ssl_read"])], deps=[MBED])
        top = facts("//p:top", [unit(undefined=["mid_f", "mbedtls_ssl_read"])], deps=["//p:mid"])
        policy = GLOBAL + '[module."//p:mid"]\n' + PERMIT + '[module."//p:top"]\n' + PERMIT
        self.assertEqual(self.tsym([mid, top], 1, policy=policy), [("undeclared-symbol", "mbedtls_ssl_read")])

    def test_defining_a_symbol_the_library_exports_is_a_collision(self):
        self.assertEqual(self.tsym([self.user(defined=["mbedtls_ssl_read"], undefined=[])], 1),
                         [("symbol-collision", "mbedtls_ssl_read")])

    def test_a_collision_is_found_even_without_a_dependency(self):
        self.assertEqual(self.tsym([self.user(defined=["psa_crypto_init"], undefined=[], deps=[])], 1),
                         [("symbol-collision", "psa_crypto_init")])

    def test_reserved_prefixes_hold_without_the_library_s_facts(self):
        user = facts("//p:user", [unit(defined=["mbedtls_ssl_read", "psa_anything", "mbedtls", "f"])])
        policy = GLOBAL + '[module."//p:user"]\n'
        outcome, result = self.run_gate("symbols", [user, CTEST], policy=policy, expect_code=1,
                                        extra=["--third-party", self.tp_dir()])
        self.assertEqual(sorted((f["rule"], f["symbol"]) for f in result["findings"]),
                         [("symbol-collision", "mbedtls_ssl_read"), ("symbol-collision", "psa_anything")])

    def test_a_weak_definition_of_a_reserved_name_is_both(self):
        user = self.user(defined=["psa_x"], undefined=[], deps=[])
        user["units"][0]["weak"] = ["psa_x"]
        self.assertEqual(self.tsym([user], 1), [("symbol-collision", "psa_x"), ("weak-symbol", "psa_x")])

    def test_the_library_itself_is_not_scanned(self):
        # Its own undefined symbols (fopen is denied) and a pragma in its facts are not findings.
        noisy = tp_facts(units=[unit("a.c.o", defined=["mbedtls_x"], undefined=["fopen", "kill", "exit"],
                                     pragmas=[(1, "clang diagnostic ignored \"-Wall\"")],
                                     attributes=[("weak", 2)], identifiers=[("__asm__", 3)])])
        self.assertEqual(self.tsym([self.user(undefined=["mbedtls_x"])], 0, tp=noisy), [])
        outcome, result = self.run_gate("semantic-suppressions", [facts("//p:lib", [unit()]), CTEST, noisy],
                                        expect_code=0, extra=["--third-party", self.tp_dir()])
        self.assertEqual(result["findings"], [])

    def test_a_library_the_allowlist_does_not_name_is_refused(self):
        rogue = tp_facts(label="gate//third_party/rogue:rogue")
        self.assertEqual(self.tsym([self.user()], 1, tp=rogue, permit=False),
                         [("missing-dep-facts", MBED), ("third-party-not-allowed", "gate//third_party/rogue:rogue"),
                          ("undeclared-symbol", "mbedtls_ssl_read")])
        outcome, result = self.run_gate("semantic-suppressions", [facts("//p:lib", [unit()]), CTEST, rogue],
                                        expect_code=1, extra=["--third-party", self.tp_dir()])
        self.assertEqual([f["rule"] for f in result["findings"]], ["third-party-not-allowed"])

    def test_the_kind_alone_does_not_make_a_product_label_trusted(self):
        # A product-cell label with the same path is not the gate's library.
        fake = tp_facts(label="//third_party/mbedtls:mbedtls")
        fake["label"] = "root//third_party/mbedtls:mbedtls"
        outcome, result = self.run_gate("symbols", [fake, CTEST], expect_code=1, policy=GLOBAL,
                                        extra=["--third-party", self.tp_dir()])
        self.assertIn("third-party-not-allowed", [f["rule"] for f in result["findings"]])

    def test_the_gate_cell_may_print_the_label_without_the_cell(self):
        # With the gate as the root cell Buck2 prints `//third_party/mbedtls:mbedtls`.
        tp = tp_facts(label="//third_party/mbedtls:mbedtls")
        user = self.user(deps=["//third_party/mbedtls:mbedtls"])
        self.assertEqual(self.tsym([user], 0, tp=tp), [])

    def test_a_product_kind_facts_file_cannot_pose_as_a_library(self):
        # A c_library with the allowlisted label is an ordinary module: it needs a policy entry like any other.
        posing = facts(MBED, [unit(defined=["f"], undefined=["fopen"])])
        outcome, result = self.run_gate("symbols", [posing, CTEST], policy=GLOBAL, expect_code=1,
                                        extra=["--third-party", self.tp_dir()])
        self.assertEqual(sorted(f["rule"] for f in result["findings"]), ["denied-symbol", "module-not-in-policy"])

    def test_the_library_not_built_is_a_missing_dependency(self):
        outcome, result = self.run_gate("symbols", [self.user(), CTEST], expect_code=1,
                                        policy=GLOBAL + '[module."//p:user"]\n' + PERMIT,
                                        extra=["--third-party", self.tp_dir()])
        self.assertEqual(sorted(f["rule"] for f in result["findings"]), ["missing-dep-facts", "undeclared-symbol"])

    def test_the_default_lists_are_the_gate_s_own(self):
        outcome, result = self.run_gate("symbols", [self.user(), CTEST, tp_facts()], expect_code=0,
                                        policy=GLOBAL + '[module."//p:user"]\n' + PERMIT)
        self.assertEqual(result["findings"], [])
        self.setUp()
        user = facts("//p:user", [unit(defined=["mbedtls_ssl_read"])])
        outcome, result = self.run_gate("symbols", [user, CTEST], expect_code=1, policy=GLOBAL + '[module."//p:user"]\n')
        self.assertEqual([f["rule"] for f in result["findings"]], ["symbol-collision"])

    def test_policy_defects_are_exit_2(self):
        bad = {
            "permission for an unlisted label": GLOBAL + '[module."//p:user"]\nthird_party = ["gate//third_party/rogue:rogue"]\n',
            "permission is a string": GLOBAL + '[module."//p:user"]\nthird_party = "%s"\n' % MBED,
            "permission is not a label": GLOBAL + '[module."//p:user"]\nthird_party = ["mbedtls"]\n',
            "duplicate permission": GLOBAL + '[module."//p:user"]\nthird_party = ["%s", "%s"]\n' % (MBED, MBED),
            "module entry for the library": GLOBAL + '[module."//p:user"]\n[module."%s"]\n' % MBED,
        }
        for name, policy in bad.items():
            with self.subTest(name):
                self.setUp()
                outcome, _ = self.run_gate("symbols", [self.user(), CTEST, tp_facts()], policy=policy,
                                           extra=["--third-party", self.tp_dir()])
                self.assertExit(outcome, 2)

    def test_list_defects_are_exit_2(self):
        for allowed, prefixes in (("# c\n" + TP_ALLOWED, TP_PREFIXES), (TP_ALLOWED, "mbedtls\n"), (TP_ALLOWED, "\n"),
                                  (TP_ALLOWED, "psa_\npsa_\n"), (TP_ALLOWED.rstrip("\n"), TP_PREFIXES),
                                  (TP_ALLOWED, "psa_"), ("gate//x:y\n", TP_PREFIXES), (TP_ALLOWED, "_x_\n")):
            with self.subTest(allowed=allowed, prefixes=prefixes):
                self.setUp()
                outcome, _ = self.run_gate("symbols", [self.user(), CTEST, tp_facts()], expect_code=2,
                                           policy=GLOBAL + '[module."//p:user"]\n' + PERMIT,
                                           extra=["--third-party", self.tp_dir(allowed, prefixes)])

    def test_missing_list_files_and_directory_are_exit_2(self):
        for case in ("ALLOWED_LABELS", "ALLOWED_TEST_LABELS", "RESERVED_PREFIXES", "dir"):
            with self.subTest(case=case):
                self.setUp()
                directory = self.tp_dir()
                if case == "dir":
                    directory = self.tmp / "nope"
                else:
                    os.remove(directory / case)
                outcome, _ = self.run_gate("symbols", [self.user(), CTEST, tp_facts()], expect_code=2,
                                           policy=GLOBAL + '[module."//p:user"]\n' + PERMIT,
                                           extra=["--third-party", directory])

    def test_symlinked_list_is_exit_2(self):
        directory = self.tp_dir()
        os.remove(directory / "ALLOWED_LABELS")
        real = self.tmp / "real"
        real.write_text(TP_ALLOWED, encoding="utf-8")
        os.symlink(real, directory / "ALLOWED_LABELS")
        outcome, _ = self.run_gate("symbols", [self.user(), CTEST, tp_facts()], expect_code=2,
                                   policy=GLOBAL + '[module."//p:user"]\n' + PERMIT, extra=["--third-party", directory])

    def test_a_label_in_both_lists_is_exit_2(self):
        directory = self.tp_dir(test_allowed=TP_ALLOWED)
        self.run_gate("symbols", [self.user(), CTEST, tp_facts()], expect_code=2,
                      policy=GLOBAL + '[module."//p:user"]\n' + PERMIT, extra=["--third-party", directory])

    def test_a_symlinked_test_list_is_exit_2(self):
        directory = self.tp_dir()
        os.remove(directory / "ALLOWED_TEST_LABELS")
        real = self.tmp / "real"
        real.write_text(TP_TEST_ALLOWED, encoding="utf-8")
        os.symlink(real, directory / "ALLOWED_TEST_LABELS")
        self.run_gate("symbols", [self.user(), CTEST, tp_facts()], expect_code=2,
                      policy=GLOBAL + '[module."//p:user"]\n' + PERMIT, extra=["--third-party", directory])


class TestOnlyLibraryCase(TempDirTestCase):
    """The TLS test peer is trusted and unscanned, but only a `c_test` may reach it."""

    run_gate = FactsCase.run_gate
    rules = FactsCase.rules
    tp_dir = ThirdPartyFactsCase.tp_dir

    def peer(self, label=PEER):
        return tp_facts(label, [unit("tls_peer.c.o", defined=["tls_peer_start", "tls_peer_step"],
                                     undefined=["srv_mbedtls_ssl_handshake", "memcpy"])])

    def graph(self, targets, code, permit=("//p:t",)):
        policy = GLOBAL + "".join('[module."%s"]\n%s' % (t["label"], 'third_party = ["%s"]\n' % PEER if t["label"] in permit else "")
                                  for t in targets)
        return self.rules("symbols", targets + [CTEST, self.peer()], code, policy=policy,
                          extra=["--third-party", self.tp_dir()])

    def node(self, label, kind, deps, undefined=()):
        return facts(label, [unit(defined=[label.split(":")[1]], undefined=undefined)], deps=deps, kind=kind)

    def test_a_test_may_use_it(self):
        t = self.node("//p:t", "c_test", [PEER], ["tls_peer_start"])
        self.assertEqual(self.graph([t], 0), [])

    def test_a_library_may_not_name_it(self):
        lib = self.node("//p:lib", "c_library", [PEER], ["tls_peer_start"])
        self.assertEqual(self.graph([lib], 1, permit=("//p:lib",)), [("test-only-dep", PEER)])

    def test_a_binary_and_a_fuzzer_may_not_name_it(self):
        for kind in ("c_binary", "c_fuzz"):
            with self.subTest(kind=kind):
                self.setUp()
                node = self.node("//p:x", kind, [PEER])
                self.assertEqual(self.graph([node], 1, permit=("//p:x",)), [("test-only-dep", PEER)])

    def test_transitive_through_libraries_and_through_a_test(self):
        t = self.node("//p:t", "c_test", [PEER])
        mid = self.node("//p:mid", "c_library", ["//p:t"])
        top = self.node("//p:top", "c_binary", ["//p:mid"])
        self.assertEqual(self.graph([t, mid, top], 1),
                         [("test-only-dep", PEER), ("test-only-dep", PEER)])

    def test_a_dep_without_facts_that_names_the_label_is_still_refused(self):
        lib = self.node("//p:lib", "c_library", [PEER])
        outcome, result = self.run_gate("symbols", [lib, CTEST], expect_code=1,
                                        policy=GLOBAL + '[module."//p:lib"]\n', extra=["--third-party", self.tp_dir()])
        self.assertEqual(sorted(f["rule"] for f in result["findings"]), ["missing-dep-facts", "test-only-dep"])

    def test_the_gate_cell_spelling_is_the_same_label(self):
        peer = self.peer("//third_party/tls_peer:tls_peer")
        lib = self.node("//p:lib", "c_library", ["//third_party/tls_peer:tls_peer"])
        policy = GLOBAL + '[module."//p:lib"]\n'
        self.assertEqual(self.rules("symbols", [lib, CTEST, peer], 1, policy=policy, extra=["--third-party", self.tp_dir()]),
                         [("test-only-dep", "//third_party/tls_peer:tls_peer"),
                          ("third-party-not-permitted", "//third_party/tls_peer:tls_peer")])

    def test_defining_the_peer_s_names_is_a_collision(self):
        for name in ("srv_start", "srv_mbedtls_ssl_read", "tls_peer_start"):
            with self.subTest(name=name):
                self.setUp()
                lib = facts("//p:lib", [unit(defined=[name])])
                policy = GLOBAL + '[module."//p:lib"]\n'
                self.assertEqual(self.rules("symbols", [lib, CTEST, self.peer()], 1, policy=policy,
                                            extra=["--third-party", self.tp_dir(prefixes="mbedtls_\npsa_\nsrv_\ntls_peer_\n")]),
                                 [("symbol-collision", name)])

    def test_calling_the_peer_without_depending_on_it_is_undeclared(self):
        lib = facts("//p:lib", [unit(defined=["f"], undefined=["tls_peer_start"])])
        self.assertEqual(self.rules("symbols", [lib, CTEST, self.peer()], 1, policy=GLOBAL + '[module."//p:lib"]\n',
                                    extra=["--third-party", self.tp_dir()]), [("undeclared-symbol", "tls_peer_start")])

    def test_the_default_lists_name_the_peer_as_test_only(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                               "third_party", "ALLOWED_TEST_LABELS"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), PEER + "\n")
