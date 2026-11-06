"""The witness bundle (P002, Q1): load, digest, check, overlay, and `gate/tools/witness.py`.

The bundle is gate-owned input, so every defect must be an InternalError (exit 2), never a pass.
"""

import os
import shutil
import subprocess
import sys
import unittest

from rigor_lib import witness_bundle as wb
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, Outcome, Repo, TempDirTestCase, base_env

FIXTURE = GATE_DIR / "tests" / "fixtures" / "witness" / "good"
TOOL = GATE_DIR / "tools" / "witness.py"
IMPL = {"//core:core": ["core/core.c"], "//util:util": ["util/util.c"]}
SHA = "0123456789abcdef0123456789abcdef01234567"


def manifest(product="canary", modules=None):
    modules = modules if modules is not None else {"//core:core": ("A001", SHA)}
    lines = ['product = "%s"' % product]
    for label, (origin, against) in modules.items():
        lines += ['[module."%s"]' % label, 'origin = "%s"' % origin, 'written_against = "%s"' % against]
    return "\n".join(lines) + "\n"


class BundleCase(TempDirTestCase):
    def copy(self, name="bundle"):
        target = self.tmp / name
        shutil.copytree(FIXTURE, target, symlinks=True)
        return target

    def make(self, text, files):
        self.made = getattr(self, "made", 0) + 1
        root = self.sub("made%d" % self.made)
        (root / "witness.toml").write_text(text, encoding="utf-8")
        (root / "files").mkdir()
        for rel, data in files.items():
            path = root / "files" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return root

    def assertLoadFails(self, root, needle=None):
        with self.assertRaises(InternalError) as caught:
            wb.load(str(root))
        if needle is not None:
            self.assertIn(needle, str(caught.exception))


class LoadGreen(BundleCase):
    def test_the_fixture_loads(self):
        bundle = wb.load(str(FIXTURE))
        self.assertEqual(bundle.product, "canary")
        self.assertEqual(sorted(bundle.modules), ["//core:core", "//util:util"])
        self.assertEqual(bundle.modules["//core:core"].origin, "A001")
        self.assertEqual(bundle.modules["//util:util"].written_against, "89abcdef0123456789abcdef0123456789abcdef")
        self.assertEqual([f.path for f in bundle.files], ["core/core.c", "util/util.c"])
        self.assertEqual(bundle.files[0].data, (FIXTURE / "files" / "core" / "core.c").read_bytes())

    def test_digest_is_the_canonical_list_of_manifest_then_files(self):
        bundle = wb.load(str(FIXTURE))
        entries = wb.digest_entries(bundle)
        self.assertEqual([e[0] for e in entries], ["witness.toml", "files/core/core.c", "files/util/util.c"])
        from rigor_lib import jsonio
        self.assertEqual(wb.digest(bundle), jsonio.sha256_hex(jsonio.canonical_dumps(entries)))

    def test_digest_does_not_depend_on_where_the_bundle_is(self):
        self.assertEqual(wb.digest(wb.load(str(FIXTURE))), wb.digest(wb.load(str(self.copy("elsewhere")))))

    def test_digest_is_stable_across_loads(self):
        self.assertEqual(wb.digest(wb.load(str(FIXTURE))), wb.digest(wb.load(str(FIXTURE))))


class DigestChanges(BundleCase):
    def setUp(self):
        super().setUp()
        self.root = self.copy()
        self.before = wb.digest(wb.load(str(self.root)))

    def assertChanged(self):
        self.assertNotEqual(wb.digest(wb.load(str(self.root))), self.before)

    def test_a_file_byte(self):
        path = self.root / "files" / "core" / "core.c"
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertChanged()

    def test_the_manifest(self):
        path = self.root / "witness.toml"
        path.write_text(path.read_text(encoding="utf-8").replace("A001", "A009"), encoding="utf-8")
        self.assertChanged()

    def test_a_rename(self):
        os.rename(self.root / "files" / "core" / "core.c", self.root / "files" / "core" / "core2.c")
        self.assertChanged()

    def test_an_added_file(self):
        (self.root / "files" / "core" / "extra.c").write_bytes(b"int x;\n")
        self.assertChanged()


class LoadDefects(BundleCase):
    def test_symlinked_file_is_refused(self):
        root = self.copy()
        os.symlink("core.c", root / "files" / "core" / "alias.c")
        self.assertLoadFails(root, "symlink")

    def test_symlink_replacing_a_file_is_refused(self):
        root = self.copy()
        target = self.tmp / "outside.c"
        target.write_bytes(b"int o;\n")
        os.unlink(root / "files" / "core" / "core.c")
        os.symlink(target, root / "files" / "core" / "core.c")
        self.assertLoadFails(root, "symlink")

    def test_symlinked_directory_is_refused(self):
        root = self.copy()
        os.symlink(self.sub("elsewhere"), root / "files" / "linked")
        self.assertLoadFails(root, "symlink")

    def test_symlinked_manifest_is_refused(self):
        root = self.copy()
        shutil.move(root / "witness.toml", self.tmp / "real.toml")
        os.symlink(self.tmp / "real.toml", root / "witness.toml")
        self.assertLoadFails(root)

    def test_symlinked_files_dir_is_refused(self):
        root = self.copy()
        shutil.move(root / "files", self.tmp / "real-files")
        os.symlink(self.tmp / "real-files", root / "files")
        self.assertLoadFails(root)

    def test_symlinked_bundle_root_is_refused(self):
        os.symlink(self.copy(), self.tmp / "link")
        self.assertLoadFails(self.tmp / "link")

    def test_fifo_is_refused(self):
        root = self.copy()
        os.mkfifo(root / "files" / "core" / "pipe")
        self.assertLoadFails(root, "special file")

    def test_empty_directory_is_refused(self):
        root = self.copy()
        (root / "files" / "core" / "empty").mkdir()
        self.assertLoadFails(root, "empty directory")

    def test_empty_files_dir_is_refused(self):
        root = self.make(manifest(), {})
        self.assertLoadFails(root, "empty directory")

    def test_non_utf8_name_is_refused(self):
        root = self.copy()
        with open(os.path.join(os.fsencode(root / "files" / "core"), b"bad\xff.c"), "wb") as handle:
            handle.write(b"x")
        self.assertLoadFails(root, "non-UTF-8")

    def test_extra_top_level_entry_is_refused(self):
        root = self.copy()
        (root / "README").write_text("x", encoding="utf-8")
        self.assertLoadFails(root, "exactly")

    def test_missing_files_dir_is_refused(self):
        root = self.copy()
        shutil.rmtree(root / "files")
        self.assertLoadFails(root, "exactly")

    def test_missing_manifest_is_refused(self):
        root = self.copy()
        os.unlink(root / "witness.toml")
        self.assertLoadFails(root, "exactly")

    def test_files_as_a_plain_file_is_refused(self):
        root = self.copy()
        shutil.rmtree(root / "files")
        (root / "files").write_bytes(b"x")
        self.assertLoadFails(root)

    def test_manifest_as_a_directory_is_refused(self):
        root = self.copy()
        os.unlink(root / "witness.toml")
        (root / "witness.toml").mkdir()
        self.assertLoadFails(root)

    def test_missing_bundle_is_refused(self):
        self.assertLoadFails(self.tmp / "nothing")

    def test_bundle_that_is_a_file_is_refused(self):
        (self.tmp / "file").write_bytes(b"x")
        self.assertLoadFails(self.tmp / "file")


class ManifestDefects(BundleCase):
    FILES = {"core/core.c": b"int c;\n"}

    def assertManifestFails(self, text):
        self.assertLoadFails(self.make(text, self.FILES))

    def test_the_good_shape_loads(self):
        wb.load(str(self.make(manifest(), self.FILES)))

    def test_not_toml(self):
        self.assertManifestFails("product = = x\n")

    def test_not_utf8(self):
        root = self.make(manifest(), self.FILES)
        (root / "witness.toml").write_bytes(b'product = "\xff"\n')
        self.assertLoadFails(root)

    def test_unknown_top_level_key(self):
        self.assertManifestFails(manifest() + 'signature = "x"\n')

    def test_missing_product(self):
        self.assertManifestFails(manifest().split("\n", 1)[1])

    def test_product_wrong_type_or_empty(self):
        for value in ("1", '""', '["canary"]'):
            self.assertManifestFails(manifest().replace('"canary"', value))

    def test_no_module_table(self):
        self.assertManifestFails('product = "canary"\n')

    def test_empty_module_table(self):
        self.assertManifestFails('product = "canary"\n[module]\n')

    def test_module_is_not_a_table(self):
        self.assertManifestFails('product = "canary"\n[module]\n"//core:core" = "x"\n')

    def test_bad_labels(self):
        for label in ("core:core", "//core", "//core:", "root//core:core", "//co re:core"):
            self.assertManifestFails(manifest(modules={label: ("A001", SHA)}))

    def test_missing_or_extra_module_keys(self):
        self.assertManifestFails('product = "canary"\n[module."//core:core"]\norigin = "A001"\n')
        self.assertManifestFails(manifest() + 'level = "L3"\n')

    def test_bad_origin(self):
        self.assertManifestFails(manifest(modules={"//core:core": ("", SHA)}))
        self.assertManifestFails(manifest().replace('origin = "A001"', "origin = 1"))

    def test_bad_written_against(self):
        for value in ("abc", SHA.upper(), SHA + "0", "g" * 40, ""):
            self.assertManifestFails(manifest(modules={"//core:core": ("A001", value)}))


class Check(BundleCase):
    def test_the_fixture_checks(self):
        owned = wb.check(wb.load(str(FIXTURE)), "canary", IMPL)
        self.assertEqual(owned, {"//core:core": ["core/core.c"], "//util:util": ["util/util.c"]})

    def test_globs_may_cover_several_files(self):
        root = self.make(manifest(), {"core/a.c": b"a", "core/sub/b.c": b"b"})
        owned = wb.check(wb.load(str(root)), "canary", {"//core:core": ["core/**"]})
        self.assertEqual(owned, {"//core:core": ["core/a.c", "core/sub/b.c"]})

    def assertCheckFails(self, bundle, product, impl, needle):
        with self.assertRaises(InternalError) as caught:
            wb.check(bundle, product, impl)
        self.assertIn(needle, str(caught.exception))

    def test_other_product(self):
        self.assertCheckFails(wb.load(str(FIXTURE)), "annas-c", IMPL, "product")

    def test_file_outside_every_impl_path(self):
        root = self.copy()
        (root / "files" / "core" / "core.h").write_bytes(b"int h;\n")
        self.assertCheckFails(wb.load(str(root)), "canary", IMPL, "0 modules")

    def test_file_in_two_modules_impl_paths(self):
        impl = dict(IMPL, **{"//util:util": ["util/util.c", "core/core.c"]})
        self.assertCheckFails(wb.load(str(FIXTURE)), "canary", impl, "2 modules")

    def test_file_of_a_module_the_bundle_does_not_list(self):
        root = self.make(manifest(), {"core/core.c": b"c", "util/util.c": b"u"})
        self.assertCheckFails(wb.load(str(root)), "canary", IMPL, "does not list")

    def test_listed_module_without_impl_paths(self):
        self.assertCheckFails(wb.load(str(FIXTURE)), "canary", {"//core:core": ["core/core.c"]}, "without impl")

    def test_listed_module_without_files(self):
        root = self.make(manifest(modules={"//core:core": ("A001", SHA), "//util:util": ("A002", SHA)}),
                         {"core/core.c": b"c"})
        self.assertCheckFails(wb.load(str(root)), "canary", IMPL, "no files")

    def test_malformed_impl_maps(self):
        bundle = wb.load(str(FIXTURE))
        for impl in ([], {"//core:core": "core/core.c", "//util:util": ["util/util.c"]},
                     dict(IMPL, **{"//core:core": []}), dict(IMPL, **{"//core:core": [1]}),
                     dict(IMPL, **{"//core:core": ["../core.c"]}), dict(IMPL, **{"core": ["core/core.c"]})):
            with self.assertRaises(InternalError):
                wb.check(bundle, "canary", impl)


HEAD = ["core/BUCK", "core/core.c", "core/core.h", "core/core_test.c",
        "util/BUCK", "util/util.c", "util/util.h", "util/util_core_test.c", "util/util_test.c"]


class Overlay(unittest.TestCase):
    def setUp(self):
        self.bundle = wb.load(str(FIXTURE))

    def test_a_module_in_scope_is_replaced(self):
        kept, files = wb.overlay(HEAD, self.bundle, {"//core:core": ["core/core.c"]})
        self.assertEqual(kept, [p for p in HEAD if p != "core/core.c"])
        self.assertEqual([f.path for f in files], ["core/core.c"])
        self.assertEqual(files[0].data, self.bundle.files[0].data)

    def test_bundle_modules_outside_scope_are_not_written(self):
        kept, files = wb.overlay(HEAD, self.bundle, {})
        self.assertEqual((kept, files), (HEAD, []))

    def test_a_module_in_scope_without_bundle_entry_keeps_its_head_files(self):
        kept, files = wb.overlay(HEAD, self.bundle, {"//other:other": ["other/x.c"], "//core:core": ["core/core.c"]})
        self.assertEqual([f.path for f in files], ["core/core.c"])
        self.assertNotIn("core/core.c", kept)

    def test_both_modules(self):
        kept, files = wb.overlay(HEAD, self.bundle, IMPL)
        self.assertEqual(kept, [p for p in HEAD if p not in ("core/core.c", "util/util.c")])
        self.assertEqual([f.path for f in files], ["core/core.c", "util/util.c"])

    def test_head_files_matching_the_glob_but_absent_from_the_bundle_are_dropped(self):
        kept, files = wb.overlay(HEAD + ["core/extra.c"], self.bundle, {"//core:core": ["core/*.c"]})
        self.assertNotIn("core/extra.c", kept)
        self.assertNotIn("core/core_test.c", kept)  # the glob is the policy's: it owns what it matches
        self.assertEqual([f.path for f in files], ["core/core.c"])

    def test_a_listed_module_with_no_matching_file_is_an_error(self):
        with self.assertRaises(InternalError):
            wb.overlay(HEAD, self.bundle, {"//core:core": ["core/other.c"]})

    def test_a_file_that_is_also_a_directory_is_an_error(self):
        with self.assertRaises(InternalError):
            wb.overlay(HEAD + ["core/core.c/x"], self.bundle, {"//core:core": ["core/core.c"]})

    def test_bad_head_paths_are_errors(self):
        for head in (["../x"], ["/abs"], [b"core/core.c"], ["a", "a"], "core/core.c"):
            with self.assertRaises(InternalError):
                wb.overlay(head, self.bundle, {})


def run_tool(args):
    argv = [sys.executable, "-I", "-B", str(TOOL)] + [str(a) for a in args]
    done = subprocess.run(argv, env=base_env(), capture_output=True, text=True, timeout=120)
    return Outcome(done.returncode, done.stdout, done.stderr)


class WitnessTool(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp / "repo")
        for rel in HEAD:
            source = GATE_DIR.parent / "canaries" / "_base" / "product" / rel
            self.repo.write(rel, source.read_bytes())
        self.commit = self.repo.commit("base")
        self.out = self.tmp / "bundle"

    def from_commit(self, *modules, out=None):
        args = ["from-commit", "--repo", self.repo.root, "--commit", "HEAD"]
        for label, patterns in modules:
            args += ["--module", label, "--paths"] + list(patterns)
        return run_tool(args + ["--product", "canary", "--out", out or self.out])

    def test_from_commit_digest_check(self):
        made = self.from_commit(("//core:core", ["core/core.c"]))
        self.assertExit(made, 0)
        bundle = wb.load(str(self.out))
        self.assertEqual([f.path for f in bundle.files], ["core/core.c"])
        self.assertEqual(bundle.files[0].data, self.repo.git("show", "HEAD:core/core.c").encode() + b"\n")
        self.assertEqual(bundle.modules["//core:core"].written_against, self.commit)
        self.assertEqual(bundle.modules["//core:core"].origin, "from-commit")
        first, second = run_tool(["digest", self.out]), run_tool(["digest", self.out])
        self.assertExit(first, 0)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stdout.strip(), wb.digest(bundle))
        self.assertIn(wb.digest(bundle), made.stdout)
        self.assertExit(run_tool(["check", self.out, "--product", "canary", "--impl", "//core:core=core/core.c"]), 0)

    def test_check_fails_after_a_symlink_is_added(self):
        self.assertExit(self.from_commit(("//core:core", ["core/core.c"])), 0)
        os.symlink(self.repo.root / "core" / "core.h", self.out / "files" / "core" / "core.h")
        outcome = run_tool(["check", self.out, "--product", "canary", "--impl", "//core:core=core/core.c"])
        self.assertExit(outcome, 2)
        self.assertIn("symlink", outcome.stderr)
        self.assertExit(run_tool(["digest", self.out]), 2)

    def test_two_modules_and_globs(self):
        self.assertExit(self.from_commit(("//core:core", ["core/core.c"]), ("//util:util", ["util/util.c"])), 0)
        self.assertEqual([f.path for f in wb.load(str(self.out)).files], ["core/core.c", "util/util.c"])
        self.assertExit(run_tool(["check", self.out, "--product", "canary", "--impl",
                                  "//core:core=core/core.c", "//util:util=util/util.c"]), 0)

    def assertRefused(self, outcome):
        self.assertExit(outcome, 2)
        self.assertFalse(os.path.lexists(self.out))
        self.assertEqual([p for p in os.listdir(self.tmp) if p.startswith(".witness-")], [])

    def test_a_module_with_no_files_is_refused(self):
        self.assertRefused(self.from_commit(("//core:core", ["core/nothing.c"])))

    def test_a_path_in_two_modules_is_refused(self):
        self.assertRefused(self.from_commit(("//core:core", ["core/core.c"]), ("//util:util", ["core/*.c"])))

    def test_a_symlink_in_the_commit_is_refused(self):
        self.repo.symlink("core/link.c", "core.c")
        self.repo.commit("link")
        self.assertRefused(self.from_commit(("//core:core", ["core/*.c"])))

    def test_existing_output_is_refused(self):
        self.out.mkdir()
        self.assertExit(self.from_commit(("//core:core", ["core/core.c"])), 2)
        self.assertEqual(os.listdir(self.out), [])

    def test_bad_arguments_are_exit_2(self):
        base = ["from-commit", "--repo", self.repo.root, "--commit", "HEAD", "--product", "canary", "--out", self.out]
        for extra in (["--paths", "core/core.c"],
                      ["--paths", "core/core.c", "--module", "//core:core"],
                      ["--module", "//core:core", "--module", "//util:util", "--paths", "x"],
                      ["--module", "core", "--paths", "core/core.c"],
                      ["--module", "//core:core", "--paths", "../core.c"]):
            self.assertRefused(run_tool(base + extra))
        self.assertRefused(run_tool(["from-commit", "--repo", self.repo.root, "--commit", "no-such-rev",
                                     "--module", "//core:core", "--paths", "core/core.c",
                                     "--product", "canary", "--out", self.out]))

    def test_check_refusals(self):
        self.assertExit(self.from_commit(("//core:core", ["core/core.c"])), 0)
        for args in (["--product", "other", "--impl", "//core:core=core/core.c"],
                     ["--product", "canary", "--impl", "//core:core"],
                     ["--product", "canary", "--impl", "//core:core=core/core.h"],
                     ["--product", "canary", "--impl", "//util:util=core/core.c"]):
            self.assertExit(run_tool(["check", self.out] + args), 2)
        self.assertExit(run_tool(["digest", self.tmp / "missing"]), 2)


if __name__ == "__main__":
    unittest.main()
