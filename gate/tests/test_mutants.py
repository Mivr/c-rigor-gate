"""Tests of `rigor mutants`: verdicts derived from raw report facts, and every way the gate must fail."""

import json

from tests.helpers import Repo, Signer, TempDirTestCase, read_json, run_rigor

LABEL = "//m:mod_mutants"
H = ["%064x" % n for n in range(1, 40)]  # distinct object hashes
BASE = H[0]
BASE0 = H[30]  # the unmodified source at -O0


def results(*lines):
    """JSON Lines text of a ctest binary: each line is (status, asserts, reason)."""
    rows = []
    for number, (status, asserts, reason) in enumerate(lines, start=1):
        rows.append(json.dumps({"id": "s/t%d" % number, "status": status, "asserts": asserts, "reason": reason}))
    passed = sum(1 for line in lines if line[0] == "pass")
    rows.append(json.dumps({"summary": {"total": len(lines), "passed": passed}}))
    return "\n".join(rows) + "\n"


PASS = {"rc": 0, "timed_out": False, "results": results(("pass", 2, ""))}
KILLED = {"rc": 1, "timed_out": False,
          "results": results(("fail", 2, "1 of 2 checks failed; first: f.c:3: CHECK(x): 1 != 2"))}
CRASH = {"rc": 1, "timed_out": False, "results": results(("fail", 1, "killed by signal 11"))}
TIMEOUT = {"rc": 1, "timed_out": False, "results": results(("fail", 1, "timeout after 10 s"))}
KILLED_BY_WATCHDOG = {"rc": -9, "timed_out": True, "results": None}


def mutant(number, function="f", operator="relational", status="ok", digest=None, runs=None, line=3, o0=None):
    """`o0`: the hash of the mutant compiled again at -O0, given for a candidate for equivalent / duplicate."""
    item = {"id": "%016x" % number, "file": "m/a.c", "begin_offset": number, "end_offset": number + 1,
            "original": "<", "replacement": "<=", "operator": operator, "function": function, "line": line,
            "compile": {"status": status, "hash": "" if status == "unviable" else (digest or H[number])},
            "runs": {"t": KILLED} if runs is None and status == "ok" else (runs or {})}
    if o0 is not None:
        item["compile"]["o0"] = {"status": "ok", "hash": o0}
    return item


def report(mutants, functions=("f",), baseline=PASS, original=BASE, label=LABEL, tests=("t",), skipped=(), hidden=()):
    return {
        "schema": 1, "label": label, "tests": list(tests),
        "sources": [{"file": "m/a.c", "sha256": "0" * 64, "definitions": len(functions) + len(skipped),
                     "functions": [{"name": n, "line": 1} for n in functions], "skipped": list(skipped),
                     "hidden": list(hidden),
                     "baseline": {"status": "ok", "hash": BASE}, "baseline_o0": {"status": "ok", "hash": BASE0},
                     "original": {"status": "ok", "hash": original}}],
        "baseline_runs": {t: baseline for t in tests}, "mutants": mutants,
    }


class MutantsTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.results = self.sub("results")
        self.policy = self.tmp / "policy.toml"
        self.write_policy("L3")

    def write_policy(self, level, label=LABEL):
        self.policy.write_text('[module."%s"]\nlevel = "%s"\n' % (label, level), encoding="utf-8")

    def put(self, document, name="mod.json"):
        (self.results / name).write_text(json.dumps(document), encoding="utf-8")

    def grade(self, extra=()):
        out = self.tmp / "out.json"
        outcome = run_rigor(["mutants", "--results", self.results, "--policy", self.policy, "--out", out]
                            + list(extra))
        return outcome, (read_json(out) if out.exists() else None)

    def rules(self, result):
        return sorted(f["rule"] for f in result["findings"])

    def fails_with(self, document, *rules, level="L3"):
        self.write_policy(level)
        self.put(document)
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), sorted(rules), result)
        return result

    # -- green -------------------------------------------------------------------------------
    def test_all_killed_by_a_check_failure_passes(self):
        self.put(report([mutant(1), mutant(2, operator="arithmetic")]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        module = result["metadata"]["modules"][LABEL]
        self.assertEqual((module["total"], module["verdicts"]["killed-assert"]), (2, 2))
        self.assertEqual(module["operators"], {"relational": 1, "arithmetic": 1})
        self.assertEqual(module["survivors"], [])

    def test_result_is_deterministic(self):
        self.put(report([mutant(1), mutant(2, runs={"t": PASS})]))
        first, _ = self.grade()
        data = (self.tmp / "out.json").read_bytes()
        second, _ = self.grade()
        self.assertEqual((first.code, second.code), (1, 1))
        self.assertEqual(data, (self.tmp / "out.json").read_bytes())

    # -- red: survivors ----------------------------------------------------------------------
    def test_a_known_survivor_is_reported_as_a_survivor_with_its_place_and_change(self):
        result = self.fails_with(report([mutant(1), mutant(2, operator="arithmetic", runs={"t": PASS}, line=7)]),
                                 "survived-mutant")
        found = result["findings"][0]
        self.assertEqual((found["id"], found["line"], found["operator"], found["replacement"], found["function"]),
                         ("%016x" % 2, 7, "arithmetic", "<=", "f"))
        self.assertEqual(result["metadata"]["modules"][LABEL]["survivors"][0]["at"], "m/a.c:7")

    def test_a_survivor_in_an_l2_module_is_only_reported(self):
        self.write_policy("L2")
        self.put(report([mutant(1), mutant(2, runs={"t": PASS})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(self.rules(result), ["survivor"])
        self.assertEqual(result["findings"][0]["severity"], "info")

    def test_one_test_passing_is_not_enough_to_kill_but_one_failing_check_is(self):
        two = report([mutant(1, runs={"a": PASS, "b": KILLED}), mutant(2, runs={"a": PASS, "b": PASS})],
                     tests=("a", "b"))
        result = self.fails_with(two, "survived-mutant")
        self.assertEqual(result["findings"][0]["id"], "%016x" % 2)

    def test_a_check_failure_beats_a_crash_for_the_verdict(self):
        both = report([mutant(1, runs={"a": CRASH, "b": KILLED})], tests=("a", "b"))
        self.put(both)
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["verdicts"]["killed-assert"], 1)

    # -- red: blind generator ----------------------------------------------------------------
    def test_a_generator_that_found_no_mutants_fails(self):
        self.fails_with(report([]), "no-mutants", "unaccounted-function")

    def test_a_source_with_functions_but_no_mutants_fails_even_if_others_have_some(self):
        document = report([mutant(1)])
        document["sources"].append({"file": "m/b.c", "sha256": "0" * 64, "definitions": 1,
                                    "functions": [{"name": "g", "line": 1}],
                                    "skipped": [], "hidden": [], "baseline": {"status": "ok", "hash": BASE},
                                    "baseline_o0": {"status": "ok", "hash": BASE0},
                                    "original": {"status": "ok", "hash": BASE}})
        self.fails_with(document, "no-mutants", "unaccounted-function")

    def test_a_module_that_has_no_mutants_at_all_fails_even_without_functions(self):
        # T008: a gate that silently mutates nothing must fail. A pure-data module is L1, by policy.
        for level in ("L2", "L3"):
            self.fails_with(report([], functions=()), "no-mutants", level=level)

    def test_a_module_whose_every_source_is_empty_fails_even_if_a_second_report_has_mutants(self):
        document = report([], functions=())
        document["sources"].append({"file": "m/b.c", "sha256": "0" * 64, "definitions": 0,
                                    "functions": [],
                                    "skipped": [], "hidden": [], "baseline": {"status": "ok", "hash": BASE},
                                    "baseline_o0": {"status": "ok", "hash": BASE0},
                                    "original": {"status": "ok", "hash": BASE}})
        self.fails_with(document, "no-mutants")

    # -- B19: every function definition is accounted for (the count comes from the generator's own AST audit)
    def test_a_function_the_generator_lost_fails_even_if_other_functions_have_mutants(self):
        document = report([mutant(1)])
        document["sources"][0]["definitions"] = 2  # the audit saw two definitions, the lists name one
        result = self.fails_with(document, "unaccounted-function")
        self.assertEqual(result["findings"][0]["problems"], {"listed": 1})
        self.write_policy("L2")
        outcome, _ = self.grade()
        self.assertExit(outcome, 1)  # not a matter of level

    def test_a_function_with_neither_a_mutant_nor_a_reason_fails(self):
        result = self.fails_with(report([mutant(1)], functions=("f", "g")), "unaccounted-function")
        self.assertEqual(result["findings"][0]["problems"], {"no mutant and no reason": ["g"]})

    def test_a_function_with_the_reason_no_mutable_token_is_an_error_in_l3_and_info_in_l2(self):
        document = report([mutant(1)], functions=("f", "g"))
        document["sources"][0]["functions"][1]["reason"] = "no-mutable-token"
        self.put(document)
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual([(f["rule"], f["severity"], f["function"]) for f in result["findings"]],
                         [("no-mutable-token", "error", "g")])
        self.write_policy("L2")
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual([(f["rule"], f["severity"], f["function"]) for f in result["findings"]],
                         [("no-mutable-token", "info", "g")])

    def test_a_reason_for_a_function_that_has_mutants_is_a_lie(self):
        document = report([mutant(1)])
        document["sources"][0]["functions"][0]["reason"] = "no-mutable-token"
        self.fails_with(document, "unaccounted-function")

    def test_a_mutant_of_a_function_nobody_listed_fails(self):
        result = self.fails_with(report([mutant(1), mutant(2, function="ghost")]), "unaccounted-function")
        self.assertEqual(result["findings"][0]["problems"], {"mutants of unlisted functions": ["ghost"]})

    def test_a_function_listed_twice_or_listed_and_skipped_fails(self):
        self.fails_with(report([mutant(1)], functions=("f", "f")), "unaccounted-function")
        both = [{"name": "f", "file": "m/a.c", "reason": "macro"}]
        self.fails_with(report([mutant(1)], skipped=both), "unaccounted-function", "unmutated-function")

    def test_a_report_without_the_count_or_with_a_bad_function_entry_is_exit_2(self):
        for tamper in (lambda s: s.pop("definitions"), lambda s: s.update(definitions="1"),
                       lambda s: s["functions"][0].update(reason="why not"),
                       lambda s: s["functions"][0].update(extra=1)):
            document = report([mutant(1)])
            tamper(document["sources"][0])
            self.put(document)
            outcome, _ = self.grade()
            self.assertExit(outcome, 2)

    # -- unviable-ratio (B11): code shaped so that mutants do not compile escapes mutation ------
    def unviable_report(self, unviable, total):
        mutants = [mutant(n, status="unviable") if n <= unviable else mutant(n, digest="%064x" % (n + 100))
                   for n in range(1, total + 1)]
        return report(mutants)

    def test_more_than_a_quarter_unviable_fails_at_l3_and_above(self):
        for level in ("L3", "L4", "L5"):
            result = self.fails_with(self.unviable_report(5, 19), "unviable-ratio", level=level)
            found = result["findings"][0]
            self.assertEqual((found["module"], found["unviable"], found["total"]), (LABEL, 5, 19))

    def test_exactly_a_quarter_unviable_is_accepted(self):
        for unviable, total in ((1, 4), (5, 20), (25, 100)):
            self.put(self.unviable_report(unviable, total))
            outcome, result = self.grade()
            self.assertExit(outcome, 0)
            self.assertEqual(self.rules(result), [], (unviable, total))

    def test_one_more_than_a_quarter_fails(self):
        for unviable, total in ((2, 7), (26, 100), (6, 20)):
            self.fails_with(self.unviable_report(unviable, total), "unviable-ratio")

    def test_in_an_l2_module_the_ratio_is_info_only(self):
        self.write_policy("L2")
        self.put(self.unviable_report(5, 19))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(self.rules(result), ["unviable-ratio"])
        self.assertEqual(result["findings"][0]["severity"], "info")

    def test_the_ratio_is_of_all_generated_mutants(self):
        # 3 unviable of 12 generated is a quarter; 3 of 11 is not.
        twelve = [mutant(n, status="unviable") for n in (1, 2, 3)] + [mutant(n) for n in range(4, 13)]
        self.put(report(twelve))
        self.assertExit(self.grade()[0], 0)
        eleven = [mutant(n, status="unviable") for n in (1, 2, 3)] + [mutant(n) for n in range(4, 12)]
        self.fails_with(report(eleven), "unviable-ratio")

    # -- levels L4 and L5 are at least as strict as L3 ----------------------------------------
    def test_l4_and_l5_modules_fail_on_a_survivor(self):
        for level in ("L4", "L5"):
            self.fails_with(report([mutant(1), mutant(2, runs={"t": PASS})]), "survived-mutant", level=level)

    def test_l4_and_l5_modules_pass_when_everything_is_killed(self):
        for level in ("L4", "L5"):
            self.write_policy(level)
            self.put(report([mutant(1)]))
            self.assertExit(self.grade()[0], 0)

    def test_l4_applies_the_per_function_rules_of_l3(self):
        self.fails_with(report([mutant(1, runs={"t": CRASH})]), "crash-only-function", level="L4")

    def test_everything_unviable_fails(self):
        self.fails_with(report([mutant(1, status="unviable"), mutant(2, status="unviable")]),
                        "all-unviable", "no-assert-kill-function")

    # -- R002 F1: code a product macro wrote inside a mutated function
    def test_macro_hidden_code_fails_l3_with_file_line_and_macro_and_is_info_in_l2(self):
        use = {"function": "f", "macro": "FAST_PATH", "line": 27, "defined_in": "m/a.c"}
        result = self.fails_with(report([mutant(1)], hidden=[use]), "macro-hidden-code")
        found = result["findings"][0]
        self.assertEqual((found["file"], found["line"], found["macro"], found["function"], found["severity"]),
                         ("m/a.c", 27, "FAST_PATH", "f", "error"))
        self.write_policy("L2")
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual([(f["rule"], f["severity"]) for f in result["findings"]
                          if f["rule"] == "macro-hidden-code"], [("macro-hidden-code", "info")])

    def test_macro_hidden_code_in_an_unlisted_function_is_unaccounted(self):
        use = {"function": "ghost", "macro": "M", "line": 2, "defined_in": "m/a.c"}
        self.fails_with(report([mutant(1)], hidden=[use]), "macro-hidden-code", "unaccounted-function")

    def test_a_malformed_hidden_list_is_exit_2(self):
        for bad in ("x", [{"function": "f"}], [{"function": "f", "macro": "M", "line": "2",
                                                "defined_in": "m/a.c"}]):
            document = report([mutant(1)])
            document["sources"][0]["hidden"] = bad
            self.put(document)
            self.assertExit(self.grade()[0], 2)

    def test_a_report_without_the_hidden_list_is_exit_2(self):
        document = report([mutant(1)])
        del document["sources"][0]["hidden"]
        self.put(document)
        self.assertExit(self.grade()[0], 2)

    def test_a_function_no_mutant_can_reach_fails_l3_and_is_info_in_l2(self):
        hidden = [{"name": "made_by_macro", "file": "m/a.c", "reason": "macro"},
                  {"name": "inline_fn", "file": "m/a.h", "reason": "header"}]
        result = self.fails_with(report([mutant(1)], skipped=hidden), "unmutated-function", "unmutated-function")
        self.assertEqual(sorted(f["function"] for f in result["findings"]), ["inline_fn", "made_by_macro"])
        self.write_policy("L2")
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual({f["severity"] for f in result["findings"]}, {"info"})

    def test_a_header_found_through_buck_out_is_reported_by_its_product_path(self):
        header = "buck-out/v2/gen/root/0123abcd/m/__m__/buck-headers/m/src/internal.h"
        hidden = [{"name": "ctx_key", "file": header, "reason": "header"},
                  {"name": "plain", "file": "m/a.h", "reason": "header"}]
        result = self.fails_with(report([mutant(1)], skipped=hidden), "unmutated-function", "unmutated-function")
        self.assertEqual({f["function"]: f["file"] for f in result["findings"]},
                         {"ctx_key": "m/src/internal.h", "plain": "m/a.h"})

    def reported_headers(self, files, reason="header"):
        hidden = [{"name": "f%d" % n, "file": file, "reason": reason} for n, file in enumerate(files)]
        self.put(report([mutant(1)], skipped=hidden))
        outcome, result = self.grade()
        return outcome.code, sorted(f["file"] for f in result["findings"] if f["rule"] == "unmutated-function")

    def test_a_third_party_toolchain_or_system_header_is_not_reported(self):
        tree = "buck-out/v2/gen/%s/0123abcd/%s/buck-headers/%s"
        outside = [tree % ("gate", "third_party/mbedtls/__mbedtls__", "psa/crypto_struct.h"),  # another cell
                   tree % ("root", "third_party/x/__x__", "mbedtls/ssl.h"),  # under no package of the product
                   tree % ("gate", "third_party/x/__x__", "m/ssl.h"),  # another cell, a package-like name
                   "third_party/mbedtls/include/mbedtls/ssl.h", "external/zlib/zlib.h",
                   "buck-out/v2/art/gate/third_party/mbedtls/__mbedtls_headers__/65eb23d4c25a5c9c/buck-headers/mbedtls/cipher.h",
                   "buck-out/v2/art/toolchains/__sysroot__/0123abcd/buck-headers/m/x.h",  # another cell, `m` by name
                   "/work/tree/buck-out/v2/art/gate/third_party/x/__x__/0123abcd/buck-headers/m/y.h",
                   "/usr/include/x86_64-linux-gnu/bits/stdio.h"]
        self.assertEqual(self.reported_headers(outside + ["m/a.h"]), (1, ["m/a.h"]))

    def test_an_art_header_of_the_product_is_reported_by_its_product_path(self):
        header = "buck-out/v2/art/root/m/__m__/1cb38945d4577fdd/buck-headers/m/src/internal.h"
        self.assertEqual(self.reported_headers([header]), (1, ["m/src/internal.h"]))

    def test_the_real_annas_paths_verbatim(self):
        self.policy.write_text('[module."//m:mod_mutants"]\nlevel = "L3"\n[module."//annas:annas"]\nlevel = "L3"\n',
                               encoding="utf-8")
        hidden = [{"name": "mbed", "reason": "header", "file":
                   "buck-out/v2/art/gate/third_party/mbedtls/__mbedtls_headers__/65eb23d4c25a5c9c/buck-headers/mbedtls/cipher.h"},
                  {"name": "ctx_key", "reason": "header", "file":
                   "buck-out/v2/art/root/annas/__annas__/1cb38945d4577fdd/buck-headers/annas/src/internal.h"}]
        self.put(report([mutant(1)]), "a.json")
        self.put(report([mutant(1)], label="//annas:annas", skipped=hidden), "b.json")
        outcome, result = self.grade()
        self.assertEqual([(f["function"], f["file"]) for f in result["findings"] if f["rule"] == "unmutated-function"],
                         [("ctx_key", "annas/src/internal.h")])

    def test_an_absolute_path_outside_the_known_roots_is_still_reported(self):
        odd = ["/home/x/proj/a.h", "/opt/toolchain/include/b.h", "/work/tree/buck-out/v2/art/root/m/__m__/0123abcd/buck-headers/m/c.h"]
        self.assertEqual(self.reported_headers(odd + ["/usr/include/stdio.h"]),
                         (1, sorted(odd[:2] + ["m/c.h"])))

    def test_a_product_header_is_reported_by_its_package_relative_path(self):
        own = "buck-out/v2/gen/root/0123abcd/m/sub/__sub__/buck-headers/m/sub/b.h"
        self.assertEqual(self.reported_headers(["m/a.h", own, "m"]), (1, ["m", "m/a.h", "m/sub/b.h"]))

    def test_a_header_the_gate_cannot_place_is_still_reported(self):
        odd = ["unknown/place.h", "buck-out/v2/gen/root/0123abcd/odd/file.h"]
        self.assertEqual(self.reported_headers(odd), (1, sorted(odd)))

    def test_a_package_name_is_matched_whole(self):
        mm = "buck-out/v2/gen/root/0123abcd/mm/__mm__/buck-headers/mm/a.h"  # `mm` is not package `m`
        self.assertEqual(self.reported_headers([mm]), (0, []))

    def test_only_a_header_can_be_outside_the_product(self):
        self.assertEqual(self.reported_headers(["third_party/x/y.c"], reason="macro"), (1, ["third_party/x/y.c"]))

    def test_the_packages_of_every_module_of_the_policy_are_the_products(self):
        self.policy.write_text('[module."//m:mod_mutants"]\nlevel = "L3"\n[module."//n/p:other"]\nlevel = "L3"\n',
                               encoding="utf-8")
        header = [{"name": "g", "file": "n/p/b.h", "reason": "header"}]
        self.put(report([mutant(1)]), "a.json")
        self.put(report([mutant(1)], label="//n/p:other", skipped=header), "b.json")
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual([(f["module"], f["file"]) for f in result["findings"] if f["rule"] == "unmutated-function"],
                         [("//n/p:other", "n/p/b.h")])

    # -- verdicts ----------------------------------------------------------------------------
    def test_equal_object_to_the_baseline_is_equivalent_and_needs_no_run(self):
        self.put(report([mutant(1), mutant(2, digest=BASE, o0=BASE0, runs={})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["verdicts"]["equivalent"], 1)

    def test_equal_object_to_an_earlier_mutant_is_a_duplicate_of_it(self):
        self.put(report([mutant(1, o0=H[20]), mutant(2, digest=H[1], o0=H[20], runs={})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["verdicts"]["duplicate"], 1)

    def test_a_duplicate_of_a_survivor_does_not_hide_it(self):
        result = self.fails_with(report([mutant(1, runs={"t": PASS}, o0=H[20]), mutant(2, digest=H[1], o0=H[20], runs={})]),
                                 "survived-mutant")
        self.assertEqual(result["findings"][0]["id"], "%016x" % 1)

    def test_a_crash_or_a_timeout_kills_but_only_by_crash(self):
        for run in (CRASH, TIMEOUT, KILLED_BY_WATCHDOG, {"rc": 139, "timed_out": False, "results": None}):
            self.fails_with(report([mutant(1, runs={"t": run})]), "crash-only-function")

    def test_a_function_with_one_assert_kill_is_enough_even_if_others_crash(self):
        self.put(report([mutant(1, runs={"t": CRASH}), mutant(2)]))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)

    # -- T078 / B31 (R003 G6): crash-kill-ratio ----------------------------------------------------
    def crash_mix(self, asserts, crashes, function="f"):
        runs = [KILLED] * asserts + [CRASH] * crashes
        return report([mutant(n, function=function, runs={"t": run}) for n, run in enumerate(runs, start=1)])

    def test_a_function_with_a_majority_of_crash_kills_fails_with_its_counts(self):
        result = self.fails_with(self.crash_mix(1, 3), "crash-kill-ratio")
        found = result["findings"][0]
        self.assertEqual((found["module"], found["function"], found["file"], found["asserts"], found["crashes"],
                          found["ratio"], found["threshold"], found["severity"]),
                         (LABEL, "f", "m/a.c", 1, 3, "0.750", "1/2", "error"))

    def test_exactly_half_crash_kills_is_not_over_the_threshold(self):
        self.put(self.crash_mix(2, 2))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)

    def test_fewer_than_four_kills_never_trip_the_ratio(self):
        self.put(self.crash_mix(1, 2))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)

    def test_a_function_with_only_crash_kills_is_only_crash_only(self):
        self.fails_with(self.crash_mix(0, 5), "crash-only-function")

    def test_crash_kill_ratio_is_info_in_an_l2_module(self):
        self.write_policy("L2")
        self.put(self.crash_mix(1, 3))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual([(f["rule"], f["severity"]) for f in result["findings"]], [("crash-kill-ratio", "info")])

    def test_the_ratio_is_per_function_and_survivors_do_not_count_as_kills(self):
        document = self.crash_mix(1, 3)
        document["mutants"].append(mutant(9, runs={"t": PASS}))
        self.fails_with(document, "crash-kill-ratio", "survived-mutant")

    def test_a_duplicate_counts_with_the_verdict_of_its_original_for_the_ratio(self):
        mutants = [mutant(1), mutant(2, runs={"t": CRASH}, o0=H[20]), mutant(3, runs={"t": CRASH}),
                   mutant(4, digest=H[2], o0=H[20], runs={})]
        self.fails_with(report(mutants), "crash-kill-ratio")

    def test_a_function_whose_mutants_are_all_equivalent_fails(self):
        self.fails_with(report([mutant(1, digest=BASE, o0=BASE0, runs={})]), "no-assert-kill-function")

    def test_a_duplicate_counts_with_the_verdict_of_the_mutant_it_duplicates(self):
        # g's only mutant makes the same object as f's, which a test killed by a failed check
        self.put(report([mutant(1, o0=H[20]), mutant(2, function="g", digest=H[1], o0=H[20], runs={})],
                        functions=("f", "g")))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)
        # ... and as one that only a crash killed
        self.fails_with(report([mutant(1, runs={"t": CRASH}, o0=H[20]), mutant(2, function="g", digest=H[1], o0=H[20], runs={}),
                                mutant(3, function="h")], functions=("f", "g", "h")),
                        "crash-only-function", "crash-only-function")

    # -- B15 (R001 R2): equivalent / duplicate must hold at -O0 too ---------------------------------
    def tce(self, result):
        return result["metadata"]["modules"][LABEL]["tce"]

    def test_equal_at_o2_but_different_at_o0_is_live_and_killed_by_a_check(self):
        self.put(report([mutant(1), mutant(2, digest=BASE, o0=H[21])]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        verdicts = result["metadata"]["modules"][LABEL]["verdicts"]
        self.assertEqual((verdicts["equivalent"], verdicts["killed-assert"]), (0, 2))
        self.assertEqual(self.tce(result), {"equivalent_o2": 1, "equivalent_o0": 0})

    def test_equal_at_o2_but_different_at_o0_and_untested_is_a_survivor(self):
        result = self.fails_with(report([mutant(1), mutant(2, digest=BASE, o0=H[21], runs={"t": PASS})]),
                                 "survived-mutant")
        self.assertEqual(result["findings"][0]["id"], "%016x" % 2)

    def test_equal_at_both_levels_stays_equivalent_and_is_counted(self):
        self.put(report([mutant(1), mutant(2, digest=BASE, o0=BASE0, runs={}),
                         mutant(3, digest=BASE, o0=H[21]), mutant(4, digest=BASE, o0=BASE0, runs={})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(result["metadata"]["modules"][LABEL]["verdicts"]["equivalent"], 2)
        self.assertEqual(self.tce(result), {"equivalent_o2": 3, "equivalent_o0": 2})

    def test_a_candidate_without_a_usable_o0_result_is_unrun_never_equivalent(self):
        self.fails_with(report([mutant(1), mutant(2, digest=BASE, runs={})]), "missing-o0")
        failed = mutant(2, digest=BASE, runs={})
        failed["compile"]["o0"] = {"status": "unviable", "hash": ""}
        self.fails_with(report([mutant(1), failed]), "missing-o0")
        dup = mutant(2, digest=H[1], runs={})
        self.fails_with(report([mutant(1, o0=H[20]), dup]), "missing-o0")

    def test_equal_at_o2_to_an_earlier_mutant_but_different_at_o0_is_live(self):
        result = self.fails_with(report([mutant(1, o0=H[20]), mutant(2, digest=H[1], o0=H[21], runs={"t": PASS})]),
                                 "survived-mutant")
        self.assertEqual(result["findings"][0]["id"], "%016x" % 2)

    def test_two_o2_folded_mutants_with_the_same_o0_object_are_duplicates_of_each_other(self):
        self.put(report([mutant(1), mutant(2, digest=BASE, o0=H[21]), mutant(3, digest=BASE, o0=H[21], runs={})]))
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        verdicts = result["metadata"]["modules"][LABEL]["verdicts"]
        self.assertEqual((verdicts["duplicate"], verdicts["killed-assert"], verdicts["equivalent"]), (1, 2, 0))

    def test_the_o0_fields_are_required_and_checked(self):
        no_base = report([mutant(1)])
        del no_base["sources"][0]["baseline_o0"]
        bad_status = report([mutant(1, o0=H[20])])
        bad_status["mutants"][0]["compile"]["o0"] = {"status": "ok", "hash": "xyz"}
        extra = report([mutant(1, o0=H[20])])
        extra["mutants"][0]["compile"]["o0"]["detail"] = "x"
        for what, document in {"no baseline_o0": no_base, "bad o0 hash": bad_status, "extra o0 key": extra}.items():
            self.put(document)
            outcome, result = self.grade()
            self.assertExit(outcome, 2)
            self.assertEqual(self.rules(result), ["internal-error"], what)

    def test_the_function_rule_does_not_apply_to_l2(self):
        self.write_policy("L2")
        self.put(report([mutant(1, runs={"t": CRASH})]))
        outcome, _ = self.grade()
        self.assertExit(outcome, 0)

    # -- red: unusable facts -----------------------------------------------------------------
    def test_a_live_mutant_without_a_run_fails(self):
        self.fails_with(report([mutant(1), mutant(2, runs={})]), "missing-run")

    def test_results_that_disagree_with_the_exit_status_fail(self):
        self.fails_with(report([mutant(1), mutant(2, runs={"t": dict(PASS, rc=1)})]), "bad-results")
        self.fails_with(report([mutant(1), mutant(2, runs={"t": dict(KILLED, rc=0)})]), "bad-results")

    def test_unparsable_or_skipped_results_fail(self):
        garbage = {"rc": 0, "timed_out": False, "results": "not json\n"}
        skipped = {"rc": 0, "timed_out": False, "results": results(("skip", 1, ""))}
        for run in (garbage, skipped):
            self.fails_with(report([mutant(1), mutant(2, runs={"t": run})]), "bad-results")

    def test_a_run_that_lists_other_tests_than_the_baseline_fails(self):
        other = {"rc": 0, "timed_out": False, "results": results(("pass", 1, ""), ("pass", 1, ""))}
        self.fails_with(report([mutant(1), mutant(2, runs={"t": other})]), "bad-results")

    def test_a_red_baseline_fails(self):
        for baseline in (KILLED, CRASH, dict(PASS, rc=1), {"rc": 0, "timed_out": False, "results": None},
                         {"rc": 0, "timed_out": False, "results": results(("pass", 0, ""))},
                         {"rc": 0, "timed_out": True, "results": PASS["results"]}):
            self.fails_with(report([mutant(1)], baseline=baseline), "baseline-red")

    def test_a_harness_that_does_not_reproduce_the_real_object_fails(self):
        self.fails_with(report([mutant(1)], original=H[30]), "harness-mismatch")

    def test_policy_and_reports_must_match(self):
        self.put(report([mutant(1)], label="//m:other"), "other.json")
        self.put(report([mutant(1)]))
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual(self.rules(result), ["module-not-in-policy"])
        self.write_policy("L3", label="//m:gone")
        (self.results / "other.json").unlink()
        outcome, result = self.grade()
        self.assertEqual(self.rules(result), ["module-not-in-policy", "policy-module-without-report"])

    # -- exit 2 ------------------------------------------------------------------------------
    def test_malformed_input_is_exit_2(self):
        bad = report([mutant(1)])
        bad["extra"] = 1
        cases = {"extra key": bad, "wrong schema": dict(report([mutant(1)]), schema=2),
                 "bad hash": report([mutant(1, digest="xyz")]),
                 "unknown test": report([mutant(1, runs={"zz": KILLED})])}
        for what, document in cases.items():
            self.put(document)
            outcome, result = self.grade()
            self.assertExit(outcome, 2)
            self.assertEqual(self.rules(result), ["internal-error"], what)

    def test_empty_results_a_stray_file_a_bad_policy_and_two_reports_for_a_label_are_exit_2(self):
        self.assertExit(self.grade()[0], 2)
        self.put(report([mutant(1)]))
        self.put(report([mutant(1)]), "second.json")
        self.assertExit(self.grade()[0], 2)
        (self.results / "second.json").unlink()
        (self.results / "notes.txt").write_text("x", encoding="utf-8")
        self.assertExit(self.grade()[0], 2)
        (self.results / "notes.txt").unlink()
        for text in ('[module."//m:mod_mutants"]\nlevel = "L1"\n', '[module."//m:mod_mutants"]\nlevel = "L6"\n',
                     '[module."//m:mod_mutants"]\n',
                     '[global]\nx = 1\n', 'not toml ['):
            self.policy.write_text(text, encoding="utf-8")
            self.assertExit(self.grade()[0], 2)


class ApprovalTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.results = self.sub("results")
        (self.tmp / "policy.toml").write_text('[module."%s"]\nlevel = "L3"\n' % LABEL, encoding="utf-8")
        (self.results / "mod.json").write_text(json.dumps(
            report([mutant(1), mutant(2, runs={"t": PASS})])), encoding="utf-8")
        self.repo = Repo(self.tmp / "repo")
        self.repo.write("a.txt", "1\n")
        self.first = self.repo.commit("first")
        self.repo.write("a.txt", "2\n")
        self.head = self.repo.commit("second")
        self.signer = Signer(self.tmp / "keys")
        self.allowed = self.signer.write_allowed_signers(self.tmp / "allowed_signers")
        self.dir = self.sub("approvals")

    def approve(self, scope, kind="equivalent-mutant", repo_sha=None):
        outcome = run_rigor(["approve", "--kind", kind, "--scope", scope, "--reason", "same behaviour",
                             "--repo-sha", repo_sha or self.first, "--key", self.signer.key, "--out", self.dir])
        self.assertExit(outcome, 0)

    def grade(self):
        out = self.tmp / "out.json"
        outcome = run_rigor(["mutants", "--results", self.results, "--policy", self.tmp / "policy.toml",
                             "--out", out, "--approvals", self.dir, "--allowed-signers", self.allowed,
                             "--repo", self.repo.root, "--head", self.head])
        return outcome, read_json(out)

    def test_a_signed_approval_of_the_mutant_id_covers_the_survivor(self):
        self.approve("%016x" % 2)
        outcome, result = self.grade()
        self.assertExit(outcome, 0)
        self.assertEqual(len(result["metadata"]["approvals_used"]), 1)

    def test_an_approval_of_another_id_or_kind_or_a_non_ancestor_does_not(self):
        for kwargs in ({"scope": "%016x" % 3}, {"scope": "%016x" % 2, "kind": "suppression"},
                       {"scope": "%016x" % 2, "repo_sha": "a" * 40}):
            for name in list(self.dir.iterdir()):
                name.unlink()
            self.approve(**kwargs)
            outcome, result = self.grade()
            self.assertExit(outcome, 1)
            self.assertIn("survived-mutant", [f["rule"] for f in result["findings"]])

    def test_an_approval_never_covers_a_missing_run_or_a_crash_only_function(self):
        (self.results / "mod.json").write_text(json.dumps(
            report([mutant(1, runs={"t": CRASH}), mutant(2, runs={})])), encoding="utf-8")
        self.approve("%016x" % 2)
        outcome, result = self.grade()
        self.assertExit(outcome, 1)
        self.assertEqual(sorted(f["rule"] for f in result["findings"]), ["missing-run"])


if __name__ == "__main__":
    import unittest
    unittest.main()
