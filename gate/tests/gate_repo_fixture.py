"""A throwaway gate repository for `rigor verify` tests (U30): `verify` recomputes the gate order and the toolchain
pins from the commit a verdict names, so a hand-built verdict needs a real commit holding those files."""

import os

from rigor_lib import jsonio, verdict
from tests import test_verdict_inputs
from tests.helpers import Repo, TempDirTestCase, run_rigor


def gate_repo(fixture, order=("a",)):
    """Commit `gate/order.txt` (the ids in `order`), `toolchains/BUCK` and `tools/buck2.version` matching `fixture`
    into `<fixture.root>/gate-repo`; point `fixture.gate_sha` and its `order_sha256` at them. Returns the repo path."""
    root = os.path.join(fixture.root, "gate-repo")
    repo = Repo(root)
    order_bytes = "".join(gate_id + "\n" for gate_id in order).encode("ascii")
    repo.write("gate/order.txt", order_bytes)
    repo.write("toolchains/BUCK", test_verdict_inputs.BUCK_TEXT % (fixture.llvm, fixture.sysroot))
    repo.write("tools/buck2.version", fixture.buck2 + "\n")
    fixture.gate_sha = repo.commit("gate")
    fixture.file_hashes["order_sha256"] = jsonio.sha256_hex(order_bytes)
    return root


class VerdictCase(TempDirTestCase):
    """A hand-built verdict over `Fixture` inputs and a gate repo it is consistent with, and `rigor verify` on it."""

    def setUp(self):
        super().setUp()
        self.verdict = self.tmp / "verdict.json"
        self.fixture = test_verdict_inputs.Fixture(str(self.tmp))
        self.gate_repo = gate_repo(self.fixture)

    def make(self, mutate_core=None):
        core = verdict.build_core(["a"], {"a": {"status": "PASS", "findings": []}})
        core["uncached"] = self.fixture.uncached
        core["approvals"] = verdict.approvals_in_force([])
        core["inputs"] = self.fixture.inputs()
        if mutate_core:
            mutate_core(core)
        document = {"core": core, "core_sha256": jsonio.sha256_hex(jsonio.canonical_dumps(core)), "metadata": {}}
        self.verdict.write_bytes(jsonio.canonical_dumps(document))

    def verify(self, *extra):
        return run_rigor(["verify", "--verdict", self.verdict, "--gate-repo", self.gate_repo,
                          "--expect-head", test_verdict_inputs.HEAD, *extra])

    def assertRejected(self, outcome, text):
        self.assertEqual(outcome.code, 1, outcome.stdout + outcome.stderr)
        self.assertIn(text, outcome.stdout)
