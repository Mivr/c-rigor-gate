"""T100: an environment listing that only a literal `grep` sees (`env | grep -i "buck\\|HOME"`) is a review, not a dump.

The listing is filtered to the lines that hold the patterns, so it can only leak a secret when a pattern could match
one: every pattern must be a plain literal (letters, digits, `_`, `-`, `=`, `^`, spaces, alternation) and none may
contain a secret-looking fragment. Any option that could widen the output (`-v`, `-A/-B/-C`, `-f`, `-r`, `-x`) or
make the patterns something other than literals leaves the listing a `cmd-env-dump`."""

import posixpath
import re

_GREPS = ("grep", "egrep", "fgrep")
_FLAG_LETTERS = set("iEFwcqnoH")  # matching style and counts; nothing that adds lines or reads files
_LITERAL_RE = re.compile(r"[A-Za-z0-9_=^ |-]+")
_SECRET_FRAGMENT_RE = re.compile(r"key|token|secret|pass|auth|cred", re.I)
_LONG_FLAGS = ("--ignore-case", "--extended-regexp", "--fixed-strings", "--word-regexp", "--count", "--quiet",
               "--line-number", "--only-matching", "--no-messages")


def _pattern_ok(pattern):
    text = pattern.replace("\\|", "|")
    if "\\" in text or not _LITERAL_RE.fullmatch(text) or _SECRET_FRAGMENT_RE.search(text):
        return False
    return all(part.strip() for part in text.split("|"))  # an empty alternative matches every line


def filtered_by_grep(command):
    """True when the stdout of `command` (a Command of trajectory_shell) goes only into a literal-pattern `grep`."""
    after = command.pipe_to
    if after is None or command.heredocs or any(r.fd != "2" for r in command.redirects):
        return False
    if after.heredocs or after.assigns or not after.words:
        return False
    words = after.words
    if any(w.subs or "$" in w.text or "`" in w.text for w in words) or posixpath.basename(words[0].text) not in _GREPS:
        return False
    patterns, i, args = [], 1, [w.text for w in words]
    while i < len(args):
        arg = args[i]
        if arg == "-e":
            if i + 1 >= len(args):
                return False
            patterns.append(args[i + 1])
            i += 1
        elif arg.startswith("--regexp="):
            patterns.append(arg.split("=", 1)[1])
        elif arg in _LONG_FLAGS:
            pass
        elif arg.startswith("-") and not arg.startswith("--") and len(arg) > 1 and set(arg[1:]) <= _FLAG_LETTERS:
            pass
        elif arg.startswith("-"):
            return False
        else:
            patterns.append(arg)
            if len(patterns) > 1 and "-e" not in args and not any(a.startswith("--regexp=") for a in args):
                return False  # a second plain word is a file to search, not the listing
        i += 1
    return bool(patterns) and all(_pattern_ok(p) for p in patterns)
