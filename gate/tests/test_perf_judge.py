"""Judging cost counts against a complexity class (T090): thresholds, record handling, the policy table, the gate step."""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from rigor_lib import facts_policy, grade_pipeline, perf_bundle, perf_gate, perf_judge, perf_package, perf_policy, verdict
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase


def rec(n, instructions, libc=0, **extra):
    base = {"name": "p", "seed": 1, "n": n, "status": "ok", "counter": "perf_event_open", "errno": 0,
            "input_len": n, "instructions": instructions, "libc_bytes": libc, "result": 0, "wall_ns_median": 1}
    base.update(extra)
    return base


class Limits(unittest.TestCase):
    def test_o1_allows_ten_percent_plus_the_counter_slack(self):
        self.assertEqual(perf_judge.limit("O(1)", 1000, 100, 400), 1116)
        self.assertEqual(perf_judge.limit("O(1)", 0, 100, 400), 16)

    def test_olog_is_the_larger_of_the_ratio_rule_and_the_additive_rule(self):
        self.assertEqual(perf_judge.limit("O(log n)", 1000, 100, 400), 1516)      # 1.5 * 1000 + 16
        self.assertEqual(perf_judge.limit("O(log n)", 40, 100, 400), 40 + 64 + 16)   # additive: 64 beats 1.5x
        self.assertEqual(perf_judge.limit("O(log n)", 100000, 100, 400), 150000 + 16)  # 1.5x is larger

    def test_olog_ratio_follows_k(self):
        self.assertEqual(perf_judge.limit("O(log n)", 1000, 100, 1600), 1000 * 2 + 16)       # k=16: 1 + 4/4
        self.assertEqual(perf_judge.limit("O(log n)", 1000, 100, 200), 1250 + 16)            # k=2: 1 + 1/4

    def test_on_allows_one_tenth_over_k(self):
        self.assertEqual(perf_judge.limit("O(n)", 1000, 100, 400), 4400 + 16)
        self.assertEqual(perf_judge.limit("O(n)", 1000, 100, 200), 2200 + 16)

    def test_onlogn_scales_with_the_log_ratio(self):
        got = perf_judge.limit("O(n log n)", 1000, 1000, 4000)
        self.assertEqual(got, int(4.4 * 1000 * 11.965784284662087 / 9.965784284662087) + 16)   # 4.4 * log2(4n) / log2(n)
        self.assertEqual(perf_judge.limit("O(n log n)", 1000, 1, 4), int(1.10 * 4 * 2 / 1 * 1000) + 16)   # n1 < 2 uses log2(2)

    def test_classes_nest(self):
        for c1 in (50, 5000):
            seq = [perf_judge.limit(c, c1, 1000, 4000) for c in perf_judge.CLASSES]
            self.assertEqual(seq, sorted(seq))


class Exceeded(unittest.TestCase):
    def test_a_linear_pair_is_inside_on_and_outside_o1_and_olog(self):
        pair = [rec(1000, 10000, 500), rec(4000, 39990, 2000)]
        self.assertEqual(perf_judge.exceeded("O(n)", pair), [])
        self.assertEqual(perf_judge.exceeded("O(n log n)", pair), [])
        self.assertEqual([e["counter"] for e in perf_judge.exceeded("O(1)", pair)], ["instructions", "libc_bytes"])
        self.assertEqual([e["counter"] for e in perf_judge.exceeded("O(log n)", pair)], ["instructions", "libc_bytes"])

    def test_either_counter_exceeding_fails(self):
        pair = [rec(1000, 10000, 500), rec(4000, 10000, 8000)]
        self.assertEqual([e["counter"] for e in perf_judge.exceeded("O(n)", pair)], ["libc_bytes"])
        pair = [rec(1000, 10000, 500), rec(4000, 100000, 500)]
        self.assertEqual([e["counter"] for e in perf_judge.exceeded("O(n)", pair)], ["instructions"])

    def test_the_finding_carries_both_counts_and_the_ratio(self):
        (item,) = perf_judge.exceeded("O(1)", [rec(10, 1000), rec(40, 4000)])
        self.assertEqual(item, {"counter": "instructions", "n1": 10, "n2": 40, "count1": 1000, "count2": 4000,
                                "ratio": "4.000", "limit": 1116})

    def test_first_and_last_of_more_than_two_sizes_are_compared(self):
        records = [rec(100, 1000), rec(200, 1000000), rec(400, 1000)]
        self.assertEqual(perf_judge.exceeded("O(1)", records), [])

    def test_zero_at_the_small_size_and_growth_is_infinite_ratio(self):
        (item,) = perf_judge.exceeded("O(1)", [rec(10, 100, 0), rec(40, 100, 500)])
        self.assertEqual((item["counter"], item["ratio"]), ("libc_bytes", "inf"))
        self.assertEqual(perf_judge.exceeded("O(1)", [rec(10, 100, 0), rec(40, 100, 0)]), [])

    def test_the_boundary_is_inclusive(self):
        edge = perf_judge.limit("O(n)", 1000, 10, 40)
        self.assertEqual(perf_judge.exceeded("O(n)", [rec(10, 1000), rec(40, edge)]), [])
        self.assertEqual(len(perf_judge.exceeded("O(n)", [rec(10, 1000), rec(40, edge + 1)])), 1)

    def test_unusable_records_are_refused(self):
        with self.assertRaises(ValueError):
            perf_judge.exceeded("O(1)", [rec(10, 100)])


class Usable(unittest.TestCase):
    def why(self, records):
        return perf_judge.usable(records)[2]

    def test_ok_pair(self):
        self.assertIsNone(self.why([rec(10, 1), rec(40, 1)]))

    def test_too_few_bad_status_and_odd_sizes_are_record_problems(self):
        self.assertEqual(self.why([rec(10, 1)]), "record")
        self.assertEqual(self.why([rec(10, 1), {"n": 40, "status": "crash", "signal": 11}]), "record")
        self.assertEqual(self.why([rec(10, 1), rec(10, 1)]), "record")
        self.assertEqual(self.why([rec(10, 1), rec(True, 1)]), "record")

    def test_an_unavailable_counter_is_its_own_reason(self):
        gone = rec(10, None, counter="unavailable", errno=13)
        self.assertEqual(self.why([gone, rec(40, 1)]), "unavailable")

    def test_missing_or_negative_counts_are_record_problems(self):
        self.assertEqual(self.why([rec(10, 1), rec(40, -1)]), "record")
        self.assertEqual(self.why([rec(10, 1), rec(40, "5")]), "record")

    def test_status_of_names_the_first_bad_status(self):
        self.assertEqual(perf_judge.status_of([rec(10, 1), {"status": "timeout"}]), "timeout")
        self.assertEqual(perf_judge.status_of([{"status": "weird"}]), "malformed")
        self.assertEqual(perf_judge.status_of([rec(10, 1), rec(40, 1)]), "malformed")


class Parse(unittest.TestCase):
    def test_lines_are_parsed_strictly(self):
        data = (json.dumps(rec(10, 1)) + "\n\n" + json.dumps(rec(40, 2)) + "\n").encode()
        self.assertEqual([r["n"] for r in perf_judge.parse_records("p", data)], [10, 40])
        for bad in (b"not json\n", b"[1]\n", b'{"a":1,"a":2}\n', b'{"a":NaN}\n'):
            with self.assertRaises(InternalError):
                perf_judge.parse_records("p", bad)


class Judge(unittest.TestCase):
    def judge(self, cost_class, records):
        return perf_gate.judge_target("//x:y_perf", "//x:y", cost_class, records)

    def test_inside_the_class_has_no_findings(self):
        self.assertEqual(self.judge("O(n)", [rec(10, 100), rec(40, 400)]), [])

    def test_exceeded_names_target_class_counts_and_ratio(self):
        (item,) = self.judge("O(n)", [rec(10, 100), rec(40, 1600)])
        self.assertEqual((item["rule"], item["severity"], item["target"], item["class"], item["module"]),
                         ("perf-class-exceeded", "error", "//x:y_perf", "O(n)", "//x:y"))
        self.assertEqual((item["count1"], item["count2"], item["ratio"], item["counter"]), (100, 1600, "16.000", "instructions"))

    def test_unavailable_counter_is_an_error(self):
        (item,) = self.judge("O(n)", [rec(10, None, counter="unavailable", errno=1), rec(40, None, counter="unavailable", errno=1)])
        self.assertEqual((item["rule"], item["severity"], item["errno"]), ("perf-counter-unavailable", "error", 1))

    def test_a_bad_status_is_a_bad_record(self):
        (item,) = self.judge("O(n)", [rec(10, 1), {"n": 40, "status": "run-error", "input_len": 3}])
        self.assertEqual((item["rule"], item["status"]), ("perf-record-bad", "run-error"))


class PolicyTable(TempDirTestCase):
    def policy(self, extra, files=("perf/a.c",)):
        for name in files:
            path = self.tmp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("/* %s */\n" % name, encoding="utf-8")
        path = self.tmp / "policy.toml"
        path.write_text('[global]\ndeny = []\n[module."//x:y"]\nlevel = "L3"\n' + extra, encoding="utf-8")
        return str(path)

    LOOKUP = '[module."//x:y".perf.lookup]\nclass = "O(log n)"\nsrcs = ["perf/a.c"]\nsizes = [100, 400]\nseed = 3\n'

    def test_a_module_declares_perf_targets_with_classes_sizes_seed_and_sources(self):
        path = self.policy(self.LOOKUP + '[module."//x:y".perf.scan]\nclass = "O(1)"\nsrcs = ["perf/a.c", "perf/b.c"]\n'
                           'sizes = [10, 20, 40]\nseed = 0\n', files=("perf/a.c", "perf/b.c"))
        lookup, scan = perf_policy.load(path)
        self.assertEqual((lookup.name, lookup.module, lookup.cost_class, lookup.sizes, lookup.seed, lookup.srcs),
                         ("lookup", "//x:y", "O(log n)", (100, 400), 3, ("perf/a.c",)))
        self.assertEqual((lookup.label, lookup.binary), ("//gate-perf:lookup_perf", "//gate-perf:lookup"))
        self.assertEqual(lookup.files, (("perf/a.c", b"/* perf/a.c */\n"),))
        self.assertEqual((scan.sizes, [p for p, _ in scan.files]), ((10, 20, 40), ["perf/a.c", "perf/b.c"]))
        self.assertEqual(perf_policy.by_module([lookup, scan]),
                         {"//x:y": {"//gate-perf:lookup_perf": "O(log n)", "//gate-perf:scan_perf": "O(1)"}})
        self.assertEqual(facts_policy.load_policy(path).modules["//x:y"].level, "L3")   # the symbol policy accepts it

    def test_no_perf_tables_is_empty(self):
        self.assertEqual(perf_policy.load(self.policy("")), [])

    def test_defects_are_exit_2(self):
        body = 'class = "O(1)"\nsrcs = ["perf/a.c"]\nsizes = [1, 2]\nseed = 1\n'
        for extra in ('[module."//x:y".perf.Bad]\n' + body,
                      '[module."//x:y".perf.a]\n' + body.replace('"O(1)"', '"O(2^n)"'),
                      '[module."//x:y".perf.a]\n' + body + 'extra = 1\n',
                      '[module."//x:y".perf.a]\n' + body.replace('seed = 1\n', ''),
                      '[module."//x:y".perf.a]\n' + body.replace('"perf/a.c"', '"../a.c"'),
                      '[module."//x:y".perf.a]\n' + body.replace('"perf/a.c"', '"perf/a.h"'),
                      '[module."//x:y".perf.a]\n' + body.replace('"perf/a.c"', '"/perf/a.c"'),
                      '[module."//x:y".perf.a]\n' + body.replace('"perf/a.c"', ''),
                      '[module."//x:y".perf.a]\n' + body.replace('[1, 2]', '[2, 2]'),
                      '[module."//x:y".perf.a]\n' + body.replace('[1, 2]', '[1]'),
                      '[module."//x:y".perf.a]\n' + body.replace('[1, 2]', '[0, 2]'),
                      '[module."//x:y".perf.a]\n' + body.replace('seed = 1', 'seed = -1'),
                      '[module."//x:y".perf.a]\n' + body.replace('seed = 1', 'seed = true'),
                      '[module."//x:y"]\nperf = 3\n',
                      '[module."//x:y".perf.gone]\n' + body.replace('perf/a.c', 'perf/gone.c'),
                      '[module."//x:y".perf.a]\n' + body + '[module."//x:z".perf.a]\n' + body):
            path = self.policy(extra)
            with self.assertRaises(InternalError, msg=extra):
                perf_policy.load(path)

    def test_a_symlinked_source_is_refused(self):
        path = self.policy(self.LOOKUP)
        (self.tmp / "perf" / "a.c").unlink()
        (self.tmp / "real.c").write_text("x", encoding="utf-8")
        (self.tmp / "perf" / "a.c").symlink_to(self.tmp / "real.c")
        with self.assertRaises(InternalError):
            perf_policy.load(path)

    def test_bundle_targets_are_judged_like_policy_targets(self):
        bundle = perf_bundle.Bundle("p", (perf_bundle.Target("many-keys", "//json:json", ("gen/k.c",), (1000, 4000), 5, "nlogn"),),
                                    (perf_bundle.PerfFile("gen/k.c", b"int x;"),), "0" * 64)
        (target,) = perf_policy.load(self.policy(""), bundle)
        self.assertEqual((target.name, target.module, target.cost_class, target.sizes, target.seed, target.files),
                         ("bundle_many_keys", "//json:json", "O(n log n)", (1000, 4000), 5, (("gen/k.c", b"int x;"),)))
        with self.assertRaises(InternalError):
            perf_policy.load(self.policy('[module."//x:y".perf.bundle_many_keys]\nclass = "O(1)"\nsrcs = ["perf/a.c"]\n'
                                         'sizes = [1, 2]\nseed = 1\n'), bundle)


class Package(TempDirTestCase):
    def targets(self):
        return [perf_policy.Target("a", "//x:y", "O(1)", (10, 40), 7, ("perf/a.c", "perf/b.c"),
                                   (("perf/a.c", b"A"), ("perf/b.c", b"B"))),
                perf_policy.Target("b", "//x:z", "O(n)", (5, 20, 80), 0, ("perf/a.c",), (("perf/a.c", b"A"),))]

    def test_the_build_file_is_one_c_perf_per_target_and_the_sources_are_written(self):
        tree = self.sub("tree")
        perf_package.write(str(tree), self.targets())
        self.assertEqual((tree / "gate-perf" / "BUCK").read_text(encoding="utf-8"), (
            'load("@gate//rules:c.bzl", "c_perf")\n\n'
            'c_perf(\n    name = "a",\n    module = "//x:y",\n    srcs = ["perf/a.c", "perf/b.c"],\n    sizes = [10, 40],\n    seed = 7,\n)\n\n'
            'c_perf(\n    name = "b",\n    module = "//x:z",\n    srcs = ["perf/a.c"],\n    sizes = [5, 20, 80],\n    seed = 0,\n)\n'))
        self.assertEqual((tree / "gate-perf" / "perf" / "b.c").read_bytes(), b"B")
        perf_package.remove(str(tree))
        self.assertFalse((tree / "gate-perf").exists())

    def test_it_refuses_an_existing_package_and_two_files_under_one_name(self):
        tree = self.sub("tree")
        (tree / "gate-perf").mkdir()
        with self.assertRaises(InternalError):
            perf_package.write(str(tree), self.targets())
        other = self.sub("tree2")
        clash = self.targets()
        clash[1] = perf_policy.Target("b", "//x:z", "O(n)", (5, 20), 0, ("perf/a.c",), (("perf/a.c", b"DIFFERENT"),))
        with self.assertRaises(InternalError):
            perf_package.write(str(other), clash)


class Step(TempDirTestCase):
    def grading(self, policy_text, status=None, role="implementer"):
        product = self.sub("product") / "product.toml"
        (self.sub("product") / "policy.toml").write_text(policy_text, encoding="utf-8")
        (self.sub("product") / "perf").mkdir(exist_ok=True)
        (self.sub("product") / "perf" / "a.c").write_text("/* driver */\n", encoding="utf-8")
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\nrole = "%s"\n' % role, encoding="utf-8")
        args = SimpleNamespace(product=str(product), uncached=False, task=str(task))
        done = {k: "PASS" for k in perf_gate.REQUIRED}
        done.update(status or {})
        return SimpleNamespace(args=args, work=str(self.sub("work")), tree=str(self.sub("tree")), status=done, perf=None)

    POLICY = ('[global]\ndeny = []\n[module."//x:y"]\nlevel = "L3"\n[module."//x:y".perf.p]\nclass = "O(1)"\n'
              'srcs = ["perf/a.c"]\nsizes = [1, 2]\nseed = 1\n')

    def test_it_is_registered_after_the_tests_and_before_mutants_and_is_in_the_order_file(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[ids.index("tests-stub") + 1:ids.index("mutants")], ["perf"])
        self.assertEqual(verdict.read_order(str(GATE_DIR / "order.txt")), ids)

    def test_a_product_without_perf_entries_passes_with_info(self):
        result = perf_gate.perf_gate(self.grading('[global]\ndeny = []\n[module."//x:y"]\nlevel = "L3"\n'))
        self.assertEqual((result.status, [(f["rule"], f["severity"]) for f in result.findings]),
                         ("PASS", [("no-perf-targets", "info")]))

    def test_test_author_is_not_applicable(self):
        result = perf_gate.perf_gate(self.grading(self.POLICY, role="test-author"))
        self.assertEqual((result.status, result.findings[0]["rule"]), ("PASS", "not-applicable"))

    def test_it_does_not_run_unless_the_tree_built_and_every_test_passed(self):
        self.assertIsNone(perf_gate.perf_gate(self.grading(self.POLICY, {"assemble": "FAIL"})))
        for gate in perf_gate.REQUIRED[1:]:
            with mock.patch.object(perf_gate, "_run") as run:
                self.assertIsNone(perf_gate.perf_gate(self.grading(self.POLICY, {gate: "FAIL"})), gate)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
