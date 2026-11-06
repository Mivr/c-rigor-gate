"""T021: the verdict core binds every input that decides it (unit level, no Buck2).

Each input is varied on its own and must change `core_sha256`; the files are snapshotted before use.
"""

import os
import pathlib
import subprocess
from types import SimpleNamespace

from rigor_lib import grade_context, jsonio, verdict, verdict_inputs
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, base_env

HEAD, BASE, MERGE_BASE, GATE = "a" * 40, "b" * 40, "c" * 40, "d" * 40
BUCK_TEXT = ('fetched_tree(\n    name = "llvm",\n    url = "u",\n    sha256 = "%s",\n    size_bytes = 1,\n)\n\n'
             'fetched_tree(\n    name = "sysroot",\n    url = "u",\n    sha256 = "%s",\n    size_bytes = 1,\n)\n')
LLVM, SYSROOT, BUCK2 = "1" * 64, "2" * 64, "3" * 64
FILE_HASHES = {key: jsonio.sha256_hex(key.encode()) for key in
               ("task_sha256", "product_toml_sha256", "policy_sha256", "expected_tests_sha256",
                "expected_tests_previous_sha256", "approvals_sha256", "allowed_signers_sha256", "order_sha256")}


class Fixture:
    """A fake grading: a tree with the toolchain files, and the gate results `build_inputs` reads."""

    def __init__(self, root):
        self.tree = os.path.join(root, "tree")
        self.root = root
        self.llvm, self.sysroot, self.buck2 = LLVM, SYSROOT, BUCK2
        self.buckconfig = "4" * 64
        self.commits = {"head": HEAD, "base": BASE, "merge_base": MERGE_BASE}
        self.gate_sha, self.gate_clean, self.name, self.uncached = GATE, True, "prod", False
        self.file_hashes = dict(FILE_HASHES)

    def grading(self):
        buck = (BUCK_TEXT % (self.llvm, self.sysroot)).encode()
        version = (self.buck2 + "\n").encode()
        for rel, data in (("toolchains/BUCK", buck), ("tools/buck2.version", version)):
            path = os.path.join(self.tree, "gate", rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
        manifest = [[".buckconfig", self.buckconfig],
                    ["gate/toolchains/BUCK", jsonio.sha256_hex(buck)],
                    ["gate/tools/buck2.version", jsonio.sha256_hex(version)]]
        documents = {"clone": {"metadata": dict(self.commits)}, "assemble": {"metadata": {"manifest": manifest}}}
        g = SimpleNamespace(tree=self.tree, gate_sha=self.gate_sha, gate_clean=self.gate_clean,
                            product=SimpleNamespace(name=self.name), args=SimpleNamespace(uncached=self.uncached),
                            inputs=dict(self.file_hashes))
        return g, documents

    def inputs(self):
        g, documents = self.grading()
        return verdict_inputs.build_inputs(g, documents)

    def core_sha256(self):
        order = ["clone"]
        core = verdict.build_core(order, {"clone": {"status": "PASS", "findings": []}})
        core["inputs"] = self.inputs()
        return jsonio.sha256_hex(jsonio.canonical_dumps(core))


def other_hash(value):
    return jsonio.sha256_hex(b"other" + value.encode())


class EveryInputChangesTheHash(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.fixture = Fixture(str(self.tmp))
        self.baseline = self.fixture.core_sha256()

    def changed(self, mutate):
        fixture = Fixture(str(self.tmp))
        mutate(fixture)
        return fixture.core_sha256()

    def test_determinism(self):
        self.assertEqual(Fixture(str(self.tmp)).core_sha256(), self.baseline)

    def test_inputs_have_exactly_the_documented_keys(self):
        self.assertEqual(set(self.fixture.inputs()), verdict_inputs.INPUT_KEYS)
        self.assertEqual(verdict_inputs.missing_inputs(self.fixture.inputs()), [])

    def test_every_single_input_changes_core_sha256(self):
        cases = {}
        for key in FILE_HASHES:
            cases[key] = lambda f, key=key: f.file_hashes.__setitem__(key, other_hash(key))
        for key, other in (("head", "e" * 40), ("base", "f" * 40), ("merge_base", "9" * 40)):
            cases[key] = lambda f, key=key, other=other: f.commits.__setitem__(key, other)
        cases["gate_sha"] = lambda f: setattr(f, "gate_sha", "e" * 40)
        cases["gate_clean"] = lambda f: setattr(f, "gate_clean", False)
        cases["product"] = lambda f: setattr(f, "name", "other")
        cases["uncached"] = lambda f: setattr(f, "uncached", True)
        cases["buckconfig_sha256"] = lambda f: setattr(f, "buckconfig", "5" * 64)
        cases["llvm_sha256"] = lambda f: setattr(f, "llvm", "6" * 64)
        cases["sysroot_sha256"] = lambda f: setattr(f, "sysroot", "7" * 64)
        cases["buck2_sha256"] = lambda f: setattr(f, "buck2", "8" * 64)
        self.assertEqual(set(cases) | {"toolchain_buck_sha256"}, verdict_inputs.INPUT_KEYS)
        seen = {self.baseline}
        for key, mutate in cases.items():
            digest = self.changed(mutate)
            self.assertNotIn(digest, seen, key)
            seen.add(digest)

    def test_the_toolchain_file_hash_changes_when_only_its_other_text_changes(self):
        fixture = Fixture(str(self.tmp))
        before = fixture.inputs()["toolchain_buck_sha256"]
        global BUCK_TEXT
        saved = BUCK_TEXT
        BUCK_TEXT = saved.replace('url = "u"', 'url = "v"')
        try:
            after = Fixture(str(self.tmp)).inputs()
        finally:
            BUCK_TEXT = saved
        self.assertNotEqual(before, after["toolchain_buck_sha256"])
        self.assertEqual((after["llvm_sha256"], after["sysroot_sha256"]), (LLVM, SYSROOT))

    def test_unknown_facts_are_null_and_reported_missing(self):
        g, documents = self.fixture.grading()
        inputs = verdict_inputs.build_inputs(g, {})
        self.assertIsNone(inputs["head"])
        self.assertIsNone(inputs["llvm_sha256"])
        self.assertIn("head", verdict_inputs.missing_inputs(inputs))
        self.assertIn("buckconfig_sha256", verdict_inputs.missing_inputs(inputs))

    def test_a_toolchain_file_changed_after_assembly_is_an_error(self):
        g, documents = self.fixture.grading()
        with open(os.path.join(g.tree, "gate", "toolchains", "BUCK"), "ab") as handle:
            handle.write(b"# edited\n")
        with self.assertRaises(InternalError):
            verdict_inputs.build_inputs(g, documents)

    def test_a_missing_pin_is_an_error(self):
        g, documents = self.fixture.grading()
        data = b'fetched_tree(\n    name = "llvm",\n    sha256 = "%s",\n)\n' % LLVM.encode()
        with open(os.path.join(g.tree, "gate", "toolchains", "BUCK"), "wb") as handle:
            handle.write(data)
        documents["assemble"]["metadata"]["manifest"][1][1] = jsonio.sha256_hex(data)
        with self.assertRaises(InternalError):
            verdict_inputs.build_inputs(g, documents)

    def test_malformed_values_are_reported(self):
        inputs = self.fixture.inputs()
        for key, value in (("head", "abc"), ("llvm_sha256", "xyz"), ("gate_clean", "yes"),
                           ("product", ""), ("approvals_sha256", "short")):
            broken = dict(inputs, **{key: value})
            self.assertEqual(verdict_inputs.missing_inputs(broken), [key], key)
        for key in verdict_inputs.OPTIONAL_KEYS:
            self.assertEqual(verdict_inputs.missing_inputs(dict(inputs, **{key: None})), [])


class Snapshot(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.product_dir = self.sub("src/products/p")
        self.write("task.toml", "id = 't'\n", directory=self.tmp)
        for name in verdict_inputs.PRODUCT_FILES:
            self.write(name, name + "\n")
        self.approvals = self.sub("approvals")
        (self.approvals / ("0" * 64 + ".json")).write_text("{}")
        self.work = str(self.sub("work"))

    def write(self, name, text, directory=None):
        (directory or self.product_dir).joinpath(name).write_text(text)

    def args(self, approvals=True, task="task.toml"):
        return SimpleNamespace(task=str(self.tmp / task), product=str(self.product_dir / "product.toml"),
                               approvals=str(self.approvals) if approvals else None)

    def snapshot(self, **kwargs):
        args = self.args(**kwargs)
        work = str(self.tmp / ("w%d" % len(list(self.tmp.glob("w*")))))
        os.makedirs(work)
        return args, verdict_inputs.snapshot_inputs(args, work)

    def test_hashes_are_of_the_bytes_and_args_point_at_the_copies(self):
        args, hashes = self.snapshot()
        self.assertEqual(hashes["task_sha256"], jsonio.sha256_hex(b"id = 't'\n"))
        self.assertEqual(hashes["policy_sha256"], jsonio.sha256_hex(b"policy.toml\n"))
        self.assertEqual(hashes["expected_tests_sha256"], jsonio.sha256_hex(b"expected-tests.json\n"))
        self.assertEqual(hashes["expected_tests_previous_sha256"],
                         jsonio.sha256_hex(b"expected-tests.previous.json\n"))
        self.assertEqual(hashes["product_toml_sha256"], jsonio.sha256_hex(b"product.toml\n"))
        for path in (args.task, args.product, args.approvals):
            self.assertIn("/inputs/", path)
            self.assertTrue(os.path.exists(path))
        self.assertEqual(pathlib.Path(os.path.dirname(args.product), "policy.toml").read_text(), "policy.toml\n")

    def test_changing_the_original_after_the_snapshot_changes_nothing(self):
        args, hashes = self.snapshot()
        (self.tmp / "task.toml").write_text("allowed = ['**']\n")
        self.write("policy.toml", "loosened\n")
        self.assertEqual(pathlib.Path(args.task).read_text(), "id = 't'\n")
        self.assertEqual(pathlib.Path(os.path.dirname(args.product), "policy.toml").read_text(), "policy.toml\n")

    def test_each_file_changes_its_own_hash_only(self):
        _, baseline = self.snapshot()
        edits = {"task_sha256": lambda: (self.tmp / "task.toml").write_text("x"),
                 "product_toml_sha256": lambda: self.write("product.toml", "x"),
                 "policy_sha256": lambda: self.write("policy.toml", "x"),
                 "expected_tests_sha256": lambda: self.write("expected-tests.json", "x"),
                 "expected_tests_previous_sha256": lambda: self.write("expected-tests.previous.json", "x"),
                 "approvals_sha256": lambda: (self.approvals / ("0" * 64 + ".json")).write_text("{ }")}
        for key, edit in edits.items():
            edit()
            _, changed = self.snapshot()
            differing = {k for k in baseline if baseline[k] != changed[k]}
            self.assertEqual(differing, {key})
            baseline = changed

    def test_approval_names_and_extra_entries_are_part_of_the_hash(self):
        _, before = self.snapshot()
        (self.approvals / ("0" * 64 + ".json")).rename(self.approvals / ("1" * 64 + ".json"))
        _, renamed = self.snapshot()
        self.assertNotEqual(before["approvals_sha256"], renamed["approvals_sha256"])
        os.symlink("elsewhere", self.approvals / "link")
        os.mkdir(self.approvals / "dir")
        _, extra = self.snapshot()
        self.assertNotEqual(renamed["approvals_sha256"], extra["approvals_sha256"])

    def test_missing_files_are_null_and_their_copies_stay_absent(self):
        os.unlink(self.product_dir / "expected-tests.previous.json")
        os.unlink(self.product_dir / "policy.toml")
        args, hashes = self.snapshot(approvals=False, task="nope.toml")
        self.assertIsNone(hashes["task_sha256"])
        self.assertIsNone(hashes["policy_sha256"])
        self.assertIsNone(hashes["expected_tests_previous_sha256"])
        self.assertIsNone(hashes["approvals_sha256"])
        self.assertIsNone(args.approvals)
        self.assertFalse(os.path.exists(args.task))

    def test_an_approvals_path_that_is_not_a_directory_stays_an_error(self):
        args = self.args()
        args.approvals = str(self.tmp / "task.toml")
        work = str(self.tmp / "wx")
        os.makedirs(work)
        self.assertIsNone(verdict_inputs.snapshot_inputs(args, work)["approvals_sha256"])
        self.assertFalse(os.path.exists(args.approvals))

    def test_symlinked_inputs_are_not_followed(self):
        os.unlink(self.product_dir / "policy.toml")
        os.symlink(self.tmp / "task.toml", self.product_dir / "policy.toml")
        _, hashes = self.snapshot()
        self.assertIsNone(hashes["policy_sha256"])


class DirtyGate(TempDirTestCase):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root)] + list(args), env=base_env(), check=True, capture_output=True)

    def setUp(self):
        super().setUp()
        self.root = self.sub("gate")
        self.git("init", "-q")
        (self.root / "f").write_text("1\n")
        self.git("add", "f")
        self.git("commit", "-q", "-m", "x")

    def test_clean(self):
        sha, clean = grade_context.gate_checkout_state(False, str(self.root))
        self.assertRegex(sha, "^[0-9a-f]{40}$")
        self.assertTrue(clean)

    def test_dirty_is_an_error_unless_allowed(self):
        (self.root / "f").write_text("2\n")
        with self.assertRaises(InternalError):
            grade_context.gate_checkout_state(False, str(self.root))
        sha, clean = grade_context.gate_checkout_state(True, str(self.root))
        self.assertFalse(clean)
        self.assertRegex(sha, "^[0-9a-f]{40}$")

    def test_untracked_files_do_not_make_it_dirty(self):
        (self.root / "new").write_text("x")
        self.assertTrue(grade_context.gate_checkout_state(False, str(self.root))[1])


class Constants(TempDirTestCase):
    def test_pass_constant_matches_the_verdict_module(self):
        self.assertEqual(verdict_inputs._PASS, verdict.STATUS_PASS)

    def test_order_parse_equals_order_read(self):
        path = str(GATE_DIR / "order.txt")
        self.assertEqual(verdict.parse_order(jsonio.read_bytes(path)), verdict.read_order(path))
