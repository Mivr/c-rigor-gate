"""A throwaway gate repository and product directory for `rigor verify` tests (U30): `verify` recomputes the gate
order, the toolchain pins and the generated `.buckconfig` from the commit a verdict names, and the product
configuration from the product directory, so a hand-built verdict needs real sources for them."""

import os

from rigor_lib import grade_tree, jsonio, verdict, verdict_inputs
from tests import test_verdict_inputs
from tests.helpers import GATE_DIR, Repo, TempDirTestCase, run_rigor

GATE_BUCKCONFIG = (GATE_DIR.parent / ".buckconfig").read_bytes()


def gate_repo(fixture, order=("a",), product_dir=None, product_files=None):
    """Commit `gate/order.txt` (the ids in `order`), `toolchains/BUCK`, `tools/buck2.version` and `.buckconfig`
    matching `fixture` into `<fixture.root>/gate-repo`, plus `product_files` ({name: bytes}) under `product_dir`;
    point `fixture.gate_sha`, its `order_sha256` and its `buckconfig` at them. Returns the repo path."""
    root = os.path.join(fixture.root, "gate-repo")
    repo = Repo(root)
    order_bytes = "".join(gate_id + "\n" for gate_id in order).encode("ascii")
    repo.write("gate/order.txt", order_bytes)
    repo.write("toolchains/BUCK", test_verdict_inputs.BUCK_TEXT % (fixture.llvm, fixture.sysroot))
    repo.write("tools/buck2.version", fixture.buck2 + "\n")
    repo.write(".buckconfig", GATE_BUCKCONFIG)
    for name, data in (product_files or {}).items():
        repo.write("%s/%s" % (product_dir, name), data)
    fixture.gate_sha = repo.commit("gate")
    fixture.file_hashes["order_sha256"] = jsonio.sha256_hex(order_bytes)
    fixture.buckconfig = jsonio.sha256_hex(grade_tree.generated_buckconfig(GATE_BUCKCONFIG))
    return root


def default_product_files():
    """Every product configuration file the grade reads, with distinct contents."""
    return {name: ("%s\n" % name).encode("ascii") for name in verdict_inputs.PRODUCT_FILE_KEYS}


class VerdictCase(TempDirTestCase):
    """A hand-built verdict over `Fixture` inputs, a gate repo and a product directory (outside the gate checkout,
    so `--product-dir`) it is consistent with, and `rigor verify` on it. `self.product_files` decides the product
    configuration bindings: a name left out is an absent file (a null binding)."""

    def setUp(self):
        super().setUp()
        self.verdict = self.tmp / "verdict.json"
        self.fixture = test_verdict_inputs.Fixture(str(self.tmp))
        self.gate_repo = gate_repo(self.fixture)
        self.product = self.sub("product")
        self.product_files = default_product_files()

    def sync_product(self):
        for name, key in verdict_inputs.PRODUCT_FILE_KEYS.items():
            path = self.product / name
            if path.exists():
                path.unlink()
            data = self.product_files.get(name)
            if data is not None:
                path.write_bytes(data)
            self.fixture.file_hashes[key] = None if data is None else jsonio.sha256_hex(data)

    def make(self, mutate_core=None):
        self.sync_product()
        core = verdict.build_core(["a"], {"a": {"status": "PASS", "findings": []}})
        core["uncached"] = self.fixture.uncached
        core["approvals"] = verdict.approvals_in_force([])
        core["inputs"] = self.fixture.inputs()
        if mutate_core:
            mutate_core(core)
        self.write(core)

    def write(self, core, core_sha256=None):
        document = {"core": core, "core_sha256": core_sha256 or jsonio.sha256_hex(jsonio.canonical_dumps(core)),
                    "metadata": {}}
        self.verdict.write_bytes(jsonio.canonical_dumps(document))

    def verify(self, *extra, product_dir=True):
        argv = ["verify", "--verdict", self.verdict, "--gate-repo", self.gate_repo,
                "--expect-head", test_verdict_inputs.HEAD, "--expect-gate", self.fixture.gate_sha]
        if product_dir:
            argv += ["--product-dir", self.product]
        return run_rigor(argv + list(extra))

    def assertRejected(self, outcome, text):
        self.assertEqual(outcome.code, 1, outcome.stdout + outcome.stderr)
        self.assertIn(text, outcome.stdout)
