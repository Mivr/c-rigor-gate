"""Tests for `rigor verdict`."""

import hashlib
import json

from tests.helpers import TempDirTestCase, read_json, run_rigor


def gate_result(gate, status="PASS", findings=None, metadata=None):
    return {"gate": gate, "status": status, "findings": findings or [], "metadata": metadata or {}}


def error_finding(rule="x"):
    return {"rule": rule, "severity": "error"}


class VerdictCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.results = self.sub("results")
        self.order = self.tmp / "order.txt"
        self.out = self.tmp / "verdict.json"

    def put(self, gate, doc=None, raw=None, directory=None):
        path = (directory or self.results) / (gate + ".json")
        if raw is not None:
            path.write_bytes(raw)
        else:
            path.write_text(json.dumps(doc if doc is not None else gate_result(gate)))

    def set_order(self, gates, text=None):
        self.order.write_text(text if text is not None else "".join(g + "\n" for g in gates))

    def run_verdict(self, results=None, order=None, out=None):
        return run_rigor(["verdict", "--order", order or self.order,
                          "--results", results or self.results, "--out", out or self.out])

    def verdict(self, code):
        outcome = self.run_verdict()
        self.assertExit(outcome, code)
        return read_json(self.out)


class VerdictGreenTests(VerdictCase):
    def test_all_pass(self):
        for gate in ("contract", "tests"):
            self.put(gate)
        self.set_order(["contract", "tests"])
        doc = self.verdict(0)
        self.assertEqual(doc["core"]["overall"], "PASS")
        self.assertEqual([(g["id"], g["status"]) for g in doc["core"]["gates"]],
                         [("contract", "PASS"), ("tests", "PASS")])

    def test_gates_are_listed_in_order_file_order(self):
        for gate in ("a", "b", "c"):
            self.put(gate)
        self.set_order(["c", "a", "b"])
        self.assertEqual([g["id"] for g in self.verdict(0)["core"]["gates"]], ["c", "a", "b"])

    def test_info_only_gate_counts_as_pass(self):
        self.put("tests", gate_result("tests", "PASS", [{"rule": "i", "severity": "info"}]))
        self.set_order(["tests"])
        self.assertEqual(self.verdict(0)["core"]["overall"], "PASS")

    def test_output_is_canonical_json(self):
        self.put("a")
        self.set_order(["a"])
        self.assertExit(self.run_verdict(), 0)
        raw = self.out.read_bytes()
        again = (json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.assertEqual(raw, again)

    def test_core_sha256_is_the_hash_of_the_canonical_core(self):
        self.put("a")
        self.set_order(["a"])
        doc = self.verdict(0)
        core_bytes = (json.dumps(doc["core"], sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.assertEqual(doc["core_sha256"], hashlib.sha256(core_bytes).hexdigest())

    def test_rerun_gives_identical_core_and_hash(self):
        self.put("a", gate_result("a", "PASS", metadata={"seconds": 1.5, "host": "one"}))
        self.set_order(["a"])
        first = self.verdict(0)
        other_results = self.sub("elsewhere")
        self.put("a", gate_result("a", "PASS", metadata={"seconds": 9.9, "host": "two"}),
                 directory=other_results)
        outcome = self.run_verdict(results=other_results, out=self.tmp / "second.json")
        self.assertExit(outcome, 0)
        second = read_json(self.tmp / "second.json")
        self.assertEqual(first["core_sha256"], second["core_sha256"])
        self.assertEqual(first["core"], second["core"])
        self.assertNotEqual(first["metadata"], second["metadata"])

    def test_metadata_holds_gate_metadata_and_paths_but_not_core(self):
        self.put("a", gate_result("a", "PASS", metadata={"seconds": 1.5}))
        self.set_order(["a"])
        doc = self.verdict(0)
        self.assertEqual(doc["metadata"]["gate_metadata"], {"a": {"seconds": 1.5}})
        self.assertNotIn("seconds", json.dumps(doc["core"]))

    def test_unlisted_results_are_ignored_but_recorded(self):
        self.put("a")
        self.put("zzz", gate_result("zzz", "FAIL", [error_finding()]))
        self.set_order(["a"])
        doc = self.verdict(0)
        self.assertEqual(doc["metadata"]["unlisted_results"], ["zzz.json"])


class VerdictRedTests(VerdictCase):
    def test_one_failing_gate_fails_the_verdict(self):
        self.put("a")
        self.put("b", gate_result("b", "FAIL", [error_finding()]))
        self.set_order(["a", "b"])
        doc = self.verdict(1)
        self.assertEqual(doc["core"]["overall"], "FAIL")
        self.assertEqual([g["status"] for g in doc["core"]["gates"]], ["PASS", "FAIL"])
        self.assertEqual(doc["core"]["gates"][1]["findings_count"], 1)

    def test_missing_result_is_not_run_and_fails(self):
        self.put("a")
        self.set_order(["a", "b"])
        doc = self.verdict(1)
        self.assertEqual(doc["core"]["overall"], "FAIL")
        self.assertEqual([g["status"] for g in doc["core"]["gates"]], ["PASS", "NOT_RUN"])

    def test_all_gates_missing_fails(self):
        self.set_order(["a", "b"])
        self.assertEqual(self.verdict(1)["core"]["overall"], "FAIL")

    def test_empty_order_file_fails(self):
        self.put("a")
        self.set_order([], text="")
        doc = self.verdict(1)
        self.assertEqual(doc["core"], {"gates": [], "overall": "FAIL"})

    def test_findings_are_committed_to_by_the_hash(self):
        self.put("a", gate_result("a", "FAIL", [error_finding("one")]))
        self.set_order(["a"])
        first = self.verdict(1)["core_sha256"]
        self.put("a", gate_result("a", "FAIL", [error_finding("two")]))
        self.assertNotEqual(self.verdict(1)["core_sha256"], first)

    def test_finding_order_in_result_file_does_not_change_the_hash(self):
        self.set_order(["a"])
        self.put("a", gate_result("a", "FAIL", [error_finding("one"), error_finding("two")]))
        first = self.verdict(1)["core_sha256"]
        self.put("a", gate_result("a", "FAIL", [error_finding("two"), error_finding("one")]))
        self.assertEqual(self.verdict(1)["core_sha256"], first)

    def test_status_change_changes_the_hash(self):
        self.set_order(["a"])
        self.put("a")
        first = self.verdict(0)["core_sha256"]
        self.put("a", gate_result("a", "FAIL", [error_finding()]))
        self.assertNotEqual(self.verdict(1)["core_sha256"], first)


class VerdictErrorTests(VerdictCase):
    def assertErrors(self):
        self.out.write_text("stale PASS")
        self.assertExit(self.run_verdict(), 2)
        self.assertFalse(self.out.exists(), "stale verdict must be removed on error")

    def test_bad_order_files(self):
        self.put("a")
        for text in ("a\n\nb\n", "\n", "a\na\n", "A\n", "a b\n", "a\r\n", "-a\n", "a/b\n", " a\n"):
            with self.subTest(text=text):
                self.set_order([], text=text)
                self.assertErrors()

    def test_order_file_without_trailing_newline_is_fine(self):
        self.put("a")
        self.set_order([], text="a")
        self.assertExit(self.run_verdict(), 0)

    def test_missing_order_file(self):
        self.order = self.tmp / "nope.txt"
        self.assertErrors()

    def test_missing_results_directory(self):
        self.set_order(["a"])
        self.assertExit(self.run_verdict(results=self.tmp / "nope"), 2)

    def test_result_that_is_not_valid_json(self):
        self.set_order(["a"])
        for raw in (b"", b"{", b"[]", b'"PASS"', b'{"status":"PASS","status":"PASS"}',
                    b"\xff\xfe", b'{"gate":"a","status":NaN,"findings":[],"metadata":{}}'):
            with self.subTest(raw=raw):
                self.put("a", raw=raw)
                self.assertErrors()

    def test_result_with_wrong_shape(self):
        self.set_order(["a"])
        good = gate_result("a")
        bad_documents = [
            {k: v for k, v in good.items() if k != "metadata"},
            dict(good, extra=1),
            dict(good, gate="b"),
            dict(good, gate=1),
            dict(good, status="pass"),
            dict(good, status="NOT_RUN"),
            dict(good, status=True),
            dict(good, findings="none"),
            dict(good, findings=[1]),
            dict(good, findings=[{"severity": "error"}]),
            dict(good, findings=[{"rule": "x", "severity": "warn"}]),
            dict(good, findings=[{"rule": "x"}]),
            dict(good, metadata=[]),
        ]
        for doc in bad_documents:
            with self.subTest(doc=doc):
                self.put("a", doc)
                self.assertErrors()

    def test_pass_that_carries_an_error_finding_is_inconsistent(self):
        self.set_order(["a"])
        self.put("a", gate_result("a", "PASS", [error_finding()]))
        self.assertErrors()

    def test_fail_without_an_error_finding_is_inconsistent(self):
        self.set_order(["a"])
        self.put("a", gate_result("a", "FAIL", []))
        self.assertErrors()

    def test_result_entry_that_is_a_directory(self):
        self.set_order(["a"])
        (self.results / "a.json").mkdir()
        self.assertErrors()

    def test_unwritable_output_is_exit_2(self):
        self.put("a")
        self.set_order(["a"])
        self.assertExit(self.run_verdict(out=self.tmp / "no" / "such" / "dir" / "v.json"), 2)
