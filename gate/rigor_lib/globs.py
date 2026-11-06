"""Path globs: `**` = any number of directories, `*` = any characters within one segment.

Every other character is literal (no `?`, no `[...]`). Patterns are relative POSIX paths.
A final `**` needs at least one path segment below; a leading or middle `**` may match zero.
"""

import re

from rigor_lib import paths
from rigor_lib.errors import InternalError

DOUBLE_STAR = "**"


def _compile_segment(segment, pattern):
    if DOUBLE_STAR in segment:
        raise InternalError("'**' must be a whole segment in glob %r" % pattern)
    parts = []
    for char in segment:
        parts.append(".*" if char == "*" else re.escape(char))
    return re.compile("".join(parts), re.DOTALL)


def compile_glob(pattern):
    """Turn a pattern into a tuple of segments; raise InternalError if it is not valid."""
    reason = paths.unsafe_path_reason(pattern)
    if reason is not None:
        raise InternalError("bad glob %r: %s" % (pattern, reason))
    segments = []
    for segment in pattern.split("/"):
        if segment == DOUBLE_STAR:
            segments.append(DOUBLE_STAR)
        else:
            segments.append(_compile_segment(segment, pattern))
    return tuple(segments)


def _match_segments(segments, parts):
    if not segments:
        return not parts
    head = segments[0]
    rest = segments[1:]
    if head == DOUBLE_STAR:
        if not rest:
            return len(parts) >= 1
        return any(_match_segments(rest, parts[skip:]) for skip in range(len(parts) + 1))
    if not parts:
        return False
    return head.fullmatch(parts[0]) is not None and _match_segments(rest, parts[1:])


def matches(glob, path_text):
    """True if the compiled `glob` matches the whole of `path_text`."""
    return _match_segments(glob, path_text.split("/"))
