"""Path resolution and the forbidden-path classification for `rigor trajectory`."""

import fnmatch
import os
import posixpath
import re
import subprocess

from rigor_lib import trajectory_rules as rules
from rigor_lib.trajectory_shell import DOLLAR, UNRESOLVED

# a pid piece the audit cannot know (`$$`, `$PPID`, `$(...)`, a wildcard) is any process (T052, R008 #5)
_PID = r"(?:self|thread-self|\d+|[^/]*[*?\[][^/]*)"
_PROC_ROOT_RE = re.compile(r"\A/proc/" + _PID + r"/(?:task/[^/]+/)?root(?=/|\Z)")
_PROC_CWD_RE = re.compile(r"\A/proc/(?:self|thread-self|\d+)/cwd(?=/|\Z)")
_PROC_ENVIRON_RE = re.compile(r"\A/proc/" + _PID + r"/(?:task/[^/]+/)?environ\Z")
_HOME_PARENT_RE = re.compile(r"\A(?:/var/tmp|/root|/home/[^/]+|/Users/[^/]+)\Z")
_WORKTREE_RE = re.compile(r"\A(/(?:[^/]+/)*?wt/[^/]+/[^/]+)(?:/|\Z)")
_WT_ROOT_RE = re.compile(r"\A/(?:[^/]+/)*?wt(?:/[^/]+)?\Z")  # a dir that holds worktrees of other tasks
_HIDDEN_RE = re.compile(r".+-hidden(?:\.git)?\Z|\Ahidden\Z")
_SSH_FILES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "authorized_keys", "id_ed25519_sk", "id_ecdsa_sk")
_SINKS = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty")
_BRACE_RE = re.compile(r"\{([^{}]*,[^{}]*)\}")
_URL_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9+.-]*://")


def collapse(path):
    path = posixpath.normpath(path)
    return "/" + path.lstrip("/") if path.startswith("//") else path


def expand_braces(text, limit=rules.MAX_BRACES):
    """`a{b,c}d` -> [abd, acd], bounded; one nesting level per pass."""
    results = [text]
    for _ in range(4):
        grown = []
        for item in results:
            match = _BRACE_RE.search(item)
            if match is None:
                grown.append(item)
                continue
            for part in match.group(1).split(","):
                grown.append(item[:match.start()] + part + item[match.end():])
        results = grown[:limit]
    return results


def _hidden_stem(literal):
    """True when a glob's literal text trends toward a `*-hidden` repo name (T052, R008 #8): it contains `hidden`,
    or its last `-`-separated segment is a non-empty prefix of `hidden` after at least one `-` (`annas-c-h`)."""
    if "hidden" in literal:
        return True
    segments = literal.split("-")
    return len(segments) >= 2 and bool(segments[-1]) and "hidden".startswith(segments[-1])


def is_url(text):
    return _URL_RE.match(text) is not None and not text.startswith("file://")


class PathPolicy:
    def __init__(self, worktree, allow_dirs, home=rules.DEFAULT_HOME):
        self.worktree = collapse(worktree)
        self.own = [self.worktree] + [collapse(d) for d in allow_dirs]
        self.real_own = [os.path.realpath(d) for d in self.own]
        self.home = collapse(home)
        self.exempt = set()   # persisted tool-output files announced by the harness
        self.made = []        # scratch dirs a gate script the agent ran printed as its own (see Audit.own_dir)
        self._tracked = None  # worktree paths git tracks on disk, read once (T052, ruling 7; None until needed)

    # -- resolving ---------------------------------------------------------------------------
    def normalize(self, text, cwd):
        """Absolute normalized path for `text`, or None if it holds an unresolved piece."""
        if UNRESOLVED in text or "\x00" in text:
            return None
        text = text.replace(DOLLAR, "$")
        if text == "~" or text.startswith("~/"):
            text = self.home + text[1:]
        elif text.startswith("~"):
            user, _, rest = text[1:].partition("/")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", user):
                return None
            text = ("/root" if user == "root" else "/home/" + user) + ("/" + rest if rest else "")
        if not text.startswith("/"):
            if UNRESOLVED in cwd:
                return None  # the working directory is unknown (T052, R008 #6)
            text = cwd + "/" + text
        path = collapse(text)
        path = _PROC_ROOT_RE.sub("", path) or "/"
        match = _PROC_CWD_RE.match(path)
        if match is not None:
            path = collapse(cwd + path[match.end():])
        return path

    def real(self, path):
        return os.path.realpath(path)

    def is_tracked(self, rel):
        """True when `rel` (a worktree-relative path) is a file git tracks in the worktree on disk. Read once with
        `git ls-files`; any failure (no repo, no git, a fixture worktree that does not exist) is an empty set, so a
        file is then treated as untracked. Like the symlink resolution, this reads the disk the audit runs on."""
        if self._tracked is None:
            self._tracked = set()
            try:
                out = subprocess.run(["git", "-C", self.worktree, "ls-files", "-z"], stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=30, check=True)
                self._tracked = set(out.stdout.decode("utf-8", "surrogateescape").split("\0"))
            except (OSError, subprocess.SubprocessError):
                pass
        return rel in self._tracked

    # -- membership --------------------------------------------------------------------------
    @staticmethod
    def _inside(base, path):
        return path == base or path.startswith(base.rstrip("/") + "/")

    def is_inside(self, base, path):
        return self._inside(base, path)

    def is_own(self, path):
        return any(self._inside(base, path) for base in self.own)

    def write_ok(self, path):
        if path in _SINKS or path.startswith("/dev/fd/"):
            return True
        if not self.is_own(path):
            return self._in_made(path)
        real = self.real(path)
        return any(self._inside(base, real) for base in self.real_own) or self.is_own(real)

    def _in_made(self, path):
        """Inside a directory the agent's own gate run created, and still there after resolving links."""
        real = self.real(path)
        return any(self._inside(base, path) and self._inside(os.path.realpath(base), real) for base in self.made)

    def relative_to_worktree(self, path):
        if self._inside(self.worktree, path):
            return posixpath.relpath(path, self.worktree)
        real = self.real(path)
        if self._inside(os.path.realpath(self.worktree), real):
            return posixpath.relpath(real, os.path.realpath(self.worktree))
        return None

    # -- forbidden reads ---------------------------------------------------------------------
    def read_rule(self, path):
        """The rule id a read of `path` breaks, or None. `path` is absolute and normalized."""
        found = self._classify(path)
        if found == "read-claude-state" and path in self.exempt:
            found = None  # an announced persisted output lifts this rule and no other (T049)
        if found is None:
            real = self.real(path)
            if real != path:
                found = self._classify(real)
                if found == "read-claude-state" and real in self.exempt:
                    found = None
        return found

    def _classify(self, path):
        if _PROC_ENVIRON_RE.match(path):
            return "read-process-environ"
        parts = path.split("/")[1:]
        for index, part in enumerate(parts):
            parent = "/" + "/".join(parts[:index])
            if part == ".config" and (_HOME_PARENT_RE.match(parent) or parent == self.home):
                return "read-secret-dir"
            if part.startswith(".claude") and not self._inside_own_part(parent):
                return "read-claude-state"
            if part == ".ssh":
                return "read-ssh-material"
        own = self.is_own(path)
        base = parts[-1] if parts else ""
        if not own and (base in _SSH_FILES or fnmatch.fnmatchcase(base, "ssh_host_*_key")):
            return "read-ssh-material"
        if own:
            return None
        return self._classify_outside(path, parts)

    def _inside_own_part(self, parent):
        return self.is_own(parent) if parent else False

    def _classify_outside(self, path, parts):
        for part in parts:
            if _HIDDEN_RE.match(part):
                return "read-hidden-repo"
            if part == "annas-mcp" or part.startswith("annas-mcp."):
                return "read-clean-room"
        cache = rules.CACHE_ROOT.rstrip("/") + "/"
        if path.startswith(cache) and path != cache.rstrip("/"):
            return "read-other-cache"
        match = _WORKTREE_RE.match(path)
        if match is not None and match.group(1) != self.worktree:
            return "read-other-worktree"
        sibling_root = posixpath.dirname(self.worktree)
        if "/wt/" in self.worktree + "/" and path.startswith(sibling_root.rstrip("/") + "/"):
            return "read-other-worktree"
        return None

    def recursive_rule(self, root):
        """Rule of a recursive read (grep -r, find, the Grep tool, ...) rooted at `root` (absolute, normalized, no
        wildcard): the rule of a forbidden root it equals or contains (T052, R008 #7). Inside the agent's own dirs, or
        a directory holding none of them, None."""
        found = self.read_rule(root)
        if found is not None or self.is_own(root):
            return found
        if _HOME_PARENT_RE.match(root) or root == self.home or any(
                self._inside(root, parent) for parent in (self.home, "/var/tmp", "/root", "/home/x", "/Users/x")):
            return "read-secret-dir"  # a home (or above one): .config, .claude*, .ssh are below
        if self._inside(root, rules.CACHE_ROOT):
            return "read-other-cache"
        if _WT_ROOT_RE.match(root) or ("/wt/" in self.worktree + "/" and
                                       self._inside(root, posixpath.dirname(self.worktree))):
            return "read-other-worktree"
        return None

    # -- glob words --------------------------------------------------------------------------
    def glob_rule(self, text, cwd):
        """Forbidden-read rule a wildcard path word could expand to, or None (T052, R008 #8). A `.`-starting
        component under a home parent that can match `.config`/`.claude*`/`.ssh` blocks; a pattern that can reach
        another task's cache or worktree, a `*-hidden` repo or `annas-mcp` blocks, but only under /var/tmp, /data
        and /home (orchestrator ruling 4: `/usr/include/a*` and other system globs stay green)."""
        normal = self.normalize(text, cwd)
        if normal is None or not re.search(r"[*?\[]", normal):
            return None
        if _PROC_ENVIRON_RE.match(normal):
            return "read-process-environ"
        parts = normal.split("/")[1:]
        wild = next((i for i, p in enumerate(parts) if re.search(r"[*?\[]", p)), len(parts))
        parent = "/" + "/".join(parts[:wild])  # the literal directory above the first wildcard component
        comp = parts[wild] if wild < len(parts) else ""
        rule = self._hidden_glob(parent, comp)
        if rule is not None:
            return rule
        return self._restricted_glob(parts) if self._under_restricted(parent) else None

    @staticmethod
    def _literals(comp):
        return re.sub(r"[*?\[\]]", "", comp)

    def _hidden_glob(self, parent, comp):
        """A `.`-starting glob component under a home parent that can match `.config`/`.claude*`/`.ssh`."""
        if not comp.startswith(".") or not (_HOME_PARENT_RE.match(parent) or parent == self.home):
            return None
        if fnmatch.fnmatchcase(".config", comp):
            return "read-secret-dir"
        if fnmatch.fnmatchcase(".claude", comp) or fnmatch.fnmatchcase(".claude.json", comp):
            return "read-claude-state"
        if fnmatch.fnmatchcase(".ssh", comp):
            return "read-ssh-material"
        return None

    def _under_restricted(self, parent):
        roots = ("/var/tmp", "/data", "/home", "/root", "/Users", self.home)
        return any(parent == r or parent.startswith(r.rstrip("/") + "/") for r in roots)

    def _restricted_glob(self, parts):
        """A glob (its full component list `parts`) reaching another cache, worktree, `*-hidden` repo or `annas-mcp`.
        A `*-hidden`/`annas-mcp` hole is a wildcard component with >= 2 literals that can match such a name; the cache
        and worktree roots match by descending the whole pattern against each forbidden directory, requiring every
        aligned component to carry a literal (a bare `*`/`**`/`?` matching a root name is left to the recursive rule)."""
        for piece in parts:
            if not re.search(r"[*?\[]", piece) or len(self._literals(piece)) < 2:
                continue
            if _hidden_stem(self._literals(piece)):
                return "read-hidden-repo"
            if "annas" in self._literals(piece) and fnmatch.fnmatchcase("annas-mcp", piece):
                return "read-clean-room"
        for root, rule in self._glob_roots():
            want = root.split("/")[1:]
            if len(parts) < len(want) or not all(
                    fnmatch.fnmatchcase(w, p) and self._literals(p) for w, p in zip(want, parts)):
                continue
            below = [re.split(r"[*?\[]", p, 1)[0] for p in parts[:len(want) + 1]]  # the forbidden dir and one below
            if not self.is_own(collapse("/" + "/".join(below))):
                return rule
        return None

    def _glob_roots(self):
        roots = [(rules.CACHE_ROOT.rstrip("/"), "read-other-cache")]
        if "/wt/" in self.worktree + "/":
            roots.append((posixpath.dirname(self.worktree), "read-other-worktree"))
        return roots
