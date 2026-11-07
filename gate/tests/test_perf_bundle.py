"""The perf bundle (R011, B13): load, validate, digest, check, `gate/tools/perf.py`.

The bundle is gate-owned input, so every defect must be an InternalError (exit 2), never a pass.
"""

import os
import shutil
import subprocess
import sys

from rigor_lib import perf_bundle as pb
from rigor_lib import witness_bundle
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, base_env

FIXTURE = GATE_DIR / "tests" / "fixtures" / "perf" / "selftest"
TOOL = GATE_DIR / "tools" / "perf.py"
PRODUCT = GATE_DIR.parent / "products" / "selftest" / "product.toml"
LEVELS = {"//core:core": "L3", "//util:util": "L2", "//deep:deep": "L5"}


def manifest(**override):
    target = {"id": '"t-1"', "module": '"//core:core"', "srcs": '["gen/a.c"]', "sizes": "[1000, 4000]",
              "seed": "1", "class": '"linear"'}
    target.update(override)
    top = {"version": "1", "product": '"selftest"'}
    lines = ["%s = %s" % item for item in top.items()] + ["[[target]]"]
    lines += ["%s = %s" % item for item in target.items() if item[1] is not None]
    return "\n".join(lines) + "\n"


class BundleCase(TempDirTestCase):
    def copy(self, name="bundle"):
        target = self.tmp / name
        shutil.copytree(FIXTURE, target, symlinks=True)
        return target

    def make(self, text, files=("gen/a.c",)):
        self.made = getattr(self, "made", 0) + 1
        root = self.sub("made%d" % self.made)
        (root / "perf.toml").write_text(text, encoding="utf-8")
        for name in files:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text("/* " + name + " */\n")
        return root

    def assertRejected(self, root, needle):
        with self.assertRaises(InternalError) as caught:
            pb.load(str(root))
        self.assertIn(needle, str(caught.exception))


class Valid(BundleCase):
    def test_the_fixture_loads_and_checks(self):
        bundle = pb.load(str(FIXTURE))
        self.assertEqual(bundle.product, "selftest")
        (target,) = bundle.targets
        self.assertEqual((target.id, target.module, target.srcs, target.sizes, target.seed, target.cost_class),
                         ("core-add-linear", "//core:core", ("gen/core_add.c",), (1000, 4000), 1, "linear"))
        self.assertEqual([f.path for f in bundle.files], ["gen/core_add.c"])
        pb.check(bundle, "selftest", LEVELS)

    def test_nlogn_and_a_larger_k_and_shared_sources(self):
        text = manifest(**{"class": '"nlogn"', "sizes": "[10, 80]"}) + (
            '[[target]]\nid = "t-2"\nmodule = "//deep:deep"\nsrcs = ["gen/a.c"]\nsizes = [3, 6]\nseed = 0\nclass = "linear"\n')
        bundle = pb.load(str(self.make(text)))
        self.assertEqual([t.id for t in bundle.targets], ["t-1", "t-2"])

    def test_digest_is_the_witness_scheme_over_manifest_and_sources(self):
        bundle = pb.load(str(FIXTURE))
        entries = [["perf.toml", witness_bundle.jsonio.sha256_hex((FIXTURE / "perf.toml").read_bytes())],
                   ["gen/core_add.c", witness_bundle.jsonio.sha256_hex((FIXTURE / "gen" / "core_add.c").read_bytes())]]
        self.assertEqual(pb.digest_entries(bundle), entries)
        self.assertEqual(pb.digest(bundle), witness_bundle.entries_digest(entries))

    def test_digest_is_stable_and_independent_of_the_location(self):
        first, second = pb.digest(pb.load(str(self.copy("one")))), pb.digest(pb.load(str(self.copy("a/two"))))
        self.assertEqual(first, second)
        self.assertEqual(first, pb.digest(pb.load(str(FIXTURE))))
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_any_byte_of_any_file_changes_the_digest(self):
        base = pb.digest(pb.load(str(FIXTURE)))
        seen = {base}
        for name in ("perf.toml", "gen/core_add.c"):
            data = (FIXTURE / name).read_bytes()
            for index in (0, len(data) // 2, len(data) - 1):
                root = self.copy("c%d" % len(seen))
                changed = bytearray(data)
                changed[index] ^= 0x01 if name != "perf.toml" else 0x00
                if name == "perf.toml":
                    changed = bytearray(data[:index] + data[index:index + 1] + b" " + data[index + 1:])
                (root / name).write_bytes(bytes(changed))
                try:
                    seen.add(pb.digest(pb.load(str(root))))
                except InternalError:
                    # a manifest edit that no longer parses is a rejection, not a digest
                    seen.add(name + str(index))
        self.assertEqual(len(seen), 7)

    def test_a_renamed_source_changes_the_digest(self):
        root = self.copy()
        os.rename(root / "gen" / "core_add.c", root / "gen" / "other.c")
        text = (root / "perf.toml").read_text().replace("core_add.c", "other.c")
        (root / "perf.toml").write_text(text)
        self.assertNotEqual(pb.digest(pb.load(str(root))), pb.digest(pb.load(str(FIXTURE))))


class Rejected(BundleCase):
    def test_unknown_and_missing_keys(self):
        self.assertRejected(self.make(manifest() + "extra = 1\n"), "exactly the keys")
        self.assertRejected(self.make(manifest(seed=None)), "exactly the keys")
        self.assertRejected(self.make(manifest().replace("version = 1\n", "")), "exactly the keys")
        self.assertRejected(self.make('version = 1\nproduct = "p"\nfoo = 1\n[[target]]\n'), "exactly the keys")

    def test_bad_version_product_and_empty_targets(self):
        self.assertRejected(self.make(manifest().replace("version = 1", "version = 2")), "version must be 1")
        self.assertRejected(self.make(manifest().replace("version = 1", 'version = "1"')), "version must be an integer")
        self.assertRejected(self.make(manifest().replace('"selftest"', '""')), "product")
        self.assertRejected(self.make('version = 1\nproduct = "p"\ntarget = []\n'), "at least one target")

    def test_not_toml_and_not_utf8(self):
        self.assertRejected(self.make("version = [\n"), "not valid")
        root = self.make(manifest())
        (root / "perf.toml").write_bytes(b"\xff\xfe")
        self.assertRejected(root, "not valid")

    def test_missing_manifest(self):
        root = self.make(manifest())
        os.unlink(root / "perf.toml")
        self.assertRejected(root, "missing perf.toml")

    def test_bad_ids(self):
        for ident in ('"Upper"', '"has_underscore"', '""', '"sp ace"', "5"):
            self.assertRejected(self.make(manifest(id=ident)), "id")

    def test_duplicate_ids(self):
        text = manifest() + '[[target]]\nid = "t-1"\nmodule = "//core:core"\nsrcs = ["gen/a.c"]\nsizes = [1, 2]\nseed = 1\nclass = "linear"\n'
        self.assertRejected(self.make(text), "duplicate target ids")

    def test_bad_modules(self):
        for module in ('"core"', '"//core"', '""', "1"):
            self.assertRejected(self.make(manifest(module=module)), "module")

    def test_bad_sizes(self):
        for sizes in ("[1000]", "[1, 2, 4]", "[1000, 1500]", "[1000, 1000]", "[4000, 1000]", "[0, 10]", "[-1, -2]",
                      '["a", "b"]', "[1.0, 4.0]", "[true, 4]", "[1000, 4001]", "1000"):
            self.assertRejected(self.make(manifest(sizes=sizes)), "sizes")

    def test_bad_class(self):
        for cost_class in ('"quadratic"', '"Linear"', '""', "1"):
            self.assertRejected(self.make(manifest(**{"class": cost_class})), "class")

    def test_bad_seed(self):
        for seed in ('"1"', "-1", "1.5", "true", str(1 << 64)):
            self.assertRejected(self.make(manifest(seed=seed)), "seed")

    def test_bad_srcs(self):
        for srcs, needle in (("[]", "srcs"), ('"gen/a.c"', "srcs"), ("[1]", "srcs"), ('["gen/a.c", "gen/a.c"]', "duplicates"),
                             ('["/etc/passwd"]', "absolute"), ('["../a.c"]', "dot segment"),
                             ('["gen/../a.c"]', "dot segment"), ('["./a.c"]', "dot segment"),
                             ('["gen//a.c"]', "empty path segment"), ('[""]', "empty path"),
                             ('["perf.toml"]', "may not be")):
            self.assertRejected(self.make(manifest(srcs=srcs), files=()), needle)

    def test_a_named_file_that_is_missing(self):
        self.assertRejected(self.make(manifest(), files=()), "missing files: gen/a.c")

    def test_a_file_the_manifest_does_not_name(self):
        self.assertRejected(self.make(manifest(), files=("gen/a.c", "gen/b.c")), "does not name: gen/b.c")
        self.assertRejected(self.make(manifest(), files=("gen/a.c", "README")), "does not name: README")

    def test_an_empty_directory(self):
        root = self.make(manifest())
        (root / "gen" / "empty").mkdir()
        self.assertRejected(root, "empty directory")

    def test_symlinks(self):
        root = self.make(manifest())
        os.symlink(root / "gen" / "a.c", root / "gen" / "alias.c")
        self.assertRejected(root, "symlink gen/alias.c")
        root = self.make(manifest())
        os.rename(root / "gen" / "a.c", self.tmp / "outside.c")
        os.symlink(self.tmp / "outside.c", root / "gen" / "a.c")
        self.assertRejected(root, "symlink gen/a.c")
        root = self.make(manifest())
        os.rename(root / "perf.toml", self.tmp / "manifest.toml")
        os.symlink(self.tmp / "manifest.toml", root / "perf.toml")
        self.assertRejected(root, "symlink perf.toml")
        root = self.make(manifest())
        os.symlink(self.tmp, root / "dirlink")
        self.assertRejected(root, "symlink dirlink")

    def test_a_symlinked_bundle_root_or_a_missing_one(self):
        os.symlink(self.copy(), self.tmp / "link")
        self.assertRejected(self.tmp / "link", "not a directory")
        self.assertRejected(self.tmp / "nope", "cannot stat")

    def test_a_special_file(self):
        root = self.make(manifest())
        os.mkfifo(root / "gen" / "fifo")
        self.assertRejected(root, "special file gen/fifo")

    def test_a_non_utf8_name(self):
        root = self.make(manifest())
        with open(os.path.join(os.fsencode(root), b"gen", b"bad\xff.c"), "wb") as handle:
            handle.write(b"x")
        self.assertRejected(root, "non-UTF-8")


class AgainstTheProduct(BundleCase):
    def check(self, text=None, product="selftest", levels=None):
        bundle = pb.load(str(self.make(text) if text else FIXTURE))
        pb.check(bundle, product, LEVELS if levels is None else levels)

    def test_a_good_bundle_passes(self):
        self.check()
        self.check(manifest(module='"//deep:deep"'))

    def test_another_product(self):
        with self.assertRaises(InternalError) as caught:
            self.check(product="annas-c")
        self.assertIn("not 'annas-c'", str(caught.exception))

    def test_a_module_not_in_the_policy(self):
        with self.assertRaises(InternalError) as caught:
            self.check(manifest(module='"//core:nope"'))
        self.assertIn("not in the product policy", str(caught.exception))

    def test_a_module_below_l3(self):
        with self.assertRaises(InternalError) as caught:
            self.check(manifest(module='"//util:util"'))
        self.assertIn("below L3", str(caught.exception))
        with self.assertRaises(InternalError):
            self.check(levels={"//core:core": "L1"})
        self.check(levels={"//core:core": "L4"})


class Tool(BundleCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, "-I", "-B", str(TOOL), *args], capture_output=True, text=True,
                              env=base_env(), check=False)

    def test_check_prints_ok_and_the_digest(self):
        done = self.run_tool("check", str(FIXTURE), "--product", str(PRODUCT))
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "ok " + pb.digest(pb.load(str(FIXTURE)))), done.stderr)

    def test_digest_prints_the_digest(self):
        done = self.run_tool("digest", str(FIXTURE))
        self.assertEqual((done.returncode, done.stdout.strip()), (0, pb.digest(pb.load(str(FIXTURE)))))

    def test_a_defect_is_exit_2(self):
        root = self.copy()
        (root / "extra.c").write_text("x")
        done = self.run_tool("check", str(root), "--product", str(PRODUCT))
        self.assertEqual(done.returncode, 2)
        self.assertIn("does not name: extra.c", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_a_module_outside_the_policy_is_exit_2(self):
        root = self.make(manifest(module='"//util:util"'))
        done = self.run_tool("check", str(root), "--product", str(PRODUCT))
        self.assertEqual(done.returncode, 2)
        self.assertIn("below L3", done.stderr)
