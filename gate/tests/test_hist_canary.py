"""Tests for tools/hist_canary.py and the historical-canary support of canaries/runner.py (T2G8). No grading runs."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "canaries" / "hist-selftest"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hist = load("hist_canary", ROOT / "tools" / "hist_canary.py")
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
           GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def sh(cwd, *args):
    done = subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout.strip()


def write(repo, name, text):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo, message):
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", message)
    return sh(repo, "git", "rev-parse", "HEAD")


def numbered(n, changes=()):
    changes = dict(changes)
    return "".join("%s\n" % changes.get(i, "line %d" % i) for i in range(1, n + 1))


def pin_text(base, bug, fix, paths=('"a.c"',), extra=""):
    return ('product = "p"\nbase = "%s"\nbug_commit = "%s"\nfix_commit = "%s"\npaths = [%s]\n%s'
            % (base, bug, fix, ", ".join(paths), extra))


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hist-test.", dir=os.environ.get("TMPDIR"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def history(self, name="p", fixed=None):
        """A repository: c0 (two defects in a.c, a b.c with one), c1 fixes them all, c2 is later work."""
        repo = self.path(name)
        os.makedirs(repo)
        sh(repo, "git", "init", "-q", "-b", "main")
        write(repo, "a.c", numbered(40, {3: "bad three", 35: "bad thirty-five"}))
        write(repo, "b.c", "bad b\n")
        c0 = commit(repo, "c0")
        write(repo, "a.c", numbered(40))
        write(repo, "b.c", "good b\n")
        c1 = commit(repo, "c1")
        write(repo, "later.txt", "x\n")
        c2 = commit(repo, "c2")
        return repo, c0, c1, c2

    def canary(self, repo_ids, patch, paths=('"a.c"', '"b.c"'), extra=""):
        base, bug, fix = repo_ids
        folder = self.path("hist-x")
        os.makedirs(folder, exist_ok=True)
        write(folder, "pin.toml", pin_text(base, bug, fix, paths, extra))
        if patch is not None:
            write(folder, "regress.patch", patch)
        return folder

    def context(self, folder, **repos):
        return hist.Context(folder, {k: v for k, v in repos.items()}, self.dir)


class MakeVerify(Scratch):
    def test_make_selects_hunks_and_verify_accepts(self):
        repo, c0, c1, c2 = self.history()
        folder = self.canary((c2, c0, c1), None)
        ctx = self.context(folder, p=repo)
        shown = hist.fix_diff(repo, c1)
        self.assertEqual([(f.path, len(f.hunks)) for f in shown], [("a.c", 2), ("b.c", 1)])
        text = hist.select_hunks(shown, ["a.c:2", "b.c"], 3)
        write(folder, "regress.patch", text)
        self.assertTrue(hist.verify(ctx).ok)
        self.assertIn("+bad thirty-five", text)
        self.assertNotIn("bad three", text)

    def test_make_cli_writes_and_verify_cli_exits_zero(self):
        repo, c0, c1, c2 = self.history()
        folder = self.canary((c2, c0, c1), None)
        tool = [sys.executable, "-I", "-B", str(ROOT / "tools" / "hist_canary.py")]
        made = subprocess.run(tool + ["make", folder, "--repo", "p=" + repo, "--select", "a.c:1"],
                              capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        checked = subprocess.run(tool + ["verify", folder, "--repo", "p=" + repo], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("ok:", checked.stdout)

    def test_context_trim_still_applies_and_is_provenance_clean(self):
        repo, c0, c1, c2 = self.history()
        folder = self.canary((c2, c0, c1), None)
        for context in (1, 2, 3):
            text = hist.select_hunks(hist.fix_diff(repo, c1), ["a.c"], context)
            write(folder, "regress.patch", text)
            self.assertTrue(hist.verify(self.context(folder, p=repo)).ok, "context %d" % context)

    def test_context_zero_is_refused(self):
        repo, c0, c1, c2 = self.history()
        folder = self.canary((c2, c0, c1), None)
        tool = [sys.executable, "-I", "-B", str(ROOT / "tools" / "hist_canary.py")]
        done = subprocess.run(tool + ["make", folder, "--repo", "p=" + repo, "--select", "a.c", "--context", "0"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertFalse(os.path.exists(os.path.join(folder, "regress.patch")))

    def test_unknown_file_or_hunk_number_is_refused(self):
        repo, c0, c1, c2 = self.history()
        shown = hist.fix_diff(repo, c1)
        with self.assertRaises(hist.HistError):
            hist.select_hunks(shown, ["zzz.c"], 3)
        with self.assertRaises(hist.HistError):
            hist.select_hunks(shown, ["a.c:3"], 3)

    def test_added_deleted_files_and_missing_newline(self):
        repo = self.path("q")
        os.makedirs(repo)
        sh(repo, "git", "init", "-q", "-b", "main")
        write(repo, "gone.c", "old\n")
        write(repo, "tail.c", "one\ntwo")
        c0 = commit(repo, "c0")
        os.remove(os.path.join(repo, "gone.c"))
        write(repo, "new.c", "fresh\n")
        write(repo, "tail.c", "one\ntwo\n")
        c1 = commit(repo, "c1")
        write(repo, "x.txt", "x\n")
        c2 = commit(repo, "c2")
        folder = self.canary((c2, c0, c1), None, paths=('"**"',))
        text = hist.select_hunks(hist.fix_diff(repo, c1), ["gone.c", "new.c", "tail.c"], 3)
        write(folder, "regress.patch", text)
        self.assertTrue(hist.verify(self.context(folder, p=repo)).ok)
        self.assertIn("deleted file mode", text)
        self.assertIn("\\ No newline at end of file", text)


class Refusals(Scratch):
    def setup_canary(self, select=("a.c:2",)):
        repo, c0, c1, c2 = self.history()
        folder = self.canary((c2, c0, c1), None)
        text = hist.select_hunks(hist.fix_diff(repo, c1), list(select), 3)
        write(folder, "regress.patch", text)
        return repo, (c0, c1, c2), folder, text

    def refused(self, folder, repo):
        verdict = hist.verify(self.context(folder, p=repo))
        self.assertFalse(verdict.ok)
        return verdict

    def test_an_invented_hunk_is_refused(self):
        repo, _, folder, text = self.setup_canary()
        write(folder, "regress.patch", text.replace("+bad thirty-five", "+invented line"))
        verdict = self.refused(folder, repo)
        self.assertTrue(any("not the reverse of any unused hunk" in e for e in verdict.errors), verdict.errors)

    def test_a_hunk_on_another_file_or_outside_paths_is_refused(self):
        repo, ids, folder, text = self.setup_canary()
        write(folder, "regress.patch", text.replace("a.c", "b.c"))
        self.assertTrue(self.refused(folder, repo).errors)
        folder = self.canary((ids[2], ids[0], ids[1]), text, paths=('"b.c"',))
        verdict = self.refused(folder, repo)
        self.assertTrue(any("outside the pinned paths" in e for e in verdict.errors), verdict.errors)

    def test_a_hunk_used_twice_is_refused(self):
        repo, _, folder, text = self.setup_canary()
        again = text + text[text.index("diff --git"):]
        write(folder, "regress.patch", again)
        self.assertTrue(self.refused(folder, repo).errors)

    def test_a_hunk_with_a_missing_removed_line_is_refused(self):
        repo, _, folder, text = self.setup_canary()
        lines = [line for line in text.split("\n") if not line.startswith("-line 35")]
        write(folder, "regress.patch", "\n".join(lines))
        self.assertTrue(self.refused(folder, repo).errors)

    def test_unsupported_patch_text_is_refused_not_trusted(self):
        repo, _, folder, text = self.setup_canary()
        write(folder, "regress.patch", text + "\ndiff --git a/a.c b/a.c\nrename from a.c\n")
        self.assertTrue(self.refused(folder, repo).errors)

    def test_empty_patch_is_refused(self):
        repo, _, folder, _ = self.setup_canary()
        write(folder, "regress.patch", "")
        self.assertTrue(self.refused(folder, repo).errors)

    def test_fix_commit_not_an_ancestor_of_the_ref_is_refused(self):
        repo, c0, c1, c2 = self.history()
        sh(repo, "git", "checkout", "-q", "-b", "side", c2)
        write(repo, "a.c", "side\n")
        side = commit(repo, "side")
        sh(repo, "git", "checkout", "-q", "main")
        folder = self.canary((c2, c0, side), None)
        write(folder, "regress.patch", "x")
        verdict = self.context(folder, p=repo).check_commits()
        self.assertTrue(any("not an ancestor of main" in e for e in verdict), verdict)

    def test_named_ref_may_hold_the_fix(self):
        repo, c0, c1, c2 = self.history()
        sh(repo, "git", "checkout", "-q", "-b", "lane/w", c2)
        write(repo, "a.c", numbered(40, {3: "bad three"}))
        fix = commit(repo, "fix on a lane")
        sh(repo, "git", "checkout", "-q", "main")
        folder = self.canary((c2, c0, fix), None, extra='fix_ref = "lane/w"\n')
        ctx = self.context(folder, p=repo)
        self.assertEqual(ctx.check_commits(), [])
        folder = self.canary((c2, c0, fix), None)   # the default ref is main: refused
        self.assertTrue(any("not an ancestor of main" in e for e in self.context(folder, p=repo).check_commits()))

    def test_bug_commit_must_precede_the_fix(self):
        repo, c0, c1, c2 = self.history()
        folder = self.canary((c2, c2, c1), None)
        self.assertTrue(any("bug_commit" in e for e in self.context(folder, p=repo).check_commits()))

    def test_stale_patch_is_reported_stale_not_invented(self):
        repo, c0, c1, c2 = self.history()
        text = hist.select_hunks(hist.fix_diff(repo, c1), ["a.c:2"], 3)
        sh(repo, "git", "checkout", "-q", "-b", "later", c2)
        write(repo, "a.c", numbered(40, {35: "something else entirely"}))
        late = commit(repo, "later changes the same line")
        folder = self.canary((late, c0, c1), text)
        verdict = hist.verify(self.context(folder, p=repo))
        self.assertEqual(verdict.errors, [])
        self.assertIn("git apply --check", verdict.stale)
        self.assertFalse(verdict.ok)

    def test_pin_validation(self):
        folder = self.path("hist-y")
        write(folder, "pin.toml", 'product = "p"\nbase = "abc"\nbug_commit = "x"\nfix_commit = "y"\npaths = ["a"]\n')
        with self.assertRaises(hist.HistError):
            hist.load_pin(folder)
        write(folder, "pin.toml", 'product = "p"\n')
        with self.assertRaises(hist.HistError):
            hist.load_pin(folder)

    def test_a_missing_repository_is_a_usage_error(self):
        repo, c0, c1, c2 = self.history()
        folder = self.canary((c2, c0, c1), "x")
        with self.assertRaises(hist.HistError):
            self.context(folder)


class ForeignFix(Scratch):
    def test_the_fix_may_live_in_another_repository(self):
        # The product has the files at `base`; the fix (and its ref) live in a second repository.
        product, c0, c1, c2 = self.history("p")
        other, o0, o1, o2 = self.history("o")
        folder = self.canary((c2, o0, o1), None, extra='fix_repo = "o"\n')
        ctx = self.context(folder, p=product, o=other)
        self.assertEqual(ctx.check_commits(), [])
        write(folder, "regress.patch", hist.select_hunks(hist.fix_diff(other, o1), ["a.c"], 3))
        self.assertTrue(hist.verify(ctx).ok)


class Fixture(unittest.TestCase):
    """The committed hist-selftest canary: its pin, its patch and its generated history agree."""

    def test_the_committed_patch_verifies_and_is_what_make_writes(self):
        with tempfile.TemporaryDirectory() as into:
            ctx = hist.Context(str(FIXTURE), {}, into)
            self.assertTrue(hist.verify(ctx).ok)
            made = hist.select_hunks(hist.fix_diff(ctx.fix, ctx.pin["fix_commit"]), ["core/core.c"], 3)
            self.assertEqual(made, (FIXTURE / "regress.patch").read_text(encoding="utf-8"))

    def test_the_patch_touches_core_add_only(self):
        text = (FIXTURE / "regress.patch").read_text(encoding="utf-8")
        self.assertEqual([l for l in text.split("\n") if l[:1] in ("+", "-") and l[:3] not in ("+++", "---")],
                         ["-int core_add(int a, int b) { return a + b; }",
                          "+int core_add(int a, int b) { return a + b + 1; }"])


class RunnerPack(Scratch):
    """The runner fails closed before grading anything: stale, invented and missing patches."""

    def pack(self, patch=None, expect_extra=None, drop_patch=False):
        root = self.path("pack")
        os.makedirs(root, exist_ok=True)
        os.symlink(ROOT / "canaries" / "_base", os.path.join(root, "_base"))
        target = os.path.join(root, "hist-selftest")
        shutil.copytree(FIXTURE, target)
        if patch is not None:
            write(target, "regress.patch", patch)
        if drop_patch:
            os.remove(os.path.join(target, "regress.patch"))
        if expect_extra:
            path = Path(target) / "expect.json"
            data = json.loads(path.read_text())
            data.update(expect_extra)
            path.write_text(json.dumps(data))
        return root

    def run_pack(self, root):
        env = dict(os.environ, TMPDIR=self.dir)
        done = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "canaries" / "runner.py"), "--root", root,
                               "--only", "hist-selftest"], capture_output=True, text=True, env=env, cwd=ROOT)
        return done.returncode, done.stdout + done.stderr

    def test_a_stale_patch_fails_the_pack_closed(self):
        # The pin names the commit before the fix as `base`: the patch is genuine but no longer applies there.
        root = self.pack()
        pin = os.path.join(root, "hist-selftest", "pin.toml")
        text = Path(pin).read_text().replace("4abdfe203b3448669a12e669befe9bffb233c06f", "4a65ed219e51e255f7bfd8ffa99818e532685352")
        Path(pin).write_text(text)
        code, out = self.run_pack(root)
        self.assertEqual(code, 1, out)
        self.assertIn("STALE", out)
        self.assertIn("stale: git apply --check", out)

    def test_an_invented_hunk_fails_the_pack_closed(self):
        text = (FIXTURE / "regress.patch").read_text(encoding="utf-8").replace("a + b + 1", "a + b + 2")
        code, out = self.run_pack(self.pack(patch=text))
        self.assertEqual(code, 1, out)
        self.assertIn("refused", out)
        self.assertNotIn("STALE", out)

    def test_pending_without_a_patch_does_not_fail_the_pack_and_is_not_graded(self):
        code, out = self.run_pack(self.pack(expect_extra={"pending": "T2G9"}, drop_patch=True))
        self.assertEqual(code, 0, out)
        self.assertIn("pending (run, verdict printed, do not fail the pack): hist-selftest (T2G9)", out)
        self.assertIn("1 pending", out)

    def test_no_patch_and_not_pending_fails_the_pack(self):
        code, out = self.run_pack(self.pack(drop_patch=True))
        self.assertEqual(code, 1, out)
        self.assertIn("not pending", out)

    def test_hist_canary_is_found_and_flagged(self):
        runner = load("canary_runner_hist", ROOT / "canaries" / "runner.py")
        self.assertTrue(runner.is_hist("hist-selftest"))
        self.assertFalse(runner.is_hist("control"))


if __name__ == "__main__":
    unittest.main()
