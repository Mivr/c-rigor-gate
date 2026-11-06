"""Read the added lines out of a zero-context `git diff` patch of a single file."""

import re

from rigor_lib.errors import InternalError

_HUNK_HEADER = re.compile(rb"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(patch):
    """List of (new line number, line bytes without the '+') for every added line.

    Everything before the first hunk is file header and is skipped. Inside hunks every line
    starts with '+', '-', ' ' or '\\' (content lines cannot start with '@@'), so a line is
    never mistaken for a header however its text looks.
    """
    lines = patch.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    added = []
    in_hunk = False
    new_number = 0
    for line in lines:
        if line.startswith(b"@@"):
            match = _HUNK_HEADER.match(line)
            if match is None:
                raise InternalError("unparseable hunk header")
            in_hunk = True
            new_number = int(match.group(1))
        elif not in_hunk:
            continue
        elif line.startswith(b"+"):
            added.append((new_number, line[1:]))
            new_number += 1
        elif line.startswith(b" "):
            new_number += 1
        elif not line.startswith((b"-", b"\\")):
            raise InternalError("unexpected line inside a hunk")
    return added
