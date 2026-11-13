"""Red tests for the verified reuse of cached toolchain trees (T030)."""

import importlib.util
import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rigor_lib import grade_build, toolchain_verify
from rigor_lib.errors import InternalError

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("verify_tree", ROOT / "toolchains" / "verify_tree.py")
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)


def make_tree(root):
    os.makedirs(os.path.join(root, "bin"))
    os.makedirs(os.path.join(root, "lib", "empty"))
    Path(root, "bin", "tool").write_bytes(b"\x7fELF-pretend" * 100)
    os.chmod(os.path.join(root, "bin", "tool"), 0o755)
    Path(root, "lib", "data.h").write_text("#define X 1\n")
    os.chmod(os.path.join(root, "lib", "data.h"), 0o644)
    os.symlink("tool", os.path.join(root, "bin", "alias"))


class VerifyTreeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/var/tmp"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.tree = os.path.join(self.dir, "tree")
        make_tree(self.tree)
        self.manifest = os.path.join(self.dir, "m")
        with open(self.manifest, "w") as handle:
            handle.write(vt.render(vt.scan(self.tree)))
        self.marker = os.path.join(self.dir, "ok")

    def verify(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = vt.main(["v", "verify", self.tree, self.manifest, self.marker])
        return code, err.getvalue()

    def assert_fails(self, needle):
        code, err = self.verify()
        self.assertEqual(code, 1, err)
        self.assertIn(needle, err)
        self.assertFalse(os.path.exists(self.marker), "no marker may be written on a difference")

    def test_untouched_tree_passes(self):
        code, err = self.verify()
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(Path(self.marker).read_text().startswith("verified "))

    def test_generation_is_reproducible_and_sorted(self):
        out = []
        for _ in range(2):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(vt.main(["v", "gen", self.tree]), 0)
            out.append(buf.getvalue())
        self.assertEqual(out[0], out[1])
        paths = [line.split("\t")[4] for line in out[0].splitlines()[1:]]
        self.assertEqual(paths, sorted(paths))
        self.assertIn("l\t-\t0\ttool\tbin/alias", out[0])

    def test_one_flipped_byte_fails(self):
        path = os.path.join(self.tree, "bin", "tool")
        data = bytearray(Path(path).read_bytes())
        data[500] ^= 1
        Path(path).write_bytes(bytes(data))
        self.assert_fails("changed: bin/tool")

    def test_appended_byte_fails(self):
        with open(os.path.join(self.tree, "lib", "data.h"), "ab") as handle:
            handle.write(b"\n")
        self.assert_fails("changed: lib/data.h")

    def test_exec_bit_gained_fails(self):
        os.chmod(os.path.join(self.tree, "lib", "data.h"), 0o755)
        self.assert_fails("changed: lib/data.h")

    def test_exec_bit_lost_fails(self):
        os.chmod(os.path.join(self.tree, "bin", "tool"), 0o644)
        self.assert_fails("changed: bin/tool")

    def test_extra_file_fails(self):
        Path(self.tree, "bin", "planted").write_text("x")
        self.assert_fails("extra: bin/planted")

    def test_extra_empty_directory_fails(self):
        os.makedirs(os.path.join(self.tree, "lib", "more"))
        self.assert_fails("extra: lib/more")

    def test_missing_file_fails(self):
        os.unlink(os.path.join(self.tree, "lib", "data.h"))
        self.assert_fails("missing: lib/data.h")

    def test_missing_directory_fails(self):
        os.rmdir(os.path.join(self.tree, "lib", "empty"))
        self.assert_fails("missing: lib/empty")

    def test_symlink_retargeted_fails(self):
        link = os.path.join(self.tree, "bin", "alias")
        os.unlink(link)
        os.symlink("../lib/data.h", link)
        self.assert_fails("changed: bin/alias")

    def test_file_replaced_by_symlink_to_identical_content_fails(self):
        path = os.path.join(self.tree, "lib", "data.h")
        content = Path(path).read_text()
        os.unlink(path)
        Path(self.dir, "elsewhere").write_text(content)
        os.symlink(os.path.join(self.dir, "elsewhere"), path)
        self.assert_fails("changed: lib/data.h")

    def test_special_file_fails(self):
        os.mkfifo(os.path.join(self.tree, "lib", "fifo"))
        self.assert_fails("fifo")

    def test_malformed_manifests_are_refused(self):
        good = Path(self.manifest).read_text()
        for bad in ("", "no header\n", good.rstrip("\n"), good + "f\tx\t1\n",
                    good + good.splitlines()[1] + "\n", good.replace("d\t-", "q\t-", 1)):
            Path(self.manifest).write_text(bad)
            with self.assertRaises(SystemExit):
                self.verify()

    def test_wrong_arguments_exit_2(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(vt.main(["v"]), 2)

    def test_tab_in_name_cannot_be_rendered(self):
        Path(self.tree, "a\tb").write_text("x")
        with self.assertRaises(SystemExit):
            vt.render(vt.scan(self.tree))


class CommittedManifestsTest(unittest.TestCase):
    def test_manifests_parse_and_cover_the_tools(self):
        llvm = vt.parse((ROOT / "toolchains" / "llvm.manifest").read_text())
        sysroot = vt.parse((ROOT / "toolchains" / "sysroot.manifest").read_text())
        for path in ("bin/clang-19", "bin/lld", "bin/llvm-symbolizer", "lib/clang/19/include"):
            self.assertIn(path, llvm)
        self.assertEqual(llvm["bin/clang-19"][:2], ("f", "x"))
        self.assertEqual(llvm["bin/ld.lld"][0], "l")
        self.assertIn("usr/include/stdio.h", sysroot)
        ndk = vt.parse((ROOT / "toolchains" / "ndk.manifest").read_text())
        prefix = "android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64/"
        for path in ("bin/clang-21", "bin/ld.lld", "bin/llvm-readelf", "lib/clang/21/include",
                     "sysroot/usr/include/jni.h", "sysroot/usr/lib/aarch64-linux-android/28/libc.so",
                     "sysroot/usr/lib/aarch64-linux-android/28/libandroid.so",
                     "sysroot/usr/lib/aarch64-linux-android/28/liblog.so"):
            self.assertIn(prefix + path, ndk)
        for table in (llvm, sysroot, ndk):
            for kind, _, size, value, path in table.values():
                self.assertFalse(path.startswith("/") or ".." in path.split("/"), path)
                if kind == "f":
                    self.assertEqual(len(value), 64, path)
                    self.assertGreaterEqual(size, 0)

    def test_buck_targets_use_the_manifests(self):
        text = (ROOT / "toolchains" / "BUCK").read_text()
        self.assertIn('manifest = t + ".manifest"', text)
        self.assertIn('script = "verify_tree.py"', text)
        # every verified tree is in the list the grader primes, in the same order for targets and manifests
        self.assertIn('for t in ["llvm", "sysroot", "ndk"]', text)
        self.assertEqual([t.split(":")[1].replace("_verified", ".manifest") for t in toolchain_verify.VERIFY_TARGETS],
                         toolchain_verify.MANIFESTS)
        self.assertEqual([t.split(":")[1].replace("_ref", ".manifest") for t in toolchain_verify.CACHED_TARGETS],
                         toolchain_verify.MANIFESTS)


class PrepareTest(unittest.TestCase):
    def fake(self, results):
        calls = []

        def run(tree, args):
            calls.append(args)
            return results[len(calls) - 1] if len(calls) <= len(results) else (0, "", "")
        return run, calls

    def test_uncached_builds_only_need_verification(self):
        self.assertTrue(toolchain_verify.needs_verification(["build", "--no-remote-cache", "//x"]))
        self.assertFalse(toolchain_verify.needs_verification(["build", "//x"]))
        self.assertFalse(toolchain_verify.needs_verification(["uquery", "--no-remote-cache"]))
        self.assertFalse(toolchain_verify.needs_verification([]))

    def test_success_runs_fetch_then_uncached_verify(self):
        run, calls = self.fake([(0, "", ""), (0, "", ""), (0, "build\tx (verify_tree llvm_verified)\tre(x)\td\n", "")])
        self.assertIsNone(toolchain_verify.prepare(run, "t"))
        self.assertNotIn("--no-remote-cache", calls[0])
        self.assertIn("toolchains//:llvm_ref", calls[0])
        self.assertIn("--no-remote-cache", calls[1])
        self.assertEqual(calls[1][-len(toolchain_verify.VERIFY_TARGETS):], toolchain_verify.VERIFY_TARGETS)
        self.assertIn("toolchains//:ndk_verified", calls[1])
        self.assertIn("toolchains//:ndk_ref", calls[0])
        self.assertEqual(calls[2], ["log", "what-ran"])

    def test_verify_failure_is_reported_and_never_refetches(self):
        run, calls = self.fake([(0, "", ""), (1, "", "TOOLCHAIN TREE DIFFERS FROM MANIFEST\nextra: x")])
        failure = toolchain_verify.prepare(run, "t")
        self.assertEqual((failure.step, failure.code), (toolchain_verify.STEP_VERIFY, 1))
        self.assertIn("VERIFICATION FAILED (verify, exit 1)", failure.message())
        self.assertIn("extra: x", failure.message())
        self.assertIn("Not re-fetching", failure.message())
        self.assertEqual(len(calls), 2)

    def test_fetch_failure_stops_before_verify(self):
        run, calls = self.fake([(1, "", "no cache and no network")])
        failure = toolchain_verify.prepare(run, "t")
        self.assertIn("(fetch, exit 1)", failure.message())
        self.assertEqual((failure.manifest(), failure.first_difference(), failure.verifier_exit_code()),
                         (None, None, None))
        self.assertEqual(len(calls), 1)

    def test_verify_served_from_cache_is_refused(self):
        line = "build\tx (verify_tree llvm_verified)\tcache\tdigest\n"
        run, _ = self.fake([(0, "", ""), (0, "", ""), (0, line, "")])
        failure = toolchain_verify.prepare(run, "t")
        self.assertEqual((failure.step, failure.code), (toolchain_verify.STEP_CACHED, 0))
        self.assertIn("served-from-cache", failure.message())
        self.assertIn(line.strip(), failure.message())

    def test_what_ran_failure_is_refused(self):
        run, _ = self.fake([(0, "", ""), (0, "", ""), (2, "", "boom")])
        self.assertIn("(what-ran, exit 2)", toolchain_verify.prepare(run, "t").message())


class RunBuckTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.original = grade_build._run_buck
        grade_build._run_buck = self.stub
        self.addCleanup(setattr, grade_build, "_run_buck", self.original)
        self.verify_code = 0

    def stub(self, tree, args):
        self.calls.append(args)
        if "--no-remote-cache" in args and toolchain_verify.VERIFY_TARGETS[0] in args:
            return self.verify_code, "", "differs"
        return 0, "", ""

    def test_forged_tree_stops_the_grade_without_starting_the_build(self):
        # T073: the `toolchain` gate reports a mismatch; a later daemon's re-check that fails is an
        # internal error (exit 2), never a build result a product gate could report as build-failed.
        self.verify_code = 1
        with self.assertRaisesRegex(InternalError, "after the toolchain gate: TOOLCHAIN VERIFICATION FAILED"):
            grade_build.run_buck("t", ["build", "--no-remote-cache", "//p:results"])
        self.assertNotIn(["build", "--no-remote-cache", "//p:results"], self.calls)

    def test_verified_uncached_build_runs_after_the_checks(self):
        args = ["build", "--no-remote-cache", "//p:results"]
        self.assertEqual(grade_build.run_buck("t", args)[0], 0)
        self.assertEqual(self.calls[-1], args)
        self.assertEqual(len(self.calls), 4)

    def test_cached_and_non_build_commands_are_untouched(self):
        grade_build.run_buck("t", ["build", "//p:results"])
        grade_build.run_buck("t", ["uquery", "x"])
        self.assertEqual(self.calls, [["build", "//p:results"], ["uquery", "x"]])


if __name__ == "__main__":
    unittest.main()
