"""The `tests-msan` and `tests-tsan` gates, the `threads` declaration check and the mode comparison of the msan and
tsan twins (T138), without Buck2: the queries and the build are replaced, the rest is the real code."""

import json
from types import SimpleNamespace
from unittest import mock

from rigor_lib import facts_data, facts_modes, facts_threads, grade_build, grade_context, grade_pipeline, grade_sanmodes
from tests.helpers import TempDirTestCase

CORE, UTIL, X, XT = "//core:core_test", "//util:util_test", "//x:x_test", "//x:xx_test"
LABELS = {"root//core:core_test_results": (CORE, False), "root//util:util_test_results": (UTIL, True),
          "root//x:x_test_results": (X, False)}


def record(test_id, status="pass"):
    return json.dumps({"id": test_id, "status": status, "asserts": 1, "reason": ""})


def results_text(*records):
    passed = sum(1 for r in records if json.loads(r)["status"] == "pass")
    return "\n".join(list(records) + [json.dumps({"summary": {"total": len(records), "passed": passed}})]) + "\n"


class Fixture(TempDirTestCase):
    """A grading whose release results hold core/a (core), util/b (util, threaded) and x/c (x, links X11)."""

    def setUp(self):
        super().setUp()
        self.work = self.sub("work")
        self.release = self.sub("work/test-results/release")
        self.san = self.sub("work/test-results/san")
        for index, (label, ids) in enumerate(zip(sorted(LABELS), (["core/a"], ["util/b"], ["x/c"]))):
            path = self.release / grade_build.result_file_name(index, label)
            path.write_text(results_text(*[record(i) for i in ids]), encoding="utf-8")
        self.product = self.sub("p")
        self.expected(["core/a", "util/b", "x/c"])
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\n', encoding="utf-8")
        args = SimpleNamespace(task=str(task), product=str(self.product / "product.toml"), approvals=None,
                               allowed_signers="signers", uncached=False)
        self.g = SimpleNamespace(args=args, built={"release": str(self.release), "san": str(self.san)},
                                 src="", head="h", work=str(self.work), tree=str(self.tmp / "tree"),
                                 test_results=str(self.work / "test-results"))
        self.built = []

    def expected(self, ids):
        (self.product / "expected-tests.json").write_text(json.dumps({"ids": ids}), encoding="utf-8")

    def fake_build(self, outcome):
        """`outcome(mode, labels)` -> (findings, directory or None); every call is remembered."""
        def build(g, mode, labels):
            self.built.append((mode, list(labels)))
            found, directory = outcome(mode, labels)
            return found, {"executed_actions": 1, "cached_actions": 2, "exit_code": 0, "targets": labels}, directory
        return build

    def writes(self, results):
        """A build outcome that writes `{file stem: [records]}` into the mode's directory."""
        def outcome(mode, labels):
            directory = self.work / "test-results" / mode
            directory.mkdir(parents=True, exist_ok=True)
            for stem, records in results.items():
                (directory / (stem + ".jsonl")).write_text(results_text(*records), encoding="utf-8")
            return [], str(directory)
        return outcome

    def run_gate(self, mode, outcome, blockers=None):
        with mock.patch.object(grade_sanmodes, "results_attributes", lambda tree: dict(LABELS)), \
                mock.patch.object(grade_sanmodes, "msan_blockers", lambda tree: {"//x:x_test": "X11"} if blockers is None else blockers), \
                mock.patch.object(grade_sanmodes, "_build", self.fake_build(outcome)), \
                mock.patch.object(grade_context, "kill_daemon"):
            return grade_sanmodes.sanitizer_tests_gate(mode)(self.g)


def rules(result):
    return sorted((f["rule"], f["severity"]) for f in result.findings)


class Msan(Fixture):
    def test_the_test_with_x11_is_not_applicable_and_the_rest_is_judged(self):
        result = self.run_gate("msan", self.writes({"a": [record("core/a")], "b": [record("util/b")]}))
        self.assertEqual(result.status, "PASS", result.findings)
        self.assertEqual(rules(result), [("msan-not-applicable", "info")])
        [item] = result.findings
        self.assertEqual((item["target"], item["library"]), ("//x:x_test", "X11"))
        self.assertEqual(self.built, [("msan", ["root//core:core_test_results", "root//util:util_test_results"])])
        self.assertEqual(result.gate, "tests-msan")

    def test_anything_else_missing_is_missing_test(self):
        result = self.run_gate("msan", self.writes({"a": [record("core/a")]}))
        self.assertEqual(result.status, "FAIL")
        self.assertIn({"rule": "missing-test", "severity": "error", "id": "util/b"}, result.findings)

    def test_a_failing_test_fails_the_gate(self):
        result = self.run_gate("msan", self.writes({"a": [record("core/a", "fail")], "b": [record("util/b")]}))
        self.assertEqual([f["rule"] for f in result.findings if f["severity"] == "error"], ["test-not-pass"])

    def test_nothing_applicable_builds_nothing(self):
        self.expected(["x/c"])
        result = self.run_gate("msan", self.writes({}), blockers={"//x:x_test": "X11", CORE: "X11", UTIL: "X11"})
        self.assertEqual(self.built, [])
        self.assertEqual(result.status, "PASS")
        self.assertIn("no-msan-targets", [f["rule"] for f in result.findings])

    def test_a_build_failure_is_a_finding_and_no_tests_are_judged(self):
        failing = lambda mode, labels: ([{"rule": "build-failed", "severity": "error", "mode": mode, "target": "*"}], None)
        result = self.run_gate("msan", failing)
        self.assertEqual(result.status, "FAIL")
        self.assertNotIn("missing-test", [f["rule"] for f in result.findings])

    def test_the_startup_check_is_one_error_that_names_the_prerequisite(self):
        item = grade_sanmodes.finding("sanitizer-startup", mode="msan", prerequisite=grade_sanmodes.PREREQUISITE)
        result = self.run_gate("msan", lambda mode, labels: ([item], None))
        self.assertEqual([f["rule"] for f in result.findings if f["severity"] == "error"], ["sanitizer-startup"])
        self.assertIn("personality(ADDR_NO_RANDOMIZE)", item["prerequisite"])

    def test_role_test_author_judges_presence_only(self):
        (self.tmp / "task.toml").write_text('id = "t"\nallowed = ["**"]\nrole = "test-author"\n', encoding="utf-8")
        (self.product / "expected-tests.previous.json").write_text('{"ids": []}', encoding="utf-8")
        result = self.run_gate("msan", self.writes({"a": [record("core/a", "fail")], "b": [record("util/b")]}))
        self.assertEqual(result.status, "PASS", result.findings)
        self.assertIs(result.metadata["statuses_judged"], False)

    def test_not_run_without_clean_results(self):
        for gone in ("release", "san"):
            del self.g.built[gone]
            self.assertIsNone(self.run_gate("msan", self.writes({})))
            self.g.built[gone] = str(self.release)


class Tsan(Fixture):
    def test_exactly_the_threaded_tests_are_expected(self):
        result = self.run_gate("tsan", self.writes({"b": [record("util/b")]}))
        self.assertEqual(result.status, "PASS", result.findings)
        self.assertEqual(self.built, [("tsan", ["root//util:util_test_results"])])
        self.assertEqual(result.metadata["expected_count"], 1)

    def test_a_race_fails_the_test(self):
        result = self.run_gate("tsan", self.writes({"b": [record("util/b", "fail")]}))
        self.assertEqual([f["rule"] for f in result.findings if f["severity"] == "error"], ["test-not-pass"])

    def test_the_threaded_test_missing_from_the_results_is_missing_test(self):
        result = self.run_gate("tsan", self.writes({"other": [record("util/other")]}))
        self.assertIn({"rule": "missing-test", "severity": "error", "id": "util/b"}, result.findings)

    def test_no_threaded_tests_passes_with_an_info_and_builds_nothing(self):
        labels = {label: (module, False) for label, (module, _) in LABELS.items()}
        with mock.patch.dict(LABELS, labels):
            result = self.run_gate("tsan", self.writes({}))
        self.assertEqual((result.status, rules(result)), ("PASS", [("no-threaded-tests", "info")]))
        self.assertEqual(self.built, [])

    def test_the_startup_check_is_an_error_not_a_list_of_missing_tests(self):
        item = grade_sanmodes.finding("sanitizer-startup", mode="tsan", prerequisite=grade_sanmodes.PREREQUISITE)
        result = self.run_gate("tsan", lambda mode, labels: ([item], None))
        self.assertEqual(rules(result), [("sanitizer-startup", "error")])


class Registration(TempDirTestCase):
    def test_both_gates_follow_tests_san_and_need_the_toolchain(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[ids.index("tests-san") + 1:ids.index("tests-san") + 3], ["tests-msan", "tests-tsan"])
        steps = dict(grade_pipeline.GATES)
        self.assertTrue(steps["tests-msan"].needs_toolchain and steps["tests-tsan"].needs_toolchain)

    def test_without_the_toolchain_they_are_not_run(self):
        g = SimpleNamespace(status={})
        for gate_id in ("tests-msan", "tests-tsan"):
            self.assertIsNone(dict(grade_pipeline.GATES)[gate_id](g))

    def test_unknown_mode(self):
        with self.assertRaises(Exception):
            grade_sanmodes.sanitizer_tests_gate("san")


class Startup(TempDirTestCase):
    def test_the_runtime_words_are_found(self):
        for text in ("CHECK failed: sanitizer_common.cpp:1 personality(old | ADDR_NO_RANDOMIZE) != -1 (-1, -1)",
                     "FATAL: MemorySanitizer: memory layout is incompatible, maybe you are using ASLR"):
            self.assertIsNotNone(grade_sanmodes.STARTUP.search(text))
        self.assertIsNone(grade_sanmodes.STARTUP.search("error: use of undeclared identifier"))

    def test_the_build_reports_it_and_collects_nothing(self):
        work = self.sub("work")
        g = SimpleNamespace(work=str(work), tree="/t", args=SimpleNamespace(uncached=False),
                            test_results=str(work / "test-results"))
        err = "ctest: test binary could not run (status 1)\nCHECK failed: personality(0) != -1 (-1, -1)\n"
        with mock.patch.object(grade_build, "run_buck", return_value=(1, "", err)), \
                mock.patch.object(grade_build, "action_counts", return_value=(1, 0)), \
                mock.patch.object(grade_build, "collect_mode") as collect:
            found, metadata, directory = grade_sanmodes._build(g, "tsan", ["root//a:a_results"])
        collect.assert_not_called()
        self.assertEqual([(f["rule"], f["severity"], f["mode"]) for f in found], [("sanitizer-startup", "error", "tsan")])
        self.assertIsNone(directory)
        self.assertEqual(metadata["exit_code"], 1)


class Closure(TempDirTestCase):
    def query(self, entries):
        return mock.patch.object(grade_sanmodes, "_query", lambda tree, expression, attributes: entries)

    def test_a_library_beyond_pthread_blocks_everything_that_depends_on_it(self):
        entries = {
            "root//x:xlib_facts": {"facts_name": "xlib", "system_libs": ["X11"], "facts_deps": []},
            "root//x:mid_facts": {"facts_name": "mid", "system_libs": ["pthread"], "facts_deps": ["root//x:xlib"]},
            "root//x:t_facts": {"facts_name": "t", "system_libs": [], "facts_deps": ["root//x:mid", "gate//ctest:ctest"]},
            "root//y:p_facts": {"facts_name": "p", "system_libs": ["pthread"], "facts_deps": []},
            "root//y:u_facts": {"facts_name": "u", "system_libs": [], "facts_deps": ["root//y:p"]},
        }
        with self.query(entries):
            blockers = grade_sanmodes.msan_blockers("/t")
        self.assertEqual(blockers, {"//x:xlib": "X11", "//x:mid": "X11", "//x:t": "X11", "//y:p": None, "//y:u": None})

    def test_a_dependency_cycle_ends(self):
        entries = {"root//a:a_facts": {"facts_name": "a", "system_libs": [], "facts_deps": ["root//a:b"]},
                   "root//a:b_facts": {"facts_name": "b", "system_libs": ["X11"], "facts_deps": ["root//a:a"]}}
        with self.query(entries):
            self.assertEqual(grade_sanmodes.msan_blockers("/t"), {"//a:a": "X11", "//a:b": "X11"})

    def test_declared_threads(self):
        entries = {"root//u:t_results": {"test": "root//u:t", "threads": True},
                   "root//u:v_results": {"test": "root//u:v"}}
        with self.query(entries):
            self.assertEqual(grade_sanmodes.declared_threads("/t"), {"//u:t": True, "//u:v": False})


def test_facts(label, kind, undefined=()):
    unit = facts_data.Unit("t.c.o", frozenset(), frozenset(), frozenset(undefined), (), (), (), ())
    return facts_data.Facts(label, kind, (), (unit,))


class Threads(TempDirTestCase):
    def judge(self, undefined, declared, kind="c_test"):
        return facts_threads.findings({"//u:t": test_facts("//u:t", kind, undefined)}, {"//u:t": declared})

    def test_an_undeclared_thread_creation_is_an_error(self):
        for function in ("pthread_create", "thrd_create", "pthread_create@GLIBC_2.2.5"):
            [item] = self.judge([function, "memcpy"], False)
            self.assertEqual((item["rule"], item["severity"], item["target"]), ("threads-undeclared", "error", "//u:t"))
        [item] = self.judge(["pthread_create", "thrd_create"], False)
        self.assertEqual(item["functions"], ["pthread_create", "thrd_create"])

    def test_a_declaration_without_a_thread_creation_is_vacuous(self):
        [item] = self.judge(["memcpy", "pthread_join"], True)
        self.assertEqual((item["rule"], item["severity"]), ("threads-vacuous", "error"))

    def test_the_matching_cases_pass(self):
        self.assertEqual(self.judge(["pthread_create"], True), [])
        self.assertEqual(self.judge(["memcpy"], False), [])

    def test_only_tests_are_judged(self):
        self.assertEqual(self.judge(["pthread_create"], False, kind="c_library"), [])
        self.assertEqual(facts_threads.findings({"//u:t": test_facts("//u:t", "c_library", ["pthread_create"])}, {}), [])

    def test_a_test_without_a_declaration_is_an_internal_error(self):
        with self.assertRaises(Exception):
            facts_threads.findings({"//u:t": test_facts("//u:t", "c_test")}, {})


def side(units):
    """A `load_mode_dir` result of one target with the given {unit: items}."""
    return {"//a:a_facts": units}


class Compare(TempDirTestCase):
    def test_the_mode_is_named_in_the_finding(self):
        item = ("call", "core_msan_only", "core/core.c", 12)
        for mode in ("san", "msan", "tsan"):
            found = facts_modes.compare(side({"core.c.o": set()}), side({"core.c.o": {item}}), mode)
            self.assertEqual([(f["only_in"], f["item"]) for f in found], [(mode, "core_msan_only")])
        found = facts_modes.compare(side({"core.c.o": {item}}), side({"core.c.o": set()}), "tsan")
        self.assertEqual([f["only_in"] for f in found], ["release"])

    def test_the_default_mode_is_san(self):
        item = ("call", "f", "a.c", 1)
        [found] = facts_modes.compare(side({"a.c.o": set()}), side({"a.c.o": {item}}))
        self.assertEqual(found["only_in"], "san")

    def test_the_twin_name_helper(self):
        from rigor_lib import grade_structure
        self.assertEqual(grade_structure.twin("root//p:a_facts", "tsan"), "root//p:a_facts_tsan")
