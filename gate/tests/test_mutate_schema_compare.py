"""Report and comparison of the schema engine (mutate/schema/schema_compare.py, T124): the class of a mutant, the
merge of the build's files into one report, and the v1-against-schema comparison with its explained disagreements."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("mutate_schema_compare", HERE.parent.parent / "mutate" / "schema" / "schema_compare.py")
cmp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cmp)

PASS = '{"asserts":1,"id":"t/a","reason":"","status":"pass"}\n{"summary":{"passed":1,"total":1}}\n'
FAIL = '{"asserts":1,"id":"t/a","reason":"0 of 0 checks failed; first: (not stored)","status":"fail"}\n{"summary":{"passed":0,"total":1}}\n'
CRASHED = '{"asserts":1,"id":"t/a","reason":"killed by signal #","status":"fail"}\n{"summary":{"passed":0,"total":1}}\n'


def run(rc=0, results=PASS, timed_out=False):
    return {"rc": rc, "timed_out": timed_out, "results": results}


class ClassTest(unittest.TestCase):
    def test_outcomes(self):
        self.assertEqual(cmp.outcome(run()), "pass")
        self.assertEqual(cmp.outcome(run(1, FAIL)), "assert")
        self.assertEqual(cmp.outcome(run(1, CRASHED)), "crash")
        self.assertEqual(cmp.outcome(run(-1, None)), "crash")
        self.assertEqual(cmp.outcome(run(0, PASS, True)), "crash")
        self.assertEqual(cmp.outcome(run(0, FAIL)), "bad")      # the status disagrees with the results
        self.assertEqual(cmp.outcome(run(1, PASS)), "bad")
        self.assertEqual(cmp.outcome(run(0, "!\n")), "bad")      # a line that does not parse
        self.assertEqual(cmp.outcome(run(0, '{"id":"t/a","status":"skip","asserts":0,"reason":""}\n')), "bad")

    def test_classes(self):
        self.assertEqual(cmp.classify({"a": run(), "b": run(1, FAIL)}), "killed-assert")
        self.assertEqual(cmp.classify({"a": run(1, CRASHED), "b": run()}), "killed-crash")
        self.assertEqual(cmp.classify({"a": run(1, CRASHED), "b": run(1, FAIL)}), "killed-assert")
        self.assertEqual(cmp.classify({"a": run(), "b": {"unreached": True}}), "survived")
        self.assertEqual(cmp.classify({"a": {"unreached": True}}), "unreached")
        self.assertEqual(cmp.classify({"a": run(), "b": {"killed_by": "a"}}), "killed-assert")  # v1's skipped run
        self.assertEqual(cmp.classify({"a": run(0, FAIL)}), "bad-results")

    def test_the_runs_saved_by_stopping_at_the_first_kill(self):
        runs = {"a": run(), "b": run(1, FAIL), "c": run(), "d": {"unreached": True}, "e": run(1, FAIL)}
        self.assertEqual(cmp.saved_runs(["a", "b", "c", "d", "e"], runs), 2)
        self.assertEqual(cmp.saved_runs(["a", "c"], {"a": run(), "c": run()}), 0)


def v1_mutant(mid, runs, o0=None, hash_="h", file="m.c"):
    comp = {"status": "ok", "hash": hash_}
    if o0:
        comp["o0"] = {"status": "ok", "hash": o0}
    return {"id": mid, "file": file, "line": 3, "operator": "relational", "function": "f", "original": "<",
            "replacement": "<=", "compile": comp, "runs": runs}


def schema_mutant(mid, klass, runs=None, status="eligible"):
    return {"id": mid, "file": "m.c", "line": 3, "operator": "relational", "function": "f", "original": "<",
            "replacement": "<=", "status": status, "class": klass, "runs": runs or {}}


V1 = {"sources": [{"file": "m.c", "baseline": {"hash": "base"}}]}


class CompareTest(unittest.TestCase):
    def compare(self, v1_mutants, schema_mutants):
        return cmp.compare(dict(V1, mutants=v1_mutants), {"mutants": schema_mutants})

    def test_agreement_and_unreached_equals_survived(self):
        result = self.compare(
            [v1_mutant("a", {"t": run(1, FAIL)}), v1_mutant("b", {"t": run()}, hash_="g"), v1_mutant("c", {"t": run(1, CRASHED)}, hash_="k")],
            [schema_mutant("a", "killed-assert"), schema_mutant("b", "unreached"), schema_mutant("c", "killed-crash")])
        self.assertEqual((result["compared"], result["agree"], result["unexplained"]), (3, 3, 0))

    def test_a_disagreement_is_listed_with_place_operator_and_both_records(self):
        result = self.compare([v1_mutant("a", {"t": run(1, FAIL)})], [schema_mutant("a", "survived", {"t": run()})])
        [d] = result["disagreements"]
        self.assertEqual((d["file"], d["line"], d["operator"], d["v1"], d["schema"]), ("m.c", 3, "relational", "killed-assert", "survived"))
        self.assertEqual(d["v1_runs"], {"t": run(1, FAIL)})
        self.assertEqual(d["schema_runs"], {"t": run()})
        self.assertEqual(result["unexplained"], 1)

    def test_a_kill_of_a_mutant_no_test_reaches_is_a_disagreement(self):
        result = self.compare([v1_mutant("a", {"t": run(1, FAIL)})], [schema_mutant("a", "unreached", {"t": {"unreached": True}})])
        self.assertEqual(result["unexplained"], 1)

    def test_a_mutant_v1_ran_at_o0_after_the_optimiser_folded_it_is_explained(self):
        folded = v1_mutant("a", {"t": run(1, FAIL)}, o0="low", hash_="base")   # -O2 object equals the baseline's
        result = self.compare([folded], [schema_mutant("a", "survived", {"t": run()})])
        self.assertEqual((len(result["disagreements"]), result["unexplained"]), (1, 0))
        self.assertTrue(result["disagreements"][0]["explained"])

    def test_the_first_of_two_mutants_with_one_object_is_not_a_folded_run(self):
        first = v1_mutant("a", {"t": run(1, FAIL)}, o0="x", hash_="same")
        second = v1_mutant("b", {"t": run(1, FAIL)}, o0="y", hash_="same")
        self.assertEqual(cmp.folded_live(dict(V1, mutants=[first, second])), {("m.c", "b")})

    def test_only_eligible_mutants_are_compared_and_a_missing_v1_run_is_unexplained(self):
        result = self.compare([v1_mutant("a", {"t": run()})], [schema_mutant("a", "survived", status="ineligible"),
                                                               schema_mutant("zz", "survived")])
        self.assertEqual((result["compared"], result["unexplained"]), (1, 1))


class CollectTest(unittest.TestCase):
    def test_the_build_files_are_merged_into_one_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            def put(name, obj):
                path = tmp / name
                path.write_text(json.dumps(obj), encoding="utf-8")
                return str(path)

            mutants = [{"id": i, "file": "m.c", "function": "f", "line": n, "operator": "relational", "original": "<",
                        "replacement": "<="} for n, i in enumerate("abcde", 1)]
            gen = put("gen.json", {"file": "m.c", "sha256": "x", "mutants": mutants})
            table = put("table.json", {"live": 4, "eligible": 2, "compiles": 2, "reasons": {"type-change": 1},
                                       "entries": [{"index": 1, "id": "a"}, {"index": 2, "id": "b"}],
                                       "ineligible": {"c": "type-change"}, "unviable": ["d"]})
            baseline = put("base.json", run())
            reach = put("reach.json", {"record": run(), "reached": [1]})
            kill = put("kill.json", {"records": {"a": run(1, FAIL)}})
            manifest = put("manifest.json", {"label": "//m:m", "tests": ["t"], "baseline_runs": {"t": baseline},
                                             "sources": [{"rel": "m.c", "gen": gen, "table": table, "live": ["a", "b", "c", "d"]}],
                                             "reach": {"t": reach}, "kills": {"t": [kill]}})
            out = str(tmp / "report.json")
            cmp.cmd_collect(["--manifest", manifest, "--out", out])
            report = json.loads((tmp / "report.json").read_text(encoding="utf-8"))
        by_id = {m["id"]: m for m in report["mutants"]}
        self.assertEqual(by_id["a"]["class"], "killed-assert")
        self.assertEqual(by_id["b"]["class"], "unreached")          # entry 2 is not in the reach set
        self.assertEqual(by_id["b"]["runs"], {"t": {"unreached": True}})
        self.assertEqual((by_id["c"]["status"], by_id["c"]["reason"]), ("ineligible", "type-change"))
        self.assertEqual(by_id["d"]["status"], "schema-unviable")
        self.assertEqual(by_id["e"]["status"], "v1-not-run")
        summary = report["summary"]
        self.assertEqual(summary["status"], {"eligible": 2, "ineligible": 1, "schema-unviable": 1, "v1-not-run": 1})
        self.assertEqual(summary["not_eligible"], {"schema-unviable": 1, "type-change": 1})
        self.assertEqual(summary["classes"], {"killed-assert": 1, "unreached": 1})
        self.assertEqual((summary["kill_runs"], summary["v1_runs_without_stop"]), (1, 2))
        self.assertEqual(summary["baseline_reproduced"], {"t": True})

    def test_a_reach_run_that_differs_from_the_baseline_is_reported_as_not_reproduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "b.json").write_text(json.dumps(run()), encoding="utf-8")
            (tmp / "r.json").write_text(json.dumps({"record": run(1, FAIL), "reached": []}), encoding="utf-8")
            same = cmp.baseline_check({"reach": {"t": str(tmp / "r.json")}, "baseline_runs": {"t": str(tmp / "b.json")}})
        self.assertEqual(same, {"t": False})


if __name__ == "__main__":
    unittest.main()
