"""T021: `grade.write_verdict` and `rigor verify` (U30: nothing is signed; a throwaway gate repo, no Buck2)."""

import json
import os
import pathlib
import shutil
import subprocess
from types import SimpleNamespace
from unittest import mock

from rigor_lib import approvals, grade, grade_steps, jsonio, verdict, witness_bundle
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, read_json, run_rigor
from tests.test_verdict_inputs import Fixture, HEAD, GATE, WITNESS_FIXTURE


def passing_results(directory, order):
    for gate_id in order:
        doc = {"gate": gate_id, "status": "PASS", "findings": [], "metadata": {}}
        (directory / (gate_id + ".json")).write_text(json.dumps(doc))


class GradeVerdict(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.fixture = Fixture(str(self.tmp))
        self.order_bytes = (GATE_DIR / "order.txt").read_bytes()
        self.order = verdict.parse_order(self.order_bytes)
        self.results = self.sub("results")
        self.out = self.tmp / "verdict.json"

    def grading(self, results=True):
        g, documents = self.fixture.grading()
        if results:
            passing_results(self.results, self.order)
            for gate_id in ("clone", "assemble"):
                doc = {"gate": gate_id, "status": "PASS", "findings": [], "metadata": documents[gate_id]["metadata"]}
                (self.results / (gate_id + ".json")).write_text(json.dumps(doc))
        g.order_bytes = self.order_bytes
        g.results = str(self.results)
        g.args.verdict_out = str(self.out)
        g.args.order_file = str(GATE_DIR / "order.txt")
        return g

    def test_a_pass_binds_the_inputs_and_uncached_stays_top_level(self):
        code = grade.write_verdict(self.grading())
        core = read_json(self.out)["core"]
        self.assertEqual((code, core["overall"]), (0, "PASS"))
        self.assertEqual(core["inputs"], self.fixture.inputs())
        self.assertIs(core["uncached"], False)
        self.assertEqual(core["inputs"]["head"], HEAD)
        self.assertEqual(core["inputs"]["gate_sha"], GATE)

    def test_the_order_bytes_used_are_the_ones_hashed_by_the_caller_not_the_file_now(self):
        g = self.grading()
        g.order_bytes = b"".join((i + "\n").encode() for i in self.order[:-1])
        passing = [name for name in os.listdir(self.results)]
        self.assertTrue(passing)
        grade.write_verdict(g)
        self.assertEqual(len(read_json(self.out)["core"]["gates"]), len(self.order) - 1)

    def test_a_pass_with_an_unbound_input_is_an_internal_error(self):
        g = self.grading()
        meta = json.loads((self.results / "clone.json").read_text())
        del meta["metadata"]["merge_base"]
        (self.results / "clone.json").write_text(json.dumps(meta))
        with self.assertRaises(InternalError):
            grade.write_verdict(g)
        self.assertFalse(self.out.exists())

    def test_a_fail_may_have_null_inputs(self):
        g = self.grading(results=False)
        code = grade.write_verdict(g)
        core = read_json(self.out)["core"]
        self.assertEqual((code, core["overall"]), (1, "FAIL"))
        self.assertIsNone(core["inputs"]["head"])

    def test_a_dirty_gate_is_recorded(self):
        self.fixture.gate_clean = False
        g = self.grading()
        self.assertEqual(grade.write_verdict(g), 0)
        self.assertIs(read_json(self.out)["core"]["inputs"]["gate_clean"], False)

    def test_a_pass_without_a_witness_binds_null(self):
        self.fixture.file_hashes["witness_sha256"] = None
        self.assertEqual(grade.write_verdict(self.grading()), 0)
        self.assertIn("witness_sha256", read_json(self.out)["core"]["inputs"])
        self.assertIsNone(read_json(self.out)["core"]["inputs"]["witness_sha256"])

    def test_the_witness_tree_daemon_is_stopped_too(self):
        g = self.grading()
        g.gate_clean = True
        with mock.patch.object(grade, "start_grading", return_value=g), \
                mock.patch.object(grade, "run_gates", return_value=None), \
                mock.patch.object(grade.grade_context, "kill_daemon") as kill:
            grade.run(g.args)
        self.assertEqual([c.args for c in kill.call_args_list],
                         [(g.tree,), (os.path.join(g.work, "tree-witness"),)])

    def test_nothing_is_signed_and_the_grade_takes_no_key(self):
        g = self.grading()
        with mock.patch.object(grade, "start_grading", return_value=g), \
                mock.patch.object(grade, "run_gates", return_value=None), \
                mock.patch.object(grade.grade_context, "kill_daemon"):
            self.assertEqual(grade.run(g.args), 0)
        self.assertFalse((self.tmp / "verdict.json.sig").exists())
        self.assertFalse(hasattr(grade, "sign_verdict"))
        outcome = run_rigor(["grade", "--product-repo", "r", "--base", "b", "--head", "h", "--task", "t",
                             "--product", "p", "--work", self.tmp / "w", "--out", self.tmp / "o", "--sign-key", "k"])
        self.assertExit(outcome, 2)
        self.assertIn("--sign-key", outcome.stderr)

    def test_the_core_counts_and_lists_the_approvals_in_force(self):
        self.assertEqual(grade.write_verdict(self.grading()), 0)
        self.assertEqual(read_json(self.out)["core"]["approvals"], {"count": 0, "in_force": []})
        g = self.grading()
        g.args.approvals, g.head, g.src = "/a", HEAD, "/src"
        valid = [approvals.Approval("ratchet", "n.toml:k", "why", "e" * 40, "2" * 64),
                 approvals.Approval("suppression", "a.c:1-nolint", "ok", "e" * 40, "1" * 64)]
        with mock.patch.object(grade.approvals, "load_approvals", return_value=approvals.ApprovalSet(valid, [])):
            self.assertEqual(grade.write_verdict(g), 0)
        block = read_json(self.out)["core"]["approvals"]
        self.assertEqual(block["count"], 2)
        self.assertEqual([e["stem"] for e in block["in_force"]], ["1" * 64, "2" * 64])
        self.assertEqual(block["in_force"][1], {"kind": "ratchet", "scope": "n.toml:k", "reason": "why",
                                              "repo_sha": "e" * 40, "stem": "2" * 64})


class PlantedApprovals(TempDirTestCase):
    """U30 fix-up: an approvals directory the graded party can write would be in force, so it is refused."""

    def args(self, approvals):
        return SimpleNamespace(product_repo=str(self.tmp / "repo"), work=str(self.tmp / "work"), approvals=approvals)

    def test_inside_the_product_repo_or_the_work_directory_is_refused(self):
        os.makedirs(self.tmp / "repo" / "approvals")
        os.makedirs(self.tmp / "work" / "approvals")
        os.symlink(self.tmp / "repo" / "approvals", self.tmp / "link")
        for path, where in ((self.tmp / "repo" / "approvals", "product repository"),
                            (self.tmp / "work" / "approvals", "work directory"),
                            (self.tmp / "link", "product repository")):
            with self.assertRaisesRegex(InternalError, where):
                grade.refuse_planted_approvals(self.args(str(path)))

    def test_outside_both_or_none_is_accepted(self):
        os.makedirs(self.tmp / "approvals")
        os.makedirs(self.tmp / "repo-approvals")   # a sibling whose name starts like the repo is outside it
        for path in (None, str(self.tmp / "approvals"), str(self.tmp / "repo-approvals")):
            self.assertIsNone(grade.refuse_planted_approvals(self.args(path)))

    def test_the_grade_refuses_it_before_anything_is_written(self):
        repo = self.tmp / "repo"
        os.makedirs(repo / "approvals")
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\n')
        outcome = run_rigor(["grade", "--product-repo", repo, "--base", "main", "--head", "main", "--task", task,
                             "--product", GATE_DIR.parent / "products" / "selftest" / "product.toml",
                             "--approvals", repo / "approvals", "--work", self.tmp / "work",
                             "--out", self.tmp / "v.json", "--allow-dirty-gate"])
        self.assertExit(outcome, 2)
        self.assertIn("inside the product repository", outcome.stderr)
        self.assertFalse((self.tmp / "v.json").exists())


class GradeWitnessOption(TempDirTestCase):
    """`rigor grade --witness` end to end up to `clone` (no Buck2: the product repo does not exist, so
    `clone` is an internal error and the FAIL verdict still records the bound inputs)."""

    def grade(self, *extra):
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\n')
        self.work = self.tmp / "work"
        self.out = self.tmp / "verdict.json"
        return run_rigor(["grade", "--product-repo", self.tmp / "no-repo", "--base", "main", "--head", "main",
                          "--task", task, "--product", GATE_DIR.parent / "products" / "selftest" / "product.toml",
                          "--work", self.work, "--out", self.out, "--allow-dirty-gate", *extra])

    def bundle(self):
        target = self.tmp / "bundle"
        shutil.copytree(WITNESS_FIXTURE, target, symlinks=True)
        return target

    def test_a_bundle_is_snapshotted_and_bound(self):
        source = self.bundle()
        outcome = self.grade("--witness", source)
        self.assertExit(outcome, 2)
        self.assertIn("clone", outcome.stderr)
        inputs = read_json(self.out)["core"]["inputs"]
        self.assertEqual(inputs["witness_sha256"], witness_bundle.digest(witness_bundle.load(str(source))))
        copy = self.work / "inputs" / "witness"
        self.assertEqual(witness_bundle.digest(witness_bundle.load(str(copy))), inputs["witness_sha256"])

    def test_a_relative_bundle_path_is_made_absolute(self):
        names = ("product_repo", "task", "product", "approvals", "witness", "work", "verdict_out")
        args = SimpleNamespace(**{name: None for name in names})
        args.witness = "bundle"
        grade.absolute_arguments(args)
        self.assertEqual(args.witness, os.path.abspath("bundle"))

    def test_without_witness_the_input_is_null(self):
        outcome = self.grade()
        self.assertExit(outcome, 2)
        self.assertIsNone(read_json(self.out)["core"]["inputs"]["witness_sha256"])
        self.assertFalse((self.work / "inputs" / "witness").exists())

    def test_a_bad_bundle_is_exit_2_before_clone(self):
        source = self.bundle()
        os.symlink(source / "files" / "core" / "core.c", source / "files" / "core" / "alias.c")
        outcome = self.grade("--witness", source)
        self.assertExit(outcome, 2)
        self.assertIn("witness bundle: symlink", outcome.stderr)
        self.assertFalse(self.out.exists())
        self.assertFalse((self.work / "src").exists())
        self.assertEqual(os.listdir(self.work / "results"), [])

    def test_a_malformed_manifest_is_exit_2_before_clone(self):
        source = self.bundle()
        (source / "witness.toml").write_text("product = \"x\"\n")
        outcome = self.grade("--witness", source)
        self.assertExit(outcome, 2)
        self.assertIn("witness.toml", outcome.stderr)
        self.assertFalse(self.out.exists())
        self.assertEqual(os.listdir(self.work / "results"), [])


def approval(stem, kind="equivalent-mutant", scope="mutants/core#abc123"):
    return approvals.Approval(kind, scope, "why", "a" * 40, stem)


class UnusedApprovals(GradeVerdict):
    """T068: valid approvals no gate used are verdict-level `unused-approval` info findings."""

    def graded(self, valid, used=(), drop=(), approvals_dir="/a"):
        g = self.grading()
        g.args.approvals, g.src, g.head = approvals_dir, "/src", "a" * 40
        doc = {"gate": "mutants", "status": "PASS", "findings": [],
               "metadata": {"approvals_used": list(used)}}
        (self.results / "mutants.json").write_text(json.dumps(doc))
        for gate_id in drop:
            (self.results / (gate_id + ".json")).unlink()
        with mock.patch.object(grade.approvals, "load_approvals",
                               return_value=approvals.ApprovalSet(valid, [])) as load:
            code = grade.write_verdict(g)
        return code, read_json(self.out)["core"], load

    def test_an_approval_no_gate_used_is_reported_as_info_and_the_verdict_still_passes(self):
        # the T058 drift shape: the body changed, the mutant id no longer exists, nothing used the approval
        code, core, load = self.graded([approval("s1")], used=[])
        self.assertEqual((code, core["overall"]), (0, "PASS"))
        self.assertEqual(core["unused_approvals"], [{
            "rule": "unused-approval", "severity": "info", "kind": "equivalent-mutant", "stem": "s1",
            "scope": "mutants/core#abc123", "reason": "not_used"}])
        self.assertEqual(load.call_args.args[:3], ("/a", "/src", "a" * 40))

    def test_a_used_approval_is_not_reported_and_the_rest_are_sorted(self):
        _, core, _ = self.graded([approval("s2"), approval("s1"), approval("s3")], used=["s2"])
        self.assertEqual([item["stem"] for item in core["unused_approvals"]], ["s1", "s3"])

    def test_a_gate_that_did_not_run_makes_the_report_fail_closed(self):
        _, core, _ = self.graded([approval("s1"), approval("s2")], used=["s2"], drop=["witness-tests"])
        self.assertEqual([(i["stem"], i["reason"]) for i in core["unused_approvals"]],
                         [("s1", "gate_not_run")])
        self.assertEqual(core["overall"], "FAIL")

    def test_the_entry_is_covered_by_the_core_hash(self):
        _, with_entry, _ = self.graded([approval("s1")])
        document = read_json(self.out)
        self.assertEqual(document["core_sha256"], jsonio.sha256_hex(jsonio.canonical_dumps(with_entry)))
        stripped = dict(with_entry, unused_approvals=[])
        self.assertNotEqual(jsonio.sha256_hex(jsonio.canonical_dumps(stripped)), document["core_sha256"])

    def test_invalid_approvals_are_not_double_reported(self):
        g = self.grading()
        g.args.approvals, g.src, g.head = "/a", "/src", "a" * 40
        forged = approvals.ApprovalSet([], [{"rule": "forged-approval", "severity": "error"}])
        with mock.patch.object(grade.approvals, "load_approvals", return_value=forged):
            grade.write_verdict(g)
        self.assertEqual(read_json(self.out)["core"]["unused_approvals"], [])

    def test_without_approvals_or_a_head_the_list_is_empty(self):
        self.assertEqual(grade.write_verdict(self.grading()), 0)
        self.assertEqual(read_json(self.out)["core"]["unused_approvals"], [])
        g = self.grading()
        g.args.approvals, g.head = "/a", ""
        with mock.patch.object(grade.approvals, "load_approvals") as load:
            grade.write_verdict(g)
        load.assert_not_called()
        self.assertEqual(read_json(self.out)["core"]["unused_approvals"], [])


class TrustFilesFromSnapshot(TempDirTestCase):
    """T071: the gate order is snapshotted with the other inputs; the gates and the verdict read only the
    copy, so a change to the live file mid-grade changes nothing. (U30: there is no signers file any more.)"""

    def setUp(self):
        super().setUp()
        self.live_order = self.tmp / "live_order.txt"
        self.live_order.write_bytes((GATE_DIR / "order.txt").read_bytes())
        self.work = self.tmp / "work"
        self.out = self.tmp / "verdict.json"
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\n')
        self.args = SimpleNamespace(
            product_repo=str(self.tmp / "repo"), task=str(task), approvals=None, witness=None,
            work=str(self.work), verdict_out=str(self.out), allow_dirty_gate=False, uncached=False,
            product=str(GATE_DIR.parent / "products" / "selftest" / "product.toml"))

    def start(self):
        with mock.patch.object(grade.grade_context, "ORDER_FILE", str(self.live_order)), \
                mock.patch.object(grade.grade_context, "seal_process_environment"), \
                mock.patch.object(grade.grade_context, "gate_checkout_state", return_value=(GATE, True)):
            return grade.start_grading(self.args)

    def test_a_change_to_the_live_files_mid_grade_changes_neither_the_gates_nor_the_verdict(self):
        seen = {}

        def hook(g):
            self.live_order.write_bytes(b"clone\n")
            with mock.patch.object(grade_steps.suppressions, "run") as run, \
                    mock.patch.object(grade_steps, "_graded_entries", return_value=[]):
                run.return_value = SimpleNamespace(status="PASS")
                grade_steps.suppressions_gate(g)
            seen["order"] = pathlib.Path(g.args.order_file).read_bytes()
            seen["args"] = vars(run.call_args[0][0])
            return None

        g = self.start()
        with mock.patch.object(grade.grade_pipeline, "GATES", (("clone", hook),)):
            grade.run_gates(g)
        self.assertNotIn("allowed_signers", seen["args"])
        inputs = g.inputs
        self.assertNotIn("allowed_signers_sha256", inputs)
        self.assertEqual(seen["order"], (GATE_DIR / "order.txt").read_bytes())
        order = (GATE_DIR / "order.txt").read_bytes()
        self.assertEqual(inputs["order_sha256"], jsonio.sha256_hex(order))
        self.assertEqual(g.order_bytes, order)
        self.assertEqual(pathlib.Path(g.args.order_file).read_bytes(), order)

    def test_the_verdict_is_built_from_the_snapshotted_order(self):
        g = self.start()
        self.live_order.write_bytes(b"clone\n")
        order = verdict.parse_order(g.order_bytes)
        os.makedirs(g.results, exist_ok=True)
        passing_results(pathlib.Path(g.results), order)
        with mock.patch.object(grade.verdict_inputs, "build_inputs", return_value={}), \
                mock.patch.object(grade.verdict_inputs, "missing_inputs", return_value=[]):
            grade.write_verdict(g)
        document = read_json(self.out)
        self.assertEqual(document["metadata"]["order_file"], str(self.work / "inputs" / "order.txt"))
        self.assertEqual(len(document["core"]["gates"]), len(order))

    def test_a_missing_order_is_an_internal_error_before_any_gate(self):
        self.live_order.unlink()
        with self.assertRaisesRegex(InternalError, "order.txt"):
            self.start()
