"""Local clones the agent made itself (T027, B23): git against a local remote is not network.

A `git clone <local path> <dest>` that the transcript shows, with `dest` in a declared scratch directory (never
the task worktree), proves the origin of `dest` is that local path. In such a clone, and only there, `git fetch`
and `git pull` from `origin` are not `cmd-git-network`, and `cmd-git-main` does not apply (it protects the
product worktree's main, not a throw-away clone). Anything that could change the origin (`git remote add`,
`set-url`, a `git config` write, a write to the clone's `.git`, a `-c` override, `--git-dir`, `GIT_*` in the
environment) ends the proof for that clone.
"""

import posixpath

from rigor_lib import trajectory_cmds as cmds
from rigor_lib import trajectory_rules as rules
from rigor_lib.trajectory_shell import UNRESOLVED

_CLONE_VALUE_OPTS = ("-b", "--branch", "--depth", "-j", "--jobs", "-u", "--upload-pack", "--filter",
                     "--shallow-since", "--shallow-exclude", "--server-option", "--bundle-uri", "--revision",
                     "-o", "--origin", "--reference", "--reference-if-able", "--template",
                     "--separate-git-dir", "-c", "--config")
_FETCH_VALUE_OPTS = ("--depth", "-j", "--jobs", "--upload-pack", "--refmap", "--filter", "-o", "--server-option",
                     "--shallow-since", "--shallow-exclude", "--deepen", "--negotiation-tip")
# clone options that can change where the clone's origin points, or that bring in other repositories
_CLONE_REFUSED = ("--origin", "--separate-git-dir", "--template", "--config", "--recurse-submodules",
                  "--recursive", "--reference", "--reference-if-able")
_TAINTING = ("cmd-git-config-write", "git-config-override", "cmd-no-verify")


def _refused_clone_option(args):
    for arg in args:
        if arg == "--":
            return False
        name = arg.split("=", 1)[0]
        if name in _CLONE_REFUSED or name.startswith("--recurse"):
            return True
        if arg.startswith("-") and not arg.startswith("--") and set(arg[1:]) & {"o", "c"}:
            return True
    return False


class GitMixin:
    """State and decisions about the agent's own local clones; mixed into the Analyzer."""

    def git_dir_of(self, argv):
        """The directory a git command acts in (cwd plus `-C`), or None when it cannot be known."""
        if any(key.startswith("GIT_") for key in list(self.env_now) + self.prefix_words):
            return None
        directory, i = self.cwd, 1
        while i < len(argv) and argv[i].startswith("-"):
            arg = argv[i]
            if arg == "-C" and i + 1 < len(argv):
                directory = self.policy.normalize(argv[i + 1], directory)
                if directory is None:
                    return None
                i += 2
            elif arg.split("=", 1)[0] in ("--git-dir", "--work-tree"):
                return None
            elif arg in ("-c", "--namespace", "--exec-path", "--config-env", "--super-prefix"):
                i += 2
            else:
                i += 1
        return directory

    def clone_of(self, path):
        """The proven, untouched local clone that contains `path`, or None."""
        found = None
        for directory, tainted in self.clones.items():
            if self.policy.is_inside(directory, path):
                if tainted:
                    return None
                found = directory
        return found

    def git_in_own_clone(self, argv):
        directory = self.git_dir_of(argv)
        return directory is not None and self.clone_of(directory) is not None

    # -- the network question ------------------------------------------------------------------
    def git_local_remote(self, argv):
        """True when a networked git command only talks to a local path the transcript proves."""
        confs, sub, sub_args = cmds.git_parts(argv)
        if any(c.split("=", 1)[0].lower() not in rules.GIT_ALLOWED_C_KEYS for c in confs):
            return False
        if sub == "clone":
            plain = [sub_args[i] for i in cmds.positionals(sub_args, _CLONE_VALUE_OPTS)]
            return bool(plain) and self.local_source(plain[0])
        if sub not in ("fetch", "pull", "ls-remote") or not self.git_in_own_clone(argv):
            return False
        plain = [sub_args[i] for i in cmds.positionals(sub_args, _FETCH_VALUE_OPTS)]
        return not plain or plain[0] == "origin"

    def local_source(self, word):
        if not word or UNRESOLVED in word or "://" in word:
            return False
        if word.startswith(("/", "./", "../")):
            return True
        if ":" in word:
            return False
        normal = self.policy.normalize(word, self.cwd)
        return normal is not None and (self.policy.is_own(normal) or self.clone_of(normal) is not None)

    # -- keeping the registry --------------------------------------------------------------------
    def git_taint(self, argv, found):
        """A command that can repoint a clone's origin ends the proof for the clone it acts in."""
        if not any(rule in _TAINTING for rule in found):
            return
        directory = self.git_dir_of(argv)
        for clone in self.clones:
            if directory is None or self.policy.is_inside(clone, directory) or self.policy.is_inside(
                    directory, clone):
                self.clones[clone] = True

    def git_touch(self, path):
        """A write into a clone's `.git` may change its origin."""
        for clone in self.clones:
            if self.policy.is_inside(posixpath.join(clone, ".git"), path):
                self.clones[clone] = True

    def note_clone(self, argv, clean):
        """After a `git clone` that raised no finding: remember its destination as a proven local clone."""
        confs, sub, sub_args = cmds.git_parts(argv)
        if sub != "clone":
            return
        plain = [sub_args[i] for i in cmds.positionals(sub_args, _CLONE_VALUE_OPTS)]
        if not plain or len(plain) > 2:
            return
        directory = self.git_dir_of(argv)
        dest = plain[1] if len(plain) == 2 else posixpath.basename(plain[0].rstrip("/")).removesuffix(".git")
        if directory is None or not dest or UNRESOLVED in dest:
            return
        dest = self.policy.normalize(dest, directory)
        if dest is None:
            return
        self.clones.pop(dest, None)  # a new clone replaces whatever was there
        if (clean and not confs and not _refused_clone_option(sub_args) and self.local_source(plain[0])
                and any(self.policy.is_inside(base, dest) for base in self.policy.own[1:])):
            self.clones[dest] = False
