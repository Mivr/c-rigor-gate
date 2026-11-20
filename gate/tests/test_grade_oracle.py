"""The `oracle` gate of `rigor grade` (T2G7): registration, `--only`, the bundle snapshot and its hash in the verdict, the replay
package and the step with a faked Buck2, and `rigor verify --expect-oracle-sha`."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade_oracle, grade_pipeline, jsonio, oracle_bundle, verdict, verdict_inputs
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, base_env, run_rigor
from tests.test_oracle import gen
from tests.test_verdict_inputs import Fixture

POLICY = 'required = true\nreplayer = "//rp:replay"\ntraces = ["scripted-01"]\n'


class Registration(unittest.TestCase):
    def test_it_is_registered_after_sim_and_needs_the_toolchain(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(ids[ids.index("sim") + 1], "oracle")
        self.assertTrue(getattr(dict(grade_pipeline.GATES)["oracle"], "needs_toolchain", False))
        self.assertEqual(verdict.read_order(str(GATE_DIR / "order.txt")), ids)

    def test_only_oracle_runs_with_the_foundation_and_the_built_tree(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        self.assertEqual(grade_pipeline.selection(["oracle"], ids),
                         {"clone", "assemble", "toolchain", "buckfiles", "build", "tests-release", "tests-san", "oracle"})
        self.assertEqual(grade_pipeline.selection(["sim", "oracle"], ids) - grade_pipeline.selection(["oracle"], ids), {"sim"})


class Snapshot(TempDirTestCase):
    def bundle(self, name="bundle"):
        directory = self.tmp / name
        gen.main(str(directory))
        return directory

    def snapshot(self, source, product="canary"):
        destination = self.tmp / ("w%d" % len(list(self.tmp.glob("w*")))) / "inputs" / "oracle"
        destination.parent.mkdir(parents=True)
        return verdict_inputs.snapshot_oracle(None if source is None else str(source), str(destination), product), destination

    def test_without_a_bundle_it_is_null_and_nothing_is_written(self):
        sha, destination = self.snapshot(None)
        self.assertIsNone(sha)
        self.assertFalse(destination.exists())

    def test_the_copy_is_loaded_and_hashed(self):
        source = self.bundle()
        sha, destination = self.snapshot(source)
        self.assertEqual(sha, oracle_bundle.digest(oracle_bundle.load(str(source))))
        self.assertEqual(sha, oracle_bundle.digest(oracle_bundle.load(str(destination))))
        self.assertEqual(sorted(str(p.relative_to(destination)) for p in destination.rglob("*")),
                         sorted(str(p.relative_to(source)) for p in source.rglob("*")))

    def test_every_defect_is_exit_2_before_clone(self):
        source = self.bundle()
        with self.assertRaises(InternalError):
            self.snapshot(source, product="another")
        link = self.tmp / "link"
        os.symlink(source, link)
        with self.assertRaises(InternalError):
            self.snapshot(link)
        os.symlink(source / "oracle.toml", source / "files" / "x.trace")
        with self.assertRaises(InternalError):
            self.snapshot(source)
        broken = self.bundle("broken")
        (broken / "files" / "scripted-01.trace").write_bytes(b"x\n")
        with self.assertRaises(InternalError):
            self.snapshot(broken)

    def test_the_hash_is_in_the_inputs_and_follows_the_bundle(self):
        sha, _ = self.snapshot(self.bundle())
        fixture = Fixture(str(self.tmp))
        fixture.file_hashes["oracle_sha256"] = sha
        self.assertEqual(fixture.inputs()["oracle_sha256"], sha)
        self.assertEqual(verdict_inputs.missing_inputs(fixture.inputs()), [])
        other = Fixture(str(self.tmp))
        other.file_hashes["oracle_sha256"] = None
        self.assertNotEqual(fixture.core_sha256(), other.core_sha256())
        self.assertEqual(verdict_inputs.missing_inputs(other.inputs()), [])

    def test_the_gate_files_are_snapshotted_by_name(self):
        for name in ("oracle-policy.toml", "oracle-normalise.toml", "oracle-excluded.toml"):
            self.assertIn(name, verdict_inputs.PRODUCT_FILES)
        for key in ("oracle_sha256", "oracle_policy_sha256", "oracle_normalise_sha256", "oracle_excluded_sha256"):
            self.assertIn(key, verdict_inputs.OPTIONAL_KEYS)


class Package(unittest.TestCase):
    def test_the_build_file(self):
        text = grade_oracle.build_file_text("//rp:replay", ["a", "b-1"])
        self.assertIn('srcs = ["files/a.trace", "files/b-1.trace"]', text)
        self.assertIn("$(location //rp:replay) < $f", text)
        self.assertIn('out = "traces"', text)
        self.assertEqual(text.count("native.genrule"), 1)


class Step(TempDirTestCase):
    def grading(self, policy=POLICY, status=None, role="implementer", bundle=True, files=()):
        product_dir = self.sub("product")
        (product_dir / "product.toml").write_text('name = "canary"\n')
        for name, text in (("oracle-policy.toml", policy),) + tuple(files):
            if text is not None:
                (product_dir / name).write_text(text)
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\nrole = "%s"\n' % role)
        path = None
        sha = None
        if bundle:
            path = self.tmp / "snapshot"
            gen.main(str(path))
            sha = oracle_bundle.digest(oracle_bundle.load(str(path)))
        args = SimpleNamespace(product=str(product_dir / "product.toml"), uncached=False, task=str(task),
                               oracle=None if path is None else str(path))
        done = {gate: "PASS" for gate in grade_oracle.REQUIRED}
        done.update(status or {})
        work, tree = self.sub("work"), self.sub("tree")
        return SimpleNamespace(args=args, work=str(work), tree=str(tree), status=done, inputs={"oracle_sha256": sha},
                               product=SimpleNamespace(name="canary"))

    def fake_buck(self, g, replay=None, success=True):
        """A Buck2 that "builds" the package: its output is what `replay(text)` makes of each trace of the package."""
        seen = {}

        def run(tree, args):
            package = os.path.join(tree, "gate-oracle")
            seen["files"] = sorted(os.listdir(os.path.join(package, "files")))
            seen["buck"] = Path(package, "BUCK").read_text()
            seen["package_file"] = os.path.isfile(os.path.join(tree, "PACKAGE"))
            output = os.path.join(tree, "buck-out", "out", "traces")
            os.makedirs(output, exist_ok=True)
            for name in seen["files"]:
                data = Path(package, "files", name).read_bytes()
                with open(os.path.join(output, name), "wb") as handle:
                    handle.write(replay(data) if replay else data)
            report = args[args.index("--build-report") + 1]
            entry = {"success": "SUCCESS" if success else "FAIL", "outputs": {"DEFAULT": ["buck-out/out/traces"]}}
            jsonio.write_atomic(report, jsonio.canonical_dumps({"results": {"root//gate-oracle:replay": entry}}))
            seen["args"] = args
            return (0 if success else 1), "", "stderr of the replayer: secret trace text"

        return seen, mock.patch.object(grade_oracle.grade_build, "run_buck", side_effect=run)

    def run_step(self, g, **kwargs):
        seen, patch = self.fake_buck(g, **kwargs)
        with patch, mock.patch.object(grade_oracle.grade_build, "action_counts", return_value=(2, 3)), \
                mock.patch.object(grade_oracle.grade_context, "kill_daemon"):
            return grade_oracle.oracle_gate_step(g), seen

    def test_it_does_not_run_unless_the_tree_built_and_every_test_passed(self):
        for gate in grade_oracle.REQUIRED:
            with mock.patch.object(grade_oracle, "_step") as step:
                self.assertIsNone(grade_oracle.oracle_gate_step(self.grading(status={gate: "FAIL"})), gate)
                step.assert_not_called()

    def test_test_author_is_not_applicable(self):
        result = grade_oracle.oracle_gate_step(self.grading(role="test-author"))
        self.assertEqual((result.status, result.findings[0]["rule"]), ("PASS", "not-applicable"))

    def test_no_bundle_and_nothing_required_passes_with_info(self):
        result = grade_oracle.oracle_gate_step(self.grading(policy=None, bundle=False))
        self.assertEqual((result.status, [f["rule"] for f in result.findings]), ("PASS", ["no-oracle"]))

    def test_no_bundle_while_required_is_a_finding_and_builds_nothing(self):
        with mock.patch.object(grade_oracle.grade_build, "run_buck") as buck:
            result = grade_oracle.oracle_gate_step(self.grading(bundle=False))
        buck.assert_not_called()
        self.assertEqual((result.status, [f["rule"] for f in result.findings]), ("FAIL", ["oracle-bundle-missing"]))

    def test_a_faithful_replayer_passes_and_the_package_is_gone_again(self):
        g = self.grading()
        result, seen = self.run_step(g)
        self.assertEqual((result.status, result.findings), ("PASS", []))
        self.assertEqual(seen["files"], ["random-0011.trace", "random-0012.trace", "scripted-01.trace", "scripted-02.trace"])
        self.assertTrue(seen["package_file"])
        self.assertEqual(seen["args"][seen["args"].index("--target-platforms") + 1], "toolchains//:linux_san")
        self.assertEqual(seen["args"][-1], "//gate-oracle:replay")
        self.assertEqual(os.listdir(g.tree), ["buck-out"])
        self.assertEqual((result.metadata["executed_actions"], result.metadata["cached_actions"]), (2, 3))
        self.assertEqual((result.metadata["traces"], result.metadata["replayed"], result.metadata["steps"]), (4, 4, 71))
        self.assertEqual(result.metadata["oracle_sha256"], g.inputs["oracle_sha256"])

    def test_a_divergent_replayer_fails_with_the_position_and_no_text(self):
        result, _ = self.run_step(self.grading(), replay=lambda data: data.replace(b'"entered":3', b'"entered":4', 1))
        self.assertEqual(result.status, "FAIL")
        self.assertEqual({f["rule"] for f in result.findings}, {"oracle-divergence"})
        self.assertNotIn("entered", jsonio.canonical_dumps(result.findings).decode())

    def test_a_replay_that_failed_names_no_output_of_the_replayer(self):
        result, _ = self.run_step(self.grading(), success=False)
        self.assertEqual([f["rule"] for f in result.findings], ["oracle-replay-failed"])
        self.assertNotIn("secret", result.to_json_bytes().decode())

    def test_policy_findings_survive_a_failed_replay(self):
        result, _ = self.run_step(self.grading(policy=POLICY.replace("scripted-01", "scripted-99")), success=False)
        self.assertEqual([f["rule"] for f in result.findings], ["oracle-replay-failed", "oracle-bundle-missing"])

    def test_excluded_traces_are_not_given_to_the_replayer(self):
        row = '[[exclude]]\ntrace_id = "scripted-01"\nreason = "r"\ndecision = "D1"\n'
        g = self.grading(policy=POLICY + "excluded_max = 1\n", files=(("oracle-excluded.toml", row),))
        result, seen = self.run_step(g)
        self.assertEqual(seen["files"], ["random-0011.trace", "random-0012.trace", "scripted-02.trace"])
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.metadata["excluded"], 1)

    def test_a_bundle_that_changed_after_the_snapshot_is_exit_2(self):
        g = self.grading()
        g.inputs["oracle_sha256"] = "0" * 64
        with self.assertRaises(InternalError):
            grade_oracle.oracle_gate_step(g)

    def test_a_bundle_needs_a_replayer_in_the_policy(self):
        with self.assertRaises(InternalError):
            grade_oracle.oracle_gate_step(self.grading(policy="required = true\n"))

    def test_a_product_that_put_a_package_in_the_way_is_exit_2(self):
        g = self.grading()
        os.makedirs(os.path.join(g.tree, "gate-oracle"))
        with self.assertRaises(InternalError):
            self.run_step(g)


class VerifyExpectation(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.key = str(self.tmp / "key")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", self.key], check=True, capture_output=True, env=base_env())
        pub = (self.tmp / "key.pub").read_text().split()
        self.signers = self.tmp / "signers"
        self.signers.write_text('signer namespaces="c-rigor-gate-verdict" %s %s\n' % (pub[0], pub[1]))
        self.verdict = self.tmp / "verdict.json"
        self.fixture = Fixture(str(self.tmp))

    def make(self, sha):
        self.fixture.file_hashes["oracle_sha256"] = sha
        core = verdict.build_core(["a"], {"a": {"status": "PASS", "findings": []}})
        core["uncached"] = False
        core["inputs"] = self.fixture.inputs()
        document = {"core": core, "core_sha256": jsonio.sha256_hex(jsonio.canonical_dumps(core)), "metadata": {}}
        self.verdict.write_bytes(jsonio.canonical_dumps(document))
        if os.path.exists(str(self.verdict) + ".sig"):
            os.unlink(str(self.verdict) + ".sig")
        subprocess.run(["ssh-keygen", "-Y", "sign", "-n", "c-rigor-gate-verdict", "-f", self.key, str(self.verdict)],
                       check=True, capture_output=True, env=base_env())

    def verify(self, *extra):
        return run_rigor(["verify", "--verdict", self.verdict, "--allowed-signers", self.signers, *extra])

    def test_expect_oracle_sha(self):
        sha = "ab" * 32
        self.make(sha)
        self.assertEqual(self.verify().code, 0)
        self.assertEqual(self.verify("--expect-oracle-sha", sha).code, 0)
        other = self.verify("--expect-oracle-sha", "cd" * 32)
        self.assertEqual(other.code, 1)
        self.assertIn("oracle_sha256 is %s, expected %s" % (sha, "cd" * 32), other.stdout)
        self.make(None)
        missing = self.verify("--expect-oracle-sha", sha)
        self.assertEqual(missing.code, 1)
        self.assertIn("oracle_sha256 is null", missing.stdout)

    def test_a_malformed_oracle_sha_is_rejected(self):
        self.make("short")
        outcome = self.verify()
        self.assertEqual(outcome.code, 1)
        self.assertIn("oracle_sha256 is missing or malformed", outcome.stdout)


if __name__ == "__main__":
    unittest.main()
