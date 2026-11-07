"""T021: the verdict core binds every input that decides it (unit level, no Buck2).

Each input is varied on its own and must change `core_sha256`; the files are snapshotted before use.
"""

import os
import pathlib
import shutil
import subprocess
from types import SimpleNamespace
from unittest import mock

from rigor_lib import grade_context, jsonio, verdict, verdict_inputs, witness_bundle
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, base_env

HEAD, BASE, MERGE_BASE, GATE = "a" * 40, "b" * 40, "c" * 40, "d" * 40
BUCK_TEXT = ('fetched_tree(\n    name = "llvm",\n    url = "u",\n    sha256 = "%s",\n    size_bytes = 1,\n)\n\n'
             'fetched_tree(\n    name = "sysroot",\n    url = "u",\n    sha256 = "%s",\n    size_bytes = 1,\n)\n')
LLVM, SYSROOT, BUCK2 = "1" * 64, "2" * 64, "3" * 64
FILE_HASHES = {key: jsonio.sha256_hex(key.encode()) for key in
               ("task_sha256", "product_toml_sha256", "policy_sha256", "expected_tests_sha256",
                "expected_tests_previous_sha256", "approvals_sha256", "allowed_signers_sha256", "order_sha256",
                "witness_sha256")}
WITNESS_FIXTURE = GATE_DIR / "tests" / "fixtures" / "witness" / "good"


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
        g = SimpleNamespace(tree=self.tree, work=self.root, gate_sha=self.gate_sha, gate_clean=self.gate_clean,
                            product=SimpleNamespace(name=self.name), args=SimpleNamespace(uncached=self.uncached, approvals=None),
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
                           ("product", ""), ("approvals_sha256", "short"), ("witness_sha256", "short"),
                           ("witness_sha256", "A" * 64)):
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


class WitnessSnapshot(TempDirTestCase):
    """T037: `--witness DIR` is copied once into <work>/inputs/witness, loaded from the copy, and hashed."""

    def bundle(self, name="bundle"):
        target = self.tmp / name
        shutil.copytree(WITNESS_FIXTURE, target, symlinks=True)
        return target

    def snapshot(self, source):
        destination = self.tmp / ("w%d" % len(list(self.tmp.glob("w*")))) / "inputs" / "witness"
        destination.parent.mkdir(parents=True)
        return verdict_inputs.snapshot_witness(None if source is None else str(source), str(destination)), \
            destination

    def core_sha256(self, witness_sha256):
        fixture = Fixture(str(self.tmp))
        fixture.file_hashes["witness_sha256"] = witness_sha256
        return fixture.core_sha256()

    def test_without_a_witness_it_is_null_and_nothing_is_written(self):
        (bundle, sha), destination = self.snapshot(None)
        self.assertEqual((bundle, sha), (None, None))
        self.assertFalse(destination.exists())
        fixture = Fixture(str(self.tmp))
        fixture.file_hashes["witness_sha256"] = None
        self.assertIsNone(fixture.inputs()["witness_sha256"])
        self.assertEqual(verdict_inputs.missing_inputs(fixture.inputs()), [])

    def test_the_copy_is_loaded_and_hashed(self):
        source = self.bundle()
        (bundle, sha), destination = self.snapshot(source)
        self.assertEqual(sha, witness_bundle.digest(witness_bundle.load(str(source))))
        self.assertEqual(sha, witness_bundle.digest(bundle))
        self.assertEqual(witness_bundle.load(str(destination)), bundle)
        self.assertEqual(sorted(str(p.relative_to(destination)) for p in destination.rglob("*")),
                         sorted(str(p.relative_to(source)) for p in source.rglob("*")))

    def test_changing_the_original_after_the_snapshot_changes_nothing(self):
        source = self.bundle()
        (bundle, sha), destination = self.snapshot(source)
        (source / "files" / "core" / "core.c").write_text("int core_add(int a, int b) { return 0; }\n")
        self.assertEqual(witness_bundle.digest(witness_bundle.load(str(destination))), sha)
        self.assertNotEqual(self.snapshot(source)[0][1], sha)

    def test_the_same_bundle_under_two_paths_gives_the_same_core(self):
        (_, first), _ = self.snapshot(self.bundle("one"))
        (_, second), _ = self.snapshot(self.bundle("elsewhere/two"))
        self.assertEqual(first, second)
        self.assertEqual(self.core_sha256(first), self.core_sha256(second))

    def test_the_witness_changes_core_sha256_and_null_differs_from_any_bundle(self):
        (_, sha), _ = self.snapshot(self.bundle())
        other = self.bundle("other")
        (other / "files" / "util" / "util.c").write_text("/* other witness */\n")
        (_, changed), _ = self.snapshot(other)
        digests = {self.core_sha256(None), self.core_sha256(sha), self.core_sha256(changed)}
        self.assertEqual(len(digests), 3)

    def assertRefused(self, source, needle):
        with self.assertRaises(InternalError) as caught:
            self.snapshot(source)
        self.assertIn(needle, str(caught.exception))

    def test_a_missing_bundle_is_an_error(self):
        self.assertRefused(self.tmp / "nope", "witness bundle")

    def test_a_symlinked_bundle_root_is_refused(self):
        os.symlink(self.bundle(), self.tmp / "link")
        self.assertRefused(self.tmp / "link", "symlink")

    def test_a_symlinked_file_is_refused(self):
        source = self.bundle()
        os.symlink(source / "files" / "core" / "core.c", source / "files" / "core" / "alias.c")
        self.assertRefused(source, "symlink files/core/alias.c")

    def test_a_symlinked_manifest_is_refused(self):
        source = self.bundle()
        os.rename(source / "witness.toml", self.tmp / "manifest.toml")
        os.symlink(self.tmp / "manifest.toml", source / "witness.toml")
        self.assertRefused(source, "symlink witness.toml")

    def test_a_symlinked_directory_is_refused(self):
        source = self.bundle()
        os.symlink(source / "files" / "core", source / "files" / "more")
        self.assertRefused(source, "symlink files/more")

    def test_a_fifo_is_refused(self):
        source = self.bundle()
        os.mkfifo(source / "files" / "core" / "pipe.c")
        self.assertRefused(source, "special file files/core/pipe.c")

    def test_format_defects_are_refused_by_the_loader_on_the_copy(self):
        empty = self.bundle("empty")
        (empty / "files" / "spare").mkdir()
        self.assertRefused(empty, "empty directory")
        extra = self.bundle("extra")
        (extra / "README").write_text("x\n")
        self.assertRefused(extra, "must hold exactly")
        bad = self.bundle("bad")
        (bad / "witness.toml").write_text("product = 1\n")
        self.assertRefused(bad, "witness.toml")


class PrepareWork(TempDirTestCase):
    def test_it_clears_the_witness_tree_and_work_after_stopping_both_daemons(self):
        for name in ("tree", grade_context.WITNESS_TREE, grade_context.WITNESS_WORK):
            (self.sub(name) / "stale").write_text("x")
        (self.sub("inputs/witness/files") / "old.c").write_text("x")
        with mock.patch.object(grade_context, "kill_daemon") as kill:
            grade_context.prepare_work(str(self.tmp))
        self.assertEqual([c.args for c in kill.call_args_list],
                         [(str(self.tmp / "tree"),), (str(self.tmp / "tree-witness"),)])
        for name in ("tree", "tree-witness", "witness", "inputs"):
            self.assertFalse((self.tmp / name).exists(), name)


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
