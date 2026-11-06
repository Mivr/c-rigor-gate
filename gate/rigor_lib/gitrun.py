"""All git access. Output is read as bytes; nothing is trusted to be UTF-8 or newline free."""

import os
import re
import subprocess
from dataclasses import dataclass

from rigor_lib.errors import InternalError

GIT_TIMEOUT_SECONDS = 120
_FULL_SHA = re.compile(r"[0-9a-f]{40}")

# Flags for every diff: no rename detection (old and new names both appear), no external
# drivers, and submodule changes always shown whatever the repository config says.
DIFF_FLAGS = ["--no-renames", "--no-ext-diff", "--no-textconv",
              "--ignore-submodules=none", "--full-index"]


def git_environment():
    """A minimal environment: no user or system git config, no prompts."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run(repo, args):
    """Run git in `repo`; return (returncode, stdout bytes, stderr bytes)."""
    command = ["git", "--literal-pathspecs", "-C", os.fsencode(repo)] + [os.fsencode(a) for a in args]
    try:
        done = subprocess.run(command, env=git_environment(), capture_output=True,
                              timeout=GIT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InternalError("cannot run git: %s" % exc) from exc
    return done.returncode, done.stdout, done.stderr


def run_git(repo, args):
    """Run git and return stdout; any non-zero exit is an internal error."""
    code, out, err = _run(repo, args)
    if code != 0:
        raise InternalError("git %s failed (%d): %s" % (
            " ".join(str(a) for a in args[:2]), code, err.decode("utf-8", "replace").strip()))
    return out


def git_yes_no(repo, args):
    """Run a git test that answers with exit 0 (yes) or 1 (no); anything else is an error."""
    code, _, err = _run(repo, args)
    if code in (0, 1):
        return code == 0
    raise InternalError("git %s failed (%d): %s" % (
        " ".join(str(a) for a in args[:2]), code, err.decode("utf-8", "replace").strip()))


def resolve_commit(repo, rev):
    """Full 40-hex commit id for `rev`. Revisions that look like options are refused by git."""
    out = run_git(repo, ["rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}"])
    sha = out.decode("ascii", "replace").strip()
    if not _FULL_SHA.fullmatch(sha):
        raise InternalError("git returned an odd commit id for %r" % rev)
    return sha


def merge_base(repo, base_sha, head_sha):
    code, out, _ = _run(repo, ["merge-base", base_sha, head_sha])
    if code != 0:
        raise InternalError("no merge base between %s and %s" % (base_sha, head_sha))
    sha = out.decode("ascii", "replace").strip()
    if not _FULL_SHA.fullmatch(sha):
        raise InternalError("git returned an odd merge base")
    return sha


def commit_exists(repo, sha):
    code, _, _ = _run(repo, ["cat-file", "-e", sha + "^{commit}"])
    return code == 0


def is_ancestor(repo, ancestor_sha, head_sha):
    return git_yes_no(repo, ["merge-base", "--is-ancestor", ancestor_sha, head_sha])


@dataclass(frozen=True)
class ChangedEntry:
    old_mode: str
    new_mode: str
    status: str
    path: bytes  # raw bytes as stored in git


def parse_raw_diff(raw):
    """Parse `git diff --raw -z --no-renames` output into ChangedEntry objects."""
    tokens = raw.split(b"\0")
    if tokens[-1] != b"":
        raise InternalError("diff output does not end with NUL")
    tokens = tokens[:-1]
    if len(tokens) % 2 != 0:
        raise InternalError("diff output has an unpaired token")
    entries = []
    for index in range(0, len(tokens), 2):
        entries.append(_parse_entry(tokens[index], tokens[index + 1]))
    return entries


def _parse_entry(meta, path):
    if not meta.startswith(b":"):
        raise InternalError("diff entry does not start with ':'")
    fields = meta[1:].split(b" ")
    if len(fields) != 5:
        raise InternalError("diff entry has %d fields" % len(fields))
    status = fields[4].decode("ascii", "replace")
    if status not in ("A", "D", "M", "T"):
        raise InternalError("unexpected diff status %r" % status)
    return ChangedEntry(fields[0].decode("ascii", "replace"), fields[1].decode("ascii", "replace"),
                        status, path)


def changed_entries(repo, base_sha, head_sha):
    """Every path that differs between two commits, sorted by raw path bytes."""
    raw = run_git(repo, ["diff", "--raw", "-z"] + DIFF_FLAGS + [base_sha, head_sha, "--"])
    return sorted(parse_raw_diff(raw), key=lambda entry: entry.path)


def patch_for_path(repo, base_sha, head_sha, raw_path):
    """Zero-context patch of one path, with every file forced to be treated as text."""
    args = ["diff", "-U0", "--no-color", "--text"] + DIFF_FLAGS + [base_sha, head_sha, "--", raw_path]
    return run_git(repo, args)


def tree_paths(repo, sha):
    """Every path in the commit's tree, as raw bytes."""
    raw = run_git(repo, ["ls-tree", "-r", "-z", "--name-only", sha])
    if raw == b"":
        return []
    tokens = raw.split(b"\0")
    if tokens[-1] != b"":
        raise InternalError("ls-tree output does not end with NUL")
    return tokens[:-1]
