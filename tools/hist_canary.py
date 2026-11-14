#!/usr/bin/env python3
"""Historical canaries (T2G8, P330 section 5): provenance of `canaries/hist-<id>/regress.patch`. Standard library only.

A historical canary re-introduces a real, already fixed defect into the product at a pinned `base` commit by a
gate-held patch (the reverse of the defect's hunks of the fix). This tool makes and judges that patch:

  hist_canary.py show   CANARY [--repo NAME=PATH]...            list the hunks of the fix diff, numbered
  hist_canary.py make   CANARY --select PATH[:N,N]... [--context N] [--repo NAME=PATH]...
                                                                write regress.patch from fix_commit
  hist_canary.py verify CANARY [--repo NAME=PATH]...            provenance + git apply --check on the base

`CANARY` is `canaries/hist-<id>/`. Its `pin.toml` has: `product` (repository name), `base`, `bug_commit`, `fix_commit`
(40 hex digits each), `paths` (globs: the only files the patch may touch), and optionally `fix_repo` (the repository
holding the fix when it is not the product's), `fix_ref` (a ref that must contain the fix; default `main`) and `gates`
(the gates `rigor grade --only` runs). A repository name resolves to a path through `--repo NAME=PATH`; a canary with a
`history.sh` generates its own repository (a fixture).

`verify` refuses (exit 1) when a hunk of the patch is not, up to line numbers and context, the reverse of a distinct
hunk of `git diff <fix>^ <fix>` (a canary cannot be invented), when a file is outside `paths`, when the fix is not an
ancestor of `fix_ref`, when `bug_commit` is not the fix's ancestor, or when the patch does not apply to `base`
(`stale`: the pack fails closed). Exit 2 is a usage or repository error.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import tomllib

PIN_KEYS = {"product", "base", "bug_commit", "fix_commit", "paths", "fix_repo", "fix_ref", "gates"}
REQUIRED = ("product", "base", "bug_commit", "fix_commit", "paths")
SHA = re.compile(r"[0-9a-f]{40}")
HUNK_HEAD = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?")
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
MODE_HEADERS = ("new file mode ", "deleted file mode ")
IGNORED_HEADERS = ("index ",)
REVERSE_KIND = {"add": "delete", "delete": "add", "modify": "modify"}


class HistError(Exception):
    """Usage or repository problem (exit 2)."""


def git(repo, *args, check=True, env=None, stdin=None):
    environ = dict(os.environ)
    environ.update(GIT_ENV)
    environ.update(env or {})
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=environ, input=stdin)
    if check and done.returncode != 0:
        raise HistError("git %s failed: %s" % (" ".join(args[:2]), done.stderr.strip()[-400:]))
    return done


# ---------------------------------------------------------------------------------------------------- pin.toml


def load_pin(canary_dir):
    path = os.path.join(canary_dir, "pin.toml")
    try:
        with open(path, "rb") as handle:
            pin = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise HistError("%s: %s" % (path, error))
    unknown = set(pin) - PIN_KEYS
    if unknown:
        raise HistError("%s: unknown keys %s" % (path, sorted(unknown)))
    for key in REQUIRED:
        if key not in pin:
            raise HistError("%s: missing `%s`" % (path, key))
    for key in ("base", "bug_commit", "fix_commit"):
        if not isinstance(pin[key], str) or not SHA.fullmatch(pin[key]):
            raise HistError("%s: `%s` must be a full 40-digit lowercase commit id" % (path, key))
    if not isinstance(pin["paths"], list) or not pin["paths"] or not all(isinstance(p, str) for p in pin["paths"]):
        raise HistError("%s: `paths` must be a non-empty list of globs" % path)
    gates = pin.get("gates", [])
    if not isinstance(gates, list) or not all(isinstance(g, str) for g in gates):
        raise HistError("%s: `gates` must be a list of gate ids" % path)
    pin.setdefault("fix_repo", pin["product"])
    pin.setdefault("fix_ref", "main")
    return pin


def glob_regex(glob):
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out)


def in_paths(path, globs):
    return any(glob_regex(g).fullmatch(path) for g in globs)


# ---------------------------------------------------------------------------------------------------- diff model


class Hunk:
    """One hunk: `lines` are (op, text, no_eol) with op in ' ', '+', '-'; starts are the real first line numbers."""

    def __init__(self, old_start, new_start, lines):
        self.old_start, self.new_start, self.lines = old_start, new_start, lines

    def runs(self):
        """The changes as [(removed lines, added lines)], one pair per run between context lines: what 'the same
        hunk, up to line numbers and context' compares. A line is (text, no_eol)."""
        out, minus, plus = [], [], []
        for op, text, eol in self.lines + [(" ", "", False)]:
            if op == " ":
                if minus or plus:
                    out.append((tuple(minus), tuple(plus)))
                minus, plus = [], []
            else:
                (minus if op == "-" else plus).append((text, eol))
        return out

    def reversed_runs(self):
        return [(plus, minus) for minus, plus in self.runs()]

    def count(self, ops):
        return sum(1 for line in self.lines if line[0] in ops)

    def trimmed(self, context):
        """The hunk with at most `context` context lines on each side."""
        first = next(i for i, line in enumerate(self.lines) if line[0] != " ")
        last = max(i for i, line in enumerate(self.lines) if line[0] != " ")
        lo, hi = max(0, first - context), min(len(self.lines), last + 1 + context)
        cut = self.lines[:lo]
        return Hunk(self.old_start + len(cut), self.new_start + len(cut), self.lines[lo:hi])

    def reverse(self):
        """The inverse hunk, each run written removals first (as git does)."""
        lines, minus, plus = [], [], []
        for op, text, eol in self.lines + [(" ", "", False)]:
            if op == " ":
                lines += [("-", t, e) for t, e in plus] + [("+", t, e) for t, e in minus]
                minus, plus = [], []
                lines.append((op, text, eol))
            else:
                (minus if op == "-" else plus).append((text, eol))
        return Hunk(self.new_start, self.old_start, lines[:-1])

    def render(self):
        old_n, new_n = self.count(" -"), self.count(" +")
        old_s = self.old_start - 1 if old_n == 0 else self.old_start
        new_s = self.new_start - 1 if new_n == 0 else self.new_start
        out = ["@@ -%d,%d +%d,%d @@" % (old_s, old_n, new_s, new_n)]
        for op, text, eol in self.lines:
            out.append(op + text)
            if eol:
                out.append("\\ No newline at end of file")
        return out


class FileDiff:
    def __init__(self, path, kind):
        self.path, self.kind, self.hunks = path, kind, []   # kind: "modify" | "add" | "delete"


def parse_diff(text):
    """Parse a git unified diff into [FileDiff]. Anything git would not produce for plain text edits is refused."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files, i = [], 0
    while i < len(lines):
        head = re.fullmatch(r"diff --git a/(.+) b/(.+)", lines[i])
        if not head or head.group(1) != head.group(2):
            raise HistError("line %d: expected `diff --git a/X b/X` (renames are not supported)" % (i + 1))
        item = FileDiff(head.group(2), "modify")
        i += 1
        while i < len(lines) and not lines[i].startswith(("--- ", "@@")):
            line = lines[i]
            if line.startswith(MODE_HEADERS):
                item.kind = "add" if line.startswith("new") else "delete"
            elif not line.startswith(IGNORED_HEADERS):
                raise HistError("line %d: unsupported header %r" % (i + 1, line))
            i += 1
        if i + 1 >= len(lines) or not lines[i].startswith("--- ") or not lines[i + 1].startswith("+++ "):
            raise HistError("%s: no ---/+++ headers (binary and mode-only changes are not supported)" % item.path)
        i += 2
        while i < len(lines) and lines[i].startswith("@@"):
            i = parse_hunk(lines, i, item)
        if not item.hunks:
            raise HistError("%s: a file entry without hunks" % item.path)
        files.append(item)
    return files


def parse_hunk(lines, i, item):
    head = HUNK_HEAD.fullmatch(lines[i])
    if not head:
        raise HistError("line %d: bad hunk header %r" % (i + 1, lines[i]))
    old_s, old_n, new_s, new_n = int(head.group(1)), head.group(2), int(head.group(3)), head.group(4)
    old_n = 1 if old_n is None else int(old_n)
    new_n = 1 if new_n is None else int(new_n)
    body, i = [], i + 1
    want_old, want_new = old_n, new_n
    while want_old > 0 or want_new > 0:
        if i >= len(lines) or not lines[i] or lines[i][0] not in " +-":
            raise HistError("line %d: hunk shorter than its header says" % (i + 1))
        op, text = lines[i][0], lines[i][1:]
        want_old -= op in " -"
        want_new -= op in " +"
        i += 1
        eol = i < len(lines) and lines[i].startswith("\\")
        i += eol
        body.append((op, text, eol))
    if want_old < 0 or want_new < 0:
        raise HistError("hunk longer than its header says")
    if old_n == 0:
        old_s += 1
    if new_n == 0:
        new_s += 1
    item.hunks.append(Hunk(old_s, new_s, body))
    return i


def fix_diff(repo, fix):
    done = git(repo, "diff", "--no-renames", "--binary", "-U3", fix + "^", fix)
    return parse_diff(done.stdout)


def render(files):
    out = []
    for item in files:
        out.append("diff --git a/%s b/%s" % (item.path, item.path))
        if item.kind != "modify":
            out.append("%s mode 100644" % ("new file" if item.kind == "add" else "deleted file"))
        out.append("--- %s" % ("/dev/null" if item.kind == "add" else "a/" + item.path))
        out.append("+++ %s" % ("/dev/null" if item.kind == "delete" else "b/" + item.path))
        for hunk in item.hunks:
            out.extend(hunk.render())
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------------- repositories


def parse_repo_args(values):
    repos = {}
    for value in values or []:
        name, sep, path = value.partition("=")
        if not sep or not name or not path:
            raise HistError("--repo wants NAME=PATH, got %r" % value)
        repos[name] = os.path.abspath(path)
    return repos


def generate_fixture(canary_dir, into):
    """Run the canary's history.sh (a tiny deterministic history); returns the repository path."""
    repo = os.path.join(into, "fixture")
    environ = dict(os.environ)
    environ.update(GIT_ENV)
    done = subprocess.run(["bash", os.path.join(canary_dir, "history.sh"), repo], capture_output=True, text=True,
                          env=environ)
    if done.returncode != 0:
        raise HistError("history.sh failed: %s" % done.stderr.strip()[-400:])
    return repo


def locate(name, repos, canary_dir, into):
    if name in repos:
        return repos[name]
    if os.path.isfile(os.path.join(canary_dir, "history.sh")):
        return generate_fixture(canary_dir, into)
    raise HistError("no repository for %r: pass --repo %s=PATH" % (name, name))


class Context:
    """A canary's repositories (the product's and the fix's)."""

    def __init__(self, canary_dir, repos, into):
        self.dir = canary_dir
        self.pin = load_pin(canary_dir)
        self.product = locate(self.pin["product"], repos, canary_dir, into)
        fix_repo = self.pin["fix_repo"]
        self.fix = self.product if fix_repo == self.pin["product"] else locate(fix_repo, repos, canary_dir, into)

    def check_commits(self):
        problems = []
        pin = self.pin
        for key, repo in (("base", self.product), ("bug_commit", self.fix), ("fix_commit", self.fix)):
            if git(repo, "cat-file", "-e", pin[key] + "^{commit}", check=False).returncode != 0:
                problems.append("%s %s is not a commit of the %s repository" % (key, pin[key][:12],
                                                                              "product" if repo is self.product else "fix"))
        if problems:
            return problems
        if git(self.fix, "rev-parse", "--verify", "-q", pin["fix_ref"] + "^{commit}", check=False).returncode != 0:
            return ["fix_ref %r does not exist in the fix repository" % pin["fix_ref"]]
        if git(self.fix, "merge-base", "--is-ancestor", pin["fix_commit"], pin["fix_ref"], check=False).returncode != 0:
            problems.append("fix_commit %s is not an ancestor of %s" % (pin["fix_commit"][:12], pin["fix_ref"]))
        if git(self.fix, "merge-base", "--is-ancestor", pin["bug_commit"], pin["fix_commit"], check=False).returncode != 0:
            problems.append("bug_commit %s is not an ancestor of fix_commit" % pin["bug_commit"][:12])
        return problems


# ---------------------------------------------------------------------------------------------------- the checks


def provenance(patch_files, fix_files, paths):
    """Reasons the patch is not a selection of reversed hunks of the fix (empty = every hunk is genuine)."""
    problems, pool = [], {}
    for item in fix_files:
        for number, hunk in enumerate(item.hunks, 1):
            pool.setdefault((item.path, item.kind), []).append((number, hunk.reversed_runs()))
    if not patch_files:
        problems.append("the patch has no hunks")
    for item in patch_files:
        if not in_paths(item.path, paths):
            problems.append("%s is outside the pinned paths" % item.path)
        candidates = pool.get((item.path, REVERSE_KIND[item.kind]), [])
        for hunk in item.hunks:
            sequence = hunk.runs()
            match = next((c for c in candidates if c[1] == sequence), None)
            if match is None:
                problems.append("%s: a hunk at line %d is not the reverse of any unused hunk of the fix diff"
                                % (item.path, hunk.old_start))
            else:
                candidates.remove(match)
    return problems


def applies(product, base, patch_text):
    """(True, "") when `git apply --check` accepts the patch on `base` (checked against the index, no work tree)."""
    with tempfile.TemporaryDirectory() as scratch:
        env = {"GIT_INDEX_FILE": os.path.join(scratch, "index")}
        git(product, "read-tree", base, env=env)
        done = git(product, "apply", "--cached", "--check", "-", env=env, check=False, stdin=patch_text)
    return done.returncode == 0, done.stderr.strip()


class Verdict:
    """`errors`: provenance and pin problems; `stale`: the patch no longer applies on `base`."""

    def __init__(self, errors, stale):
        self.errors, self.stale = errors, stale

    @property
    def ok(self):
        return not self.errors and not self.stale


def verify(ctx):
    path = os.path.join(ctx.dir, "regress.patch")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        raise HistError("%s: %s" % (path, error))
    errors = ctx.check_commits()
    if errors:
        return Verdict(errors, None)
    try:
        patch_files = parse_diff(text)
    except HistError as error:
        return Verdict(["regress.patch: %s" % error], None)
    errors = provenance(patch_files, fix_diff(ctx.fix, ctx.pin["fix_commit"]), ctx.pin["paths"])
    if errors:
        return Verdict(errors, None)
    good, why = applies(ctx.product, ctx.pin["base"], text)
    return Verdict([], None if good else "git apply --check on base %s: %s" % (ctx.pin["base"][:12], why))


def select_hunks(files, selections, context):
    """Pick hunks of the fix diff and return the reversed patch text. A selection is PATH or PATH:N,N (1-based)."""
    by_path = {item.path: item for item in files}
    chosen = []
    for selection in selections:
        path, sep, numbers = selection.partition(":")
        if path not in by_path:
            raise HistError("%s is not changed by the fix commit" % path)
        item = by_path[path]
        wanted = [int(n) for n in numbers.split(",")] if sep else list(range(1, len(item.hunks) + 1))
        for number in wanted:
            if not 1 <= number <= len(item.hunks):
                raise HistError("%s has hunks 1..%d, not %d" % (path, len(item.hunks), number))
        out = FileDiff(path, REVERSE_KIND[item.kind])
        out.hunks = [item.hunks[n - 1].trimmed(context).reverse() for n in sorted(set(wanted))]
        chosen.append(out)
    return render(chosen)


# ---------------------------------------------------------------------------------------------------- CLI


def command_show(args, ctx):
    for item in fix_diff(ctx.fix, ctx.pin["fix_commit"]):
        for number, hunk in enumerate(item.hunks, 1):
            print("%s:%d  (%s, -%d +%d)" % (item.path, number, item.kind, hunk.count("-"), hunk.count("+")))
            for op, text, _ in hunk.lines:
                print("    %s%s" % (op, text))
    return 0


def command_make(args, ctx):
    errors = ctx.check_commits()
    if errors:
        print("refused: " + "; ".join(errors), file=sys.stderr)
        return 1
    text = select_hunks(fix_diff(ctx.fix, ctx.pin["fix_commit"]), args.select, args.context)
    files = parse_diff(text)
    errors = provenance(files, fix_diff(ctx.fix, ctx.pin["fix_commit"]), ctx.pin["paths"])
    if errors:
        print("refused: " + "; ".join(errors), file=sys.stderr)
        return 1
    good, why = applies(ctx.product, ctx.pin["base"], text)
    if not good:
        print("refused: the reversed hunks do not apply on base %s (stale): %s" % (ctx.pin["base"][:12], why),
              file=sys.stderr)
        return 1
    with open(os.path.join(ctx.dir, "regress.patch"), "w", encoding="utf-8") as handle:
        handle.write(text)
    print("wrote %s (%d hunks)" % (os.path.join(ctx.dir, "regress.patch"), sum(len(f.hunks) for f in files)))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("show", command_show), ("make", command_make), ("verify", command_verify)):
        child = sub.add_parser(name)
        child.add_argument("canary")
        child.add_argument("--repo", action="append", default=[], metavar="NAME=PATH")
        child.set_defaults(handler=handler)
        if name == "make":
            child.add_argument("--select", action="append", required=True, metavar="PATH[:N,N]")
            child.add_argument("--context", type=int, default=3)
    return parser


def command_verify(args, ctx):
    result = verify(ctx)
    if result.errors:
        print("refused: " + "; ".join(result.errors), file=sys.stderr)
        return 1
    if result.stale:
        print("stale: " + result.stale, file=sys.stderr)
        return 1
    print("ok: every hunk is the reverse of a hunk of %s, and the patch applies on %s"
          % (ctx.pin["fix_commit"][:12], ctx.pin["base"][:12]))
    return 0


def main(argv):
    args = build_parser().parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="hist-canary.") as into:
            ctx = Context(os.path.abspath(args.canary), parse_repo_args(args.repo), into)
            return args.handler(args, ctx)
    except HistError as error:
        print("hist_canary: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
