"""The perf bundle's verdict binding (R011, B13): snapshot, `core.inputs.perf_sha256`, `rigor grade --perf`,
and `rigor verify --expect-perf-sha`. Same shape as the witness binding (T037)."""

import os
import shutil
from types import SimpleNamespace

from rigor_lib import grade, perf_bundle, verdict_inputs
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, read_json, run_rigor
from tests.test_verdict_inputs import Fixture

FIXTURE = GATE_DIR / "tests" / "fixtures" / "perf" / "selftest"
PRODUCT = GATE_DIR.parent / "products" / "selftest" / "product.toml"
LEVELS = {"//core:core": "L3", "//util:util": "L2"}


class Snapshot(TempDirTestCase):
    def bundle(self, name="bundle"):
        target = self.tmp / name
        shutil.copytree(FIXTURE, target, symlinks=True)
        return target

    def snapshot(self, source, product="selftest", levels=None):
        destination = self.tmp / ("w%d" % len(list(self.tmp.glob("w*")))) / "inputs" / "perf"
        destination.parent.mkdir(parents=True)
        result = verdict_inputs.snapshot_perf(None if source is None else str(source), str(destination), product,
                                              LEVELS if levels is None else levels)
        return result, destination

    def core_sha256(self, perf_sha256):
        fixture = Fixture(str(self.tmp))
        fixture.file_hashes["perf_sha256"] = perf_sha256
        return fixture.core_sha256()

    def test_without_perf_it_is_null_and_nothing_is_written(self):
        (bundle, sha), destination = self.snapshot(None)
        self.assertEqual((bundle, sha), (None, None))
        self.assertFalse(destination.exists())
        fixture = Fixture(str(self.tmp))
        fixture.file_hashes["perf_sha256"] = None
        self.assertIsNone(fixture.inputs()["perf_sha256"])
        self.assertEqual(verdict_inputs.missing_inputs(fixture.inputs()), [])

    def test_the_copy_is_loaded_and_hashed(self):
        source = self.bundle()
        (bundle, sha), destination = self.snapshot(source)
        self.assertEqual(sha, perf_bundle.digest(perf_bundle.load(str(source))))
        self.assertEqual(sha, perf_bundle.digest(bundle))
        self.assertEqual(perf_bundle.load(str(destination)), bundle)
        self.assertEqual(sorted(str(p.relative_to(destination)) for p in destination.rglob("*")),
                         sorted(str(p.relative_to(source)) for p in source.rglob("*")))

    def test_the_grade_reads_only_the_snapshot(self):
        source = self.bundle()
        (bundle, sha), destination = self.snapshot(source)
        (source / "gen" / "core_add.c").write_text("/* swapped after the snapshot */\n")
        os.unlink(source / "perf.toml")
        self.assertEqual(perf_bundle.digest(perf_bundle.load(str(destination))), sha)
        self.assertEqual(perf_bundle.load(str(destination)), bundle)
        self.assertEqual(perf_bundle.digest(bundle), sha)

    def test_the_same_bundle_under_two_paths_gives_the_same_core(self):
        (_, first), _ = self.snapshot(self.bundle("one"))
        (_, second), _ = self.snapshot(self.bundle("elsewhere/two"))
        self.assertEqual(first, second)
        self.assertEqual(self.core_sha256(first), self.core_sha256(second))

    def test_the_bundle_changes_core_sha256_and_null_differs_from_any_bundle(self):
        (_, sha), _ = self.snapshot(self.bundle())
        other = self.bundle("other")
        (other / "gen" / "core_add.c").write_text("/* other */\n")
        (_, changed), _ = self.snapshot(other)
        self.assertEqual(len({self.core_sha256(None), self.core_sha256(sha), self.core_sha256(changed)}), 3)

    def assertRefused(self, source, needle, **kwargs):
        with self.assertRaises(InternalError) as caught:
            self.snapshot(source, **kwargs)
        self.assertIn(needle, str(caught.exception))

    def test_a_missing_bundle_is_an_error(self):
        self.assertRefused(self.tmp / "nope", "perf bundle")

    def test_symlinks_and_special_files_are_refused_by_the_copy(self):
        os.symlink(self.bundle(), self.tmp / "link")
        self.assertRefused(self.tmp / "link", "perf bundle")
        source = self.bundle("sym")
        os.symlink(source / "gen" / "core_add.c", source / "gen" / "alias.c")
        self.assertRefused(source, "perf bundle: symlink gen/alias.c")
        source = self.bundle("fifo")
        os.mkfifo(source / "gen" / "fifo")
        self.assertRefused(source, "perf bundle: special file gen/fifo")

    def test_format_defects_and_the_product_checks_are_errors(self):
        source = self.bundle()
        (source / "stray.c").write_text("x")
        self.assertRefused(source, "does not name: stray.c")
        self.assertRefused(self.bundle("p"), "not 'annas-c'", product="annas-c")
        self.assertRefused(self.bundle("q"), "not in the product policy", levels={})
        self.assertRefused(self.bundle("r"), "below L3", levels={"//core:core": "L2"})
        bad = self.bundle("s")
        (bad / "perf.toml").write_text('version = 1\nproduct = 1\n')
        self.assertRefused(bad, "perf.toml")


class GradePerfOption(TempDirTestCase):
    """`rigor grade --perf` end to end up to `clone` (the product repo does not exist, so `clone` is an
    internal error and the FAIL verdict still records the bound inputs)."""

    def grade(self, *extra):
        task = self.tmp / "task.toml"
        task.write_text('id = "t"\nallowed = ["**"]\n')
        self.work = self.tmp / "work"
        self.out = self.tmp / "verdict.json"
        return run_rigor(["grade", "--product-repo", self.tmp / "no-repo", "--base", "main", "--head", "main",
                          "--task", task, "--product", PRODUCT, "--work", self.work, "--out", self.out,
                          "--allow-dirty-gate", *extra])

    def bundle(self):
        target = self.tmp / "bundle"
        shutil.copytree(FIXTURE, target, symlinks=True)
        return target

    def test_a_bundle_is_snapshotted_and_bound(self):
        source = self.bundle()
        outcome = self.grade("--perf", source)
        self.assertExit(outcome, 2)
        self.assertIn("clone", outcome.stderr)
        inputs = read_json(self.out)["core"]["inputs"]
        self.assertEqual(inputs["perf_sha256"], perf_bundle.digest(perf_bundle.load(str(source))))
        self.assertEqual(perf_bundle.digest(perf_bundle.load(str(self.work / "inputs" / "perf"))), inputs["perf_sha256"])
        self.assertIsNone(inputs["witness_sha256"])

    def test_without_perf_the_input_is_null(self):
        self.assertExit(self.grade(), 2)
        self.assertIsNone(read_json(self.out)["core"]["inputs"]["perf_sha256"])
        self.assertFalse((self.work / "inputs" / "perf").exists())

    def test_a_relative_bundle_path_is_made_absolute(self):
        args = SimpleNamespace(perf="bundle")
        grade.absolute_arguments(args)
        self.assertEqual(args.perf, os.path.abspath("bundle"))

    def test_a_bundle_for_another_product_is_exit_2_before_clone(self):
        source = self.bundle()
        text = (source / "perf.toml").read_text().replace('"selftest"', '"annas-c"')
        (source / "perf.toml").write_text(text)
        outcome = self.grade("--perf", source)
        self.assertExit(outcome, 2)
        self.assertIn("perf bundle is for product 'annas-c'", outcome.stderr)
        self.assertFalse(self.out.exists())
        self.assertFalse((self.work / "src").exists())
        self.assertEqual(os.listdir(self.work / "results"), [])

    def test_a_module_below_l3_is_exit_2_before_clone(self):
        source = self.bundle()
        (source / "perf.toml").write_text((source / "perf.toml").read_text().replace("//core:core", "//util:util"))
        outcome = self.grade("--perf", source)
        self.assertExit(outcome, 2)
        self.assertIn("below L3", outcome.stderr)
        self.assertFalse(self.out.exists())

    def test_a_symlink_in_the_bundle_is_exit_2_before_clone(self):
        source = self.bundle()
        os.symlink(source / "gen" / "core_add.c", source / "gen" / "alias.c")
        outcome = self.grade("--perf", source)
        self.assertExit(outcome, 2)
        self.assertIn("perf bundle: symlink", outcome.stderr)
        self.assertFalse(self.out.exists())
