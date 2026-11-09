"""The `toolchain` gate (T073, B33 a) through the pipeline, with the verifier faked at its seam
(`grade_build._run_buck`, the Buck2 runner `toolchain_verify.prepare` is given). No Buck2 runs."""

import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade, grade_build, grade_pipeline, grade_toolchain, jsonio, toolchain_verify, verdict
from rigor_lib.findings import GateResult
from tests.helpers import GATE_DIR, TempDirTestCase

# The gates that compile or link: none of them may run unless `toolchain` passed.
COMPILING = ["semantic-suppressions", "symbols", "build", "structure", "mode-divergence", "fuzz", "mutants",
             "witness-tests", "mutants-witness"]

# What buck2 (exit 3) printed when the verify action of the llvm tree failed in the T073 demonstration
# (one sha256 of a scratch copy of llvm.manifest flipped), shortened.
VERIFY_STDERR = (
    "[2026-11-07T02:49:07.848+00:00] Action failed: toolchains//:llvm_verified "
    "(toolchains//:linux_release#e2375fbe4e23c7fb) (verify_tree llvm_verified)\n"
    "[2026-11-07T02:49:07.848+00:00] Remote command returned non-zero exit code 1\n"
    "[2026-11-07T02:49:07.848+00:00] Remote action digest: 'd771:142'\n"
    "[2026-11-07T02:49:07.848+00:00] Stdout: <empty>\n"
    "[2026-11-07T02:49:07.848+00:00] Stderr:\n"
    "TOOLCHAIN TREE DIFFERS FROM MANIFEST (1 differences)\n"
    "changed: bin/clang-19 (manifest ('f', 'x', 223765784, 'c57c'), tree ('f', 'x', 223765784, 'c57b'))\n"
    "\n"
    "BUILD FAILED\n")


class ToolchainPipeline(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.tree = self.sub("tree")
        manifests = self.tree / "gate" / "toolchains"
        manifests.mkdir(parents=True)
        for name in toolchain_verify.MANIFESTS:
            (manifests / name).write_bytes(("manifest of %s\n" % name).encode())
        self.results = self.sub("results")
        self.calls, self.ran = [], []
        self.verify = (0, "")
        original = grade_build._run_buck
        grade_build._run_buck = self.buck
        self.addCleanup(setattr, grade_build, "_run_buck", original)

    def buck(self, tree, args):
        self.calls.append(args)
        if toolchain_verify.CACHED_TARGETS[0] in args:
            return 0, "", ""
        if toolchain_verify.VERIFY_TARGETS[0] in args:
            return self.verify[0], "", self.verify[1]
        if args == ["log", "what-ran"]:
            return 0, "build\ttoolchains//:llvm_verified (verify_tree llvm_verified)\tre\tabc:1\n", ""
        self.fail("an unexpected buck2 command: %r" % (args,))

    def step(self, gate_id):
        def run(g):
            self.ran.append(gate_id)
            return GateResult(gate_id, [], {})
        return run

    def rows(self, assemble="PASS", real_steps=False):
        """assemble (stubbed), the real `toolchain` row, every compiling row and one gate that does not compile.

        With `real_steps` the compiling rows are those of grade_pipeline.GATES (their steps must never be
        reached); otherwise the same wrapper around a recording step."""
        findings = [] if assemble == "PASS" else [{"rule": "bad-path", "severity": "error"}]
        rows = [("assemble", lambda g: GateResult("assemble", findings, {}))]
        rows.append(next(row for row in grade_pipeline.GATES if row[0] == "toolchain"))
        for gate_id, step in grade_pipeline.GATES:
            if gate_id in COMPILING:
                rows.append((gate_id, step if real_steps else
                             grade_toolchain.needs_toolchain(gate_id, self.step(gate_id))))
        rows.append(("tests-stub", self.step("tests-stub")))
        return tuple(rows)

    def grade(self, uncached, **kwargs):
        g = SimpleNamespace(args=SimpleNamespace(uncached=uncached), status={}, tree=str(self.tree),
                            results=str(self.results))
        rows = self.rows(**kwargs)
        out = io.StringIO()
        with mock.patch.object(grade.grade_pipeline, "GATES", rows), contextlib.redirect_stdout(out):
            self.assertIsNone(grade.run_gates(g))
        order = [gate_id for gate_id, _ in rows]
        documents = verdict.load_results(str(self.results), order)
        core = verdict.build_core(order, documents)
        return {e["id"]: e["status"] for e in core["gates"]}, core["overall"], out.getvalue()

    def toolchain_findings(self):
        return json.loads((self.results / "toolchain.json").read_text())["findings"]

    def test_verified(self):
        statuses, overall, _ = self.grade(uncached=True)
        self.assertEqual((statuses["toolchain"], overall), ("PASS", "PASS"))
        [item] = self.toolchain_findings()
        self.assertEqual((item["rule"], item["severity"]), ("toolchain-verified", "info"))
        want = [{"path": "toolchains/" + n,
                 "sha256": jsonio.sha256_hex(("manifest of %s\n" % n).encode())} for n in toolchain_verify.MANIFESTS]
        self.assertEqual(item["manifests"], want)
        self.assertEqual(self.ran, COMPILING + ["tests-stub"])
        self.assertIn("--no-remote-cache", self.calls[1])
        self.assertEqual(len(self.calls), 3)  # fetch, uncached verify, what-ran: once per grade

    def test_cached_grade_is_not_verified_and_runs_no_buck2(self):
        statuses, overall, _ = self.grade(uncached=False)
        self.assertEqual((statuses["toolchain"], overall), ("PASS", "PASS"))
        [item] = self.toolchain_findings()
        self.assertEqual(item, {"rule": "toolchain-not-verified", "severity": "info", "reason": "cached grade"})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ran, COMPILING + ["tests-stub"])

    def test_cached_grade_passes_even_without_a_tree(self):
        statuses, _, _ = self.grade(uncached=False, assemble="FAIL")
        self.assertEqual(statuses["toolchain"], "PASS")
        self.assertEqual(self.calls, [])

    def test_mismatch_fails_the_gate_and_no_compiling_gate_runs(self):
        self.verify = (3, VERIFY_STDERR)
        statuses, overall, out = self.grade(uncached=True, real_steps=True)
        self.assertEqual((statuses["toolchain"], overall), ("FAIL", "FAIL"))
        self.assertEqual({g for g in COMPILING if statuses[g] == "NOT_RUN"}, set(COMPILING))
        self.assertEqual(statuses["tests-stub"], "PASS")  # a gate that does not compile still runs
        [item] = self.toolchain_findings()
        self.assertEqual(item, {"rule": "toolchain-mismatch", "severity": "error",
                                "manifest": "toolchains/llvm.manifest", "first_difference": "bin/clang-19",
                                "step": "verify", "exit_code": 3, "verifier_exit_code": 1})
        metadata = json.loads((self.results / "toolchain.json").read_text())["metadata"]
        self.assertIn("TOOLCHAIN TREE DIFFERS FROM MANIFEST", metadata["stderr_tail"])
        for gate_id in COMPILING:
            self.assertFalse((self.results / (gate_id + ".json")).exists(), gate_id)
            self.assertIn("%-14s not run: gate toolchain is FAIL" % gate_id, out)
        self.assertEqual(len(self.calls), 2)  # fetch and verify; no product build was started

    def test_mismatch_with_recording_steps(self):
        self.verify = (1, VERIFY_STDERR)
        statuses, _, _ = self.grade(uncached=True)
        self.assertEqual(self.ran, ["tests-stub"])
        self.assertEqual(statuses["build"], "NOT_RUN")

    def test_fetch_failure_is_a_mismatch_without_a_path(self):
        def no_cache(tree, args):
            self.calls.append(args)
            return 3, "", "no cache and no network"
        grade_build._run_buck = no_cache
        statuses, _, _ = self.grade(uncached=True)
        self.assertEqual(statuses["toolchain"], "FAIL")
        [item] = self.toolchain_findings()
        self.assertEqual((item["rule"], item["step"], item["exit_code"]), ("toolchain-mismatch", "fetch", 3))
        self.assertEqual((item["manifest"], item["first_difference"], item["verifier_exit_code"]),
                         (None, None, None))
        self.assertEqual(self.ran, ["tests-stub"])

    def test_uncached_without_a_tree_is_not_run(self):
        statuses, _, out = self.grade(uncached=True, assemble="FAIL")
        self.assertEqual(statuses["toolchain"], "NOT_RUN")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ran, ["tests-stub"])
        self.assertIn("not run: gate toolchain is NOT_RUN", out)


class ToolchainInTheGateList(unittest.TestCase):
    def test_exactly_the_compiling_gates_need_the_toolchain_and_come_after_it(self):
        ids = [gate_id for gate_id, _ in grade_pipeline.GATES]
        wrapped = [gate_id for gate_id, step in grade_pipeline.GATES if getattr(step, "needs_toolchain", False)]
        self.assertEqual(wrapped, COMPILING)
        self.assertEqual(ids.index("toolchain"), ids.index("assemble") + 1)
        self.assertLess(ids.index("toolchain"), min(ids.index(g) for g in COMPILING))

    def test_the_order_file_lists_toolchain_after_assemble(self):
        order = verdict.read_order(str(GATE_DIR / "order.txt"))
        self.assertEqual(order[order.index("assemble") + 1], "toolchain")


class FailureDetails(unittest.TestCase):
    def failure(self, step, err):
        return toolchain_verify.Failure(step, 1, err)

    def test_the_sysroot_manifest_when_its_action_is_named_first(self):
        err = VERIFY_STDERR.replace("llvm_verified", "sysroot_verified").replace("changed: bin/clang-19 (", "missing: usr/x (")
        item = grade_toolchain.mismatch(self.failure("verify", err))
        self.assertEqual((item["manifest"], item["first_difference"]), ("toolchains/sysroot.manifest", "usr/x"))

    def test_extra_and_missing_paths(self):
        for line, path in (("extra: lib/evil.so", "lib/evil.so"), ("missing: bin/ld.lld", "bin/ld.lld")):
            self.assertEqual(self.failure("verify", "x\n" + line + "\n").first_difference(), path)

    def test_nothing_is_guessed_from_other_steps(self):
        failure = self.failure("what-ran", VERIFY_STDERR)
        self.assertEqual((failure.manifest(), failure.first_difference(), failure.verifier_exit_code()),
                         (None, None, None))
