"""Path resolution and the forbidden-path classification for `rigor trajectory`."""

import fnmatch
import os
import posixpath
import re

from rigor_lib import trajectory_rules as rules
from rigor_lib.trajectory_shell import DOLLAR, UNRESOLVED

_PROC_ROOT_RE = re.compile(r"\A/proc/(?:self|thread-self|\d+)/root(?=/|\Z)")
_PROC_CWD_RE = re.compile(r"\A/proc/(?:self|thread-self|\d+)/cwd(?=/|\Z)")
_PROC_ENVIRON_RE = re.compile(r"\A/proc/(?:self|thread-self|\d+|[^/]*[*?\[][^/]*)/environ\Z")
_HOME_PARENT_RE = re.compile(r"\A(?:/var/tmp|/root|/home/[^/]+|/Users/[^/]+)\Z")
_WORKTREE_RE = re.compile(r"\A(/(?:[^/]+/)*?wt/[^/]+/[^/]+)(?:/|\Z)")
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
            text = cwd + "/" + text
        path = collapse(text)
        path = _PROC_ROOT_RE.sub("", path) or "/"
        match = _PROC_CWD_RE.match(path)
        if match is not None:
            path = collapse(cwd + path[match.end():])
        return path

    def real(self, path):
        return os.path.realpath(path)

    # -- membership --------------------------------------------------------------------------
    @staticmethod
    def _inside(base, path):
        return path == base or path.startswith(base.rstrip("/") + "/")

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
        if path in self.exempt:
            return None
        found = self._classify(path)
        if found is None:
            real = self.real(path)
            if real != path and real not in self.exempt:
                found = self._classify(real)
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

    # -- glob words --------------------------------------------------------------------------
    def glob_rule(self, text, cwd):
        """Forbidden-read rule a wildcard path word could expand to, or None."""
        normal = self.normalize(text, cwd)
        if normal is None or not re.search(r"[*?\[]", normal):
            return None
        if _PROC_ENVIRON_RE.match(normal):
            return "read-process-environ"
        pattern = normal.split("/")
        for example, rule in self._glob_examples():
            want = example.split("/")
            if len(pattern) < len(want) or not all(
                    fnmatch.fnmatchcase(w, p) for w, p in zip(want, pattern)):
                continue
            literals = len(re.sub(r"[*?\[\]]", "", pattern[len(want) - 1]))
            if literals >= 2 and pattern[:len(want) - 1] == want[:-1]:
                return rule
        return None

    def _glob_examples(self):
        return (("/var/tmp/.config", "read-secret-dir"), ("/var/tmp/.claude", "read-claude-state"),
                (self.home + "/.config", "read-secret-dir"), (self.home + "/.ssh", "read-ssh-material"))
