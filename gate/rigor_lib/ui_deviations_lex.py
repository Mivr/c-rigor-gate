"""`ui_deviations_lex`: the comment reader of `rigor ui-deviations` (docs/ui-deviations.md "Where a tag may stand").

`lex(text)` -> (comments, groups, problems). A comment is a tuple of (line number, text) pairs (consecutive `//` lines
form one comment; the leading `*` of a block comment line is decoration and is removed). A group is the lines of a maximal
run of comments with nothing but white space between them (a blank line between two `//` runs, or a comment split in two,
does not end it): sections are read over groups, tags over comments. A problem is (line, why). Pure function of the text.
"""

import re


def logical(text):
    """(characters, line numbers): newlines normalised to \\n, a backslash-newline splice removed."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    chars, lines, line, i, n = [], [], 1, 0, len(text)
    while i < n:
        if text[i] == "\\" and text[i + 1:i + 2] == "\n":
            line += 1
            i += 2
            continue
        chars.append(text[i])
        lines.append(line)
        if text[i] == "\n":
            line += 1
        i += 1
    return "".join(chars), lines


def _skip_literal(s, i, quote):
    """Index after the literal opening at s[i]; None when a newline or the end comes first."""
    i += 1
    while i < len(s) and s[i] != "\n":
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == quote:
            return i + 1
        i += 1
    return None


def _content_lines(lnums, start, body, first_strip):
    out, offset = [], start
    for k, part in enumerate(body.split("\n")):
        lineno = lnums[min(offset, len(lnums) - 1)]
        out.append((lineno, re.sub(first_strip if k == 0 else r"^[ \t]*\*?", "", part)))
        offset += len(part) + 1
    return out


def lex(text):
    s, lnums = logical(text)
    comments, groups, problems = [], [], []
    i, n, last_line_end, prev_end = 0, len(s), None, None
    while i < n:
        c = s[i]
        is_block = c == "/" and s[i + 1:i + 2] == "*"
        is_line = c == "/" and s[i + 1:i + 2] == "/"
        if is_block or is_line:
            if is_block:
                end = s.find("*/", i + 2)
                if end < 0:
                    problems.append((lnums[i], "unterminated-comment"))
                    break
                part = _content_lines(lnums, i + 2, s[i + 2:end], r"^\*?")
                stop = end + 2
            else:
                end = s.find("\n", i)
                end = n if end < 0 else end
                part = _content_lines(lnums, i + 2, s[i + 2:end], r"^$")
                stop = end
            if prev_end is not None and s[prev_end:i].strip() == "":
                groups[-1].extend(part)
            else:
                groups.append(list(part))
            if is_line and last_line_end is not None and part[0][0] == last_line_end + 1:
                comments[-1] = comments[-1] + tuple(part)
            else:
                comments.append(tuple(part))
            last_line_end = lnums[stop - 1] if is_line and stop > i else None
            prev_end, i = stop, stop
        elif c in "\"'":
            after = _skip_literal(s, i, c)
            if after is None:
                problems.append((lnums[i], "unterminated-literal"))
                after = s.find("\n", i)
                after = n if after < 0 else after
            i = after
        else:
            i += 1
    return tuple(comments), tuple(tuple(g) for g in groups), tuple(problems)
