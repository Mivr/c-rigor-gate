"""`ui_deviations_sections`: deviation sections of header prose and their entry count (docs/ui-deviations.md "Untagged prose").

`sections_of(group)` -> tuple of (heading line number, entries); entries 0 means the section has no recognised entry (it is
reported as `deviation-unlabelled`, never counted as one). A group is the line list `ui_deviations_lex.lex` returns.
"""

import re

WORDS = r"(?:disagreements?|deviations?|differences?[ \t]+from|differs[ \t]+from|deviates)(?![a-z0-9_])"
_START = re.compile(r"[*/#=\-\s]*" + WORDS, re.IGNORECASE)
_TITLE = re.compile(r"(?<![a-z0-9_])" + WORDS, re.IGNORECASE)
_RULE = re.compile(r"-{3,}[ \t]*(.*?)[ \t]*-*[ \t]*$")
_DECOR = "*/#=- \t"

_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
_CAP = r"([A-Z]{1,3})([1-9][0-9]{0,2})"
_DASH = r"([A-Z]{1,12}-)([1-9][0-9]{0,2})"
_TAIL = r"(?=[:.),]?(?:[ \t]+\S|$))"
_ROM = r"(i{1,3}|iv|v|vi{1,3}|ix|x)"
# (style, regex, ordinal reader); a line label is tried in this order on the left-stripped text.
_LINE = (
    ("note-n", re.compile(r"Note[ \t]+([0-9]{1,3})" + _TAIL), lambda m: int(m.group(1))),
    ("cap:", re.compile(r"(?:Note[ \t]+)?\(?" + _CAP + _TAIL), lambda m: (m.group(1), int(m.group(2)))),
    ("dash:", re.compile(_DASH + _TAIL), lambda m: (m.group(1), int(m.group(2)))),
    ("n.", re.compile(r"([0-9]{1,3})\.[ \t]+\S"), lambda m: int(m.group(1))),
    ("n)", re.compile(r"([0-9]{1,3})\)[ \t]+\S"), lambda m: int(m.group(1))),
    ("n:", re.compile(r"([0-9]{1,3}):[ \t]+\S"), lambda m: int(m.group(1))),
    ("(n)", re.compile(r"\(([0-9]{1,3})\)[ \t]+\S"), lambda m: int(m.group(1))),
    ("#n", re.compile(r"#([0-9]{1,3})[ \t:.)]+\S"), lambda m: int(m.group(1))),
    ("(r)", re.compile(r"\(" + _ROM + r"\)[ \t]+\S", re.IGNORECASE), lambda m: _ROMAN[m.group(1).lower()]),
    ("r)", re.compile(_ROM + r"\)[ \t]+\S", re.IGNORECASE), lambda m: _ROMAN[m.group(1).lower()]),
    ("r.", re.compile(_ROM + r"\.[ \t]+\S", re.IGNORECASE), lambda m: _ROMAN[m.group(1).lower()]),
    ("(a)", re.compile(r"\(([a-z])\)[ \t]+\S"), lambda m: ord(m.group(1)) - 96),
    ("a)", re.compile(r"([a-z])\)[ \t]+\S"), lambda m: ord(m.group(1)) - 96),
    ("bullet", re.compile(r"[-*•–+][ \t]+\S"), None),
)
# Inline chains: (style, regex over the whole text, ordinal reader). Same style names as the line labels.
_CHAIN = (
    ("note-n", re.compile(r"Note[ \t]+([0-9]{1,3})(?![0-9])"), lambda m: int(m.group(1))),
    ("cap:", re.compile(r"(?<![A-Za-z0-9_])" + _CAP + r"(?![A-Za-z0-9_])"), lambda m: (m.group(1), int(m.group(2)))),
    ("dash:", re.compile(r"(?<![A-Za-z0-9_-])" + _DASH + r"(?![A-Za-z0-9_])"), lambda m: (m.group(1), int(m.group(2)))),
    ("n)", re.compile(r"(?<![\w(])([0-9]{1,3})\)"), lambda m: int(m.group(1))),
    ("(n)", re.compile(r"\(([0-9]{1,3})\)"), lambda m: int(m.group(1))),
    ("#n", re.compile(r"#([0-9]{1,3})(?![0-9])"), lambda m: int(m.group(1))),
    ("(a)", re.compile(r"\(([a-z])\)"), lambda m: ord(m.group(1)) - 96),
    ("a)", re.compile(r"(?<![\w(])([a-z])\)"), lambda m: ord(m.group(1)) - 96),
    ("(r)", re.compile(r"\(" + _ROM + r"\)", re.IGNORECASE), lambda m: _ROMAN[m.group(1).lower()]),
)


def _is_rule_title(s):
    m = _RULE.match(s)
    return None if m is None or not m.group(1).strip("-") else m.group(1)


def is_heading(s, prev):
    """s: a stripped comment line; prev: the stripped line before it in the group (None at the group's start).
    A rule line whose title holds a word of the list, or a line that starts with one (after decoration) and then
    ends, or goes on with `:` `(` `,` `.` `;` or a dash (a heading); a line that starts with the word and goes on in prose
    is a heading only when it begins a paragraph (blank line, rule line or group start before it), so a wrapped sentence
    is not one."""
    title = _is_rule_title(s)
    if title is not None and _TITLE.search(title):
        return True
    m = _START.match(s)
    if m is None:
        return False
    rest = s[m.end():].lstrip(" \t")
    if rest == "" or rest[0] in ":(,.;\u2014\u2013-":
        return True            # `Deviations:`, `DISAGREEMENTS (Rust wins)`: a heading wherever it stands
    return prev is None or prev.strip(_DECOR) == "" or _is_rule_title(prev) is not None


def is_end(s):
    """A `---- title ----` rule line or an upper-case title line ends a section; a bare `---` does not."""
    if _is_rule_title(s) is not None:
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and len(s) <= 80 and all(c.isupper() for c in letters)


def indent(text):
    expanded = text.expandtabs(8)
    return len(expanded) - len(expanded.lstrip(" "))


def label(text):
    """(style, ordinal) when the left-stripped line begins with an entry label, else None."""
    body = text.strip()
    for style, regex, read in _LINE:
        m = regex.match(body)
        if m:
            return style, None if read is None else read(m)
    return None


def _chain_items(text):
    out = set()
    for style, regex, read in _CHAIN:
        ordinals = [read(m) for m in regex.finditer(text)]
        if style.endswith(":"):
            for prefix in {p for p, _ in ordinals}:
                out.update((style + prefix, k, 0) for k in range(1, _run([o for p, o in ordinals if p == prefix]) + 1))
        else:
            out.update((style, k, 0) for k in range(1, _run(ordinals) + 1))
    return out


def _run(ordinals):
    expected = 1
    for value in ordinals:
        if value == expected:
            expected += 1
    return expected - 1


def count_entries(lines):
    """Entries of one section: `lines` is [(line number, text)], the heading first. The union of (a) the labelled
    lines at the indent of the first label (or less), and (b) the longest in-order inline chain of every label style
    over the heading line and the unlabelled lines at that indent (every line when no line is labelled). 0 when there is none."""
    marks = []
    for number, text in lines[1:]:
        found = label(text)
        if found is not None:
            marks.append((number, indent(text), found))
    top = marks[0][1] if marks else None
    keys, seen = set(), {}
    for number, deep, (style, ordinal) in marks:
        if deep > top:
            continue
        if style == "bullet":
            keys.add((style, number, 0))
            continue
        name = style + ordinal[0] if style.endswith(":") else style
        value = ordinal[1] if style.endswith(":") else ordinal
        seen[(name, value)] = seen.get((name, value), -1) + 1
        keys.add((name, value, seen[(name, value)]))
    labelled = {number for number, _, _ in marks}
    shown = [text for k, (number, text) in enumerate(lines)
             if k == 0 or top is None or (indent(text) <= top and number not in labelled)]
    keys |= _chain_items(" ".join(shown))
    return len(keys)


def sections_of(group):
    """-> tuple of (heading line, entries) for one group of comment lines. A section runs from its heading to the next
    heading or end line, or to the end of the group (adjacent comments, blank lines between them included)."""
    found, current, prev = [], None, None
    for number, text in group:
        s = text.strip()
        if is_heading(s, prev):
            if current is not None:
                found.append((current[0][0], count_entries(current)))
            current = [(number, text)]
        elif current is not None and is_end(s):
            found.append((current[0][0], count_entries(current)))
            current = None
        elif current is not None:
            current.append((number, text))
        prev = s
    if current is not None:
        found.append((current[0][0], count_entries(current)))
    return tuple(found)
