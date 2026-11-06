"""Local clones the agent made itself (T027, B23): git against a local remote is not network.

A `git clone <local path> <dest>` that the transcript shows, with `dest` in a declared scratch directory (never
the task worktree), proves the origin of `dest` is that local path. In such a clone, and only there, `git fetch`
and `git pull` from `origin` are not `cmd-git-network`, and `cmd-git-main` does not apply (it protects the
product worktree's main, not a throw-away clone). Anything that could change the origin (`git remote add`,
`set-url`, a `git config` write, a write to the clone's `.git`, a `-c` override, `--git-dir`, `GIT_*` in the
environment) ends the proof for that clone.
"""

import posixpath
import re

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


_PARAM_RE = re.compile(r"\s*'((?:[^']|'\\'')*)'(?:=('(?:[^']|'\\'')*'))?")
_CONFIG_FILES = ("GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")
# config keys whose value git runs as a shell command (T057, R008 #10); `alias.*` is handled apart
_COMMAND_KEYS = ("core.pager", "core.sshcommand", "core.editor", "sequence.editor")


def _env_confs(genv):
    """The `-c KEY=VALUE` overrides git takes from its environment: GIT_CONFIG_COUNT/KEY_<n>/VALUE_<n>,
    GIT_CONFIG_PARAMETERS, and a config file named by GIT_CONFIG(_GLOBAL|_SYSTEM) (its content is unknown)."""
    confs = []
    count = genv.get("GIT_CONFIG_COUNT")
    if count is not None:
        number = int(count) if count.isdigit() else -1
        for index in range(min(number, 64) if number >= 0 else 0):
            key = genv.get("GIT_CONFIG_KEY_%d" % index, UNRESOLVED)
            confs.append(key + "=" + genv.get("GIT_CONFIG_VALUE_%d" % index, ""))
        if number < 0:
            confs.append(UNRESOLVED + "=")
    params = genv.get("GIT_CONFIG_PARAMETERS")
    if params is not None:
        pos = 0
        while pos < len(params.rstrip()):
            match = _PARAM_RE.match(params, pos)
            if match is None or match.end() == pos:
                confs.append(UNRESOLVED + "=")
                break
            key = match.group(1).replace("'\\''", "'")
            value = (match.group(2) or "''")[1:-1].replace("'\\''", "'")
            confs.append(key + "=" + value)
            pos = match.end()
    for name in _CONFIG_FILES:
        if name in genv:
            confs.append("include.path=" + genv[name])
    return confs


_ALWAYS_WRITE = ("commit", "merge", "rebase", "reset", "cherry-pick", "revert", "am", "checkout", "switch",
                 "restore", "update-ref", "clean", "gc", "prune", "prune-packed", "rm", "mv", "add", "notes",
                 "replace", "update-index", "filter-branch", "repack", "init", "fast-import", "worktree")
_BRANCH_WRITE_FLAGS = ("-d", "-D", "-m", "-M", "-c", "-C", "-f", "--force", "--delete", "--move", "--copy",
                       "-u", "--set-upstream-to", "--unset-upstream", "--edit-description")


def _git_is_write(sub, sub_args):
    """True when a git subcommand modifies a repository or its worktree (so an outside `-C`/`--git-dir` is
    `write-outside`). A listing form of branch/tag/reflog/stash/symbolic-ref is a read."""
    if sub in _ALWAYS_WRITE:
        return True
    plain = [a for a in sub_args if not a.startswith("-")]
    if sub == "branch":
        return any(a in _BRANCH_WRITE_FLAGS for a in sub_args) or bool(plain)
    if sub == "tag":
        if any(a in ("-l", "--list", "-n") or a.startswith("--list") for a in sub_args):
            return False
        return any(a in ("-d", "--delete", "-f", "--force", "-a", "-s", "-m", "--annotate") for a in sub_args) \
            or bool(plain)
    if sub == "reflog":
        return bool(plain) and plain[0] in ("expire", "delete", "drop")
    if sub == "stash":
        return bool(plain) and plain[0] in ("push", "save", "pop", "apply", "drop", "clear", "store", "create")
    if sub == "symbolic-ref":
        return len(plain) >= 2
    return False


def _ref_write_targets(sub, sub_args):
    """The refs a git command writes (update-ref, symbolic-ref write, branch create/delete/move/copy)."""
    plain = [a for a in sub_args if not a.startswith("-")]
    if sub == "update-ref":
        return plain[1:2] if sub_args[:1] == ["-d"] or "--stdin" in sub_args else plain[:1]
    if sub == "symbolic-ref":
        return plain[:1] if len(plain) >= 2 else []
    if sub == "branch":
        if any(a in _BRANCH_WRITE_FLAGS for a in sub_args):
            move = any(a in ("-m", "-M", "-c", "-C", "--move", "--copy") for a in sub_args)
            return plain[-1:] if move and len(plain) >= 2 else plain
        return plain  # creating a new branch
    return []


class GitMixin:
    """State and decisions about the agent's own local clones; mixed into the Analyzer."""

    def effective_git_argv(self, argv, genv):
        """`argv` with the environment's config overrides as leading `-c` pairs and `--config-env=KEY=VAR` turned into
        `-c KEY=<value of VAR>` (T057, R008 #10): they are judged exactly like `-c`."""
        out, i = [argv[0]], 1
        for conf in _env_confs(genv):
            out += ["-c", conf]
        while i < len(argv) and argv[i].startswith("-"):
            arg = argv[i]
            spec = None
            if arg.startswith("--config-env="):
                spec = arg[len("--config-env="):]
            elif arg == "--config-env" and i + 1 < len(argv):
                spec, i = argv[i + 1], i + 1
            if spec is None:
                out.append(arg)
                if arg in ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix") \
                        and i + 1 < len(argv):
                    out.append(argv[i + 1])
                    i += 1
            else:
                key, _, var = spec.partition("=")
                out += ["-c", key + "=" + genv.get(var, UNRESOLVED)]
            i += 1
        return out + argv[i:]

    def git_write_dir(self, argv):
        """The repository/worktree directory a git command writes to (T057, R008 #13): `--work-tree`, else
        `--git-dir`/`GIT_DIR` (its parent when it ends in `.git`), else cwd with `-C` applied. None when unknown."""
        genv = self.cmd_env
        git_dir, work, cdir, i = genv.get("GIT_DIR"), genv.get("GIT_WORK_TREE"), self.cwd, 1
        while i < len(argv) and argv[i].startswith("-"):
            arg = argv[i]
            if arg == "-C" and i + 1 < len(argv):
                cdir = self.policy.normalize(argv[i + 1], cdir) or UNRESOLVED
                i += 2
                continue
            if arg.startswith("--git-dir="):
                git_dir = arg[len("--git-dir="):]
            elif arg == "--git-dir" and i + 1 < len(argv):
                git_dir, i = argv[i + 1], i + 1
            elif arg.startswith("--work-tree="):
                work = arg[len("--work-tree="):]
            elif arg == "--work-tree" and i + 1 < len(argv):
                work, i = argv[i + 1], i + 1
            i += 1
        chosen = work or git_dir
        if not chosen:
            return None if UNRESOLVED in cdir else cdir
        normal = self.policy.normalize(chosen, cdir)
        if normal is None:
            return None
        return posixpath.dirname(normal) if (not work and posixpath.basename(normal) == ".git") else normal

    def git_shared_store(self, argv, raw):
        """The shared ref/object store rules (T057, R008 #13): a writing subcommand whose directory is outside the
        worktree and scratch is `write-outside`; in the shared repo (not a proven scratch clone), a ref write outside
        HEAD and the task's own branch is `cmd-git-ref-write`, and `stash clear/drop`, `reflog expire` and
        `gc --prune` (and `git prune`) are `cmd-git-prune`."""
        confs, sub, sub_args = cmds.git_parts(self.effective_git_argv(argv, self.cmd_env))
        if _git_is_write(sub, sub_args):
            target = self.git_write_dir(argv)
            if target is not None and not self.policy.write_ok(target):
                self.add("write-outside", raw, target)
        if self.git_in_own_clone(argv):
            return
        for ref in _ref_write_targets(sub, sub_args):
            if not self._own_ref(ref) and not cmds._is_main_ref(ref):  # a main ref is cmd-git-main already
                self.add("cmd-git-ref-write", raw, ref)
        pruning = (
            (sub == "stash" and sub_args[:1] and sub_args[0] in ("clear", "drop"))
            or (sub == "reflog" and sub_args[:1] == ["expire"])
            or (sub in ("prune", "prune-packed"))
            or (sub == "gc" and any(a == "--prune" or (a.startswith("--prune=") and a != "--prune=never")
                                    for a in sub_args)))
        if pruning:
            self.add("cmd-git-prune", raw, "git " + sub)

    def _own_ref(self, ref):
        """True when a ref write targets HEAD or the task's own branch (`refs/heads/task/<id>` or `task/<id>`)."""
        own = "task/" + self.task.task_id
        bare = ref.split("@", 1)[0].split("~", 1)[0].split("^", 1)[0]
        return bare in ("HEAD", "ORIG_HEAD", own, "refs/heads/" + own) or bare.startswith(own + "/") \
            or bare.startswith("refs/heads/" + own + "/")

    def git_exec_strings(self, argv, raw, depth, env):
        """git subcommands that run a shell command for the agent (T057, R008 #11): `rebase -x/--exec CMD`,
        `bisect run CMD ARGS`, `submodule foreach CMD`."""
        _, sub, sub_args = cmds.git_parts(self.effective_git_argv(argv, self.cmd_env))
        if sub == "rebase":
            for i, arg in enumerate(sub_args):
                if arg in ("-x", "--exec") and i + 1 < len(sub_args):
                    self.bash(sub_args[i + 1], depth + 1, env)
                elif arg.startswith("--exec="):
                    self.bash(arg[len("--exec="):], depth + 1, env)
        elif sub == "bisect" and sub_args[:1] == ["run"] and len(sub_args) > 1:
            self.bash(" ".join(sub_args[1:]), depth + 1, env)
        elif sub == "submodule" and sub_args[:1] == ["foreach"] and len(sub_args) > 1:
            rest = [a for a in sub_args[1:] if a != "--recursive" and not a.startswith("-q")]
            if rest:
                self.bash(" ".join(rest), depth + 1, env)

    def git_config_code(self, argv, raw, depth, env):
        """The value of an `alias.*` (`!CMD` is shell, else git arguments), `core.pager`, `pager.*`, `core.sshCommand`
        or an editor key, from `-c` or the environment, is audited as the command it runs (T057, R008 #10)."""
        confs, _, _ = cmds.git_parts(self.effective_git_argv(argv, self.cmd_env))
        for conf in confs:
            key, _, value = conf.partition("=")
            key = key.lower()
            if not value.strip():
                continue
            if key.startswith("alias."):
                self.bash(value[1:] if value.startswith("!") else "git " + value, depth + 1, env)
            elif key in _COMMAND_KEYS or key.startswith("pager."):
                self.bash(value, depth + 1, env)

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
