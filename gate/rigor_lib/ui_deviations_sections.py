"""`ui_deviations_sections`: deviation sections of header prose and their entry count (docs/ui-deviations.md "Untagged prose").

`sections_of(group)` -> tuple of `Section`; entries 0 means no recognised entry (`deviation-unlabelled`, never counted as
one). A group is the line list `ui_deviations_lex.lex` returns. The closed list of heading words is `HEADING_WORDS` (and `MID_WORDS`), in one place.
"""

import re
from dataclasses import dataclass

# The closed list of heading words (case-insensitive, whole words), in one place. HEADING_WORDS may start a section at a line
# start or in a titled rule line; MID_WORDS (the nouns and phrases of the list, without `differ`, `differs` and `differing`) also in the middle of a line when
# a colon or the first entry label follows in its sentence.
_NOUNS = (r"disagreements?", r"deviations?", r"differences?[ \t]+from", r"deviates", r"rs[ \t]+vs\.?[ \t]+c", r"rust[ \t]+vs\.?")
HEADING_WORDS = r"(?:" + "|".join(_NOUNS + (r"differ(?:s|ing)?",)) + r")(?![a-z0-9_])"
MID_WORDS = r"(?:" + "|".join(_NOUNS) + r")(?![a-z0-9_])"
_START = re.compile(r"[*/#=\-\s]*" + HEADING_WORDS, re.IGNORECASE)
_TITLE = re.compile(r"(?<![a-z0-9_])" + HEADING_WORDS, re.IGNORECASE)
_ANY = re.compile(r"(?<![a-z0-9_])" + MID_WORDS, re.IGNORECASE)
_RULE = re.compile(r"-{3,}[ \t]*(.*?)[ \t]*-*[ \t]*$")
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
# The first entry label of any style: a heading word followed by one in its sentence makes the line a heading.
_FIRST = re.compile(r"\(1\)|(?<![\w(])1\)|\(a\)|(?<![\w(])a\)|#1(?![0-9])|(?<![A-Za-z0-9_])[A-Z]{1,3}-?1(?![0-9A-Za-z_])"
                    r"|Note[ \t]+1(?![0-9])")
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
_CAP = r"([A-Z]{1,3})([1-9][0-9]{0,2})"
_DASH = r"([A-Z]{1,12}-[A-Z]?)([1-9][0-9]{0,2})"
_DASHW = r"([A-Z]{2,12}-)([A-Z][A-Z0-9]{0,3})"
_TAIL = r"(?=[:.),]?(?:[ \t]+\S|$))"
_ROM = r"(i{1,3}|iv|v|vi{1,3}|ix|x)"
# (style, regex, ordinal reader); a line label is tried in this order on the left-stripped text.
_LINE = (
    ("note-n", re.compile(r"Note[ \t]+([0-9]{1,3})" + _TAIL), lambda m: int(m.group(1))),
    ("cap:", re.compile(r"(?:Note[ \t]+)?\(?" + _CAP + r"(?:-[A-Z]{1,3}[1-9][0-9]{0,2})?" + _TAIL),
     lambda m: (m.group(1), int(m.group(2)))),
    ("dash:", re.compile(_DASH + _TAIL), lambda m: (m.group(1), int(m.group(2)))),
    ("dashw:", re.compile(_DASHW + _TAIL), lambda m: (m.group(1), m.group(2))),
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
# Inline chains: (style, regex over the section text, ordinal reader); same style names as the line labels.
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
_BEFORE_ENTRY = re.compile(r"(?:[.;:!?]\s+|\n\s*)$")


@dataclass(frozen=True)
class Section:
    line: int          # the heading's line
    entries: int       # 0: no recognised entry
    styles: frozenset  # the label styles of its entries
    open: bool         # it ran to the end of its group (a labelled continuation after code would be a split)


def _is_rule_title(s):
    m = _RULE.match(s)
    return None if m is None or not m.group(1).strip("-") else m.group(1)


def is_heading(s, nxt=""):
    """s: a stripped comment line; nxt: the next stripped line of its group (a heading phrase may wrap onto it).
    A rule line whose title holds a word of HEADING_WORDS; a line that starts with one (after any run of `*`, `/`, `#`, `=`, `-` and
    white space), whatever follows; or a line holding one followed in its sentence by a colon or by the first entry label."""
    if not s:
        return False
    title = _is_rule_title(s)
    if title is not None and _TITLE.search(title):
        return True
    joined = s + " " + nxt
    if _START.match(joined):
        return True
    if label(s) is not None:
        return False                      # an entry line that mentions a heading word is an entry, not a heading
    for m in _ANY.finditer(joined):
        if m.start() >= len(s):
            break
        if joined[:m.start()].endswith('"'):
            continue                      # a quoted word is a reference to a heading ("Disagreements"), not one
        sentence = _SENTENCE_END.split(joined[m.end():], 1)[0]
        if ":" in sentence or _FIRST.search(sentence):
            return True
    return False


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


def is_end(s):
    """A `---- title ----` rule line or an all-upper-case title line ends a section; a bare `---` and a line that carries an
    entry label (`D2 NO CAP IN RUST`) do not."""
    if label(s) is not None:
        return False
    if _is_rule_title(s) is not None:
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and len(s) <= 80 and all(c.isupper() for c in letters)


def _run(ordinals):
    expected = 1
    for value in ordinals:
        if value == expected:
            expected += 1
    return expected - 1


def _chain_items(text):
    """(style, k, 0) for every in-order chain from 1 whose items stand where an entry starts: at the start of the text or of
    a line, or after a sentence end. A label inside the text of an entry (`(A1)`, `D1` in `see D1`) is a cross-reference."""
    out = set()
    for style, regex, read in _CHAIN:
        found = [(read(m), m.start()) for m in regex.finditer(text)
                 if text[:m.start()].strip() == "" or _BEFORE_ENTRY.search(text[:m.start()])]
        ordinals = [o for o, _ in found]
        if style.endswith(":"):
            for prefix in {p for p, _ in ordinals}:
                out.update((style + prefix, k, 0) for k in range(1, _run([o for p, o in ordinals if p == prefix]) + 1))
        else:
            out.update((style, k, 0) for k in range(1, _run(ordinals) + 1))
    return out


def _name(style, ordinal):
    return style + ordinal[0] if style.endswith(":") else style


def _family(name):
    """The label style without its prefix letters (`cap:D` and `cap:B` are one style): what a continuation must share."""
    return name.split(":")[0] + ":" if ":" in name else name


def _paragraphs(lines):
    out, current = [], []
    for item in lines:
        if item[1].strip() == "":
            if current:
                out.append(current)
            current = []
        else:
            current.append(item)
    return out + ([current] if current else [])


def count_entries(lines):
    """-> (entries, styles, closed). `lines` is [(line number, text)], the heading first. Only the run of paragraphs that
    carry a label of a style already seen counts (a later unrelated list after a blank line and an unlabelled paragraph
    does not; the first labelled paragraph always does). Entries are the union of the labelled lines at the indent of the first
    label (or less) and the in-order inline chains over the heading line and the unlabelled lines at that indent."""
    marks, kept, seen, top, closed = [], [], set(), None, False
    for k, para in enumerate(_paragraphs(lines)):
        mine = [(n, indent(t), label(t)) for n, t in (para[1:] if k == 0 else para) if label(t) is not None]
        deep = top if top is not None else (mine[0][1] if mine else None)
        styles = {_family(_name(*lab)) for _, ind, lab in mine if ind <= deep}
        if k and seen and not (styles & seen):
            closed = True
            break
        kept.extend(para)
        marks.extend(mine)
        seen |= styles
        top = deep
    keys, count = set(), {}
    for number, deep, (style, ordinal) in marks:
        if deep > top:
            continue
        if style == "bullet":
            keys.add((style, number, 0))
            continue
        name = _name(style, ordinal)
        value = ordinal[1] if style.endswith(":") else ordinal
        count[(name, value)] = count.get((name, value), -1) + 1
        keys.add((name, value, count[(name, value)]))
    labelled = {number for number, _, _ in marks}
    shown = "\n".join(t for k, (number, t) in enumerate(kept)
                      if k == 0 or top is None or (indent(t) <= top and number not in labelled))
    keys |= _chain_items(shown)
    return len(keys), frozenset(_family(key[0]) for key in keys), closed


def sections_of(group):
    """-> tuple of Section for one group of comment lines. A section runs from its heading to the next heading or end
    line, or to the end of the group (adjacent comments, blank lines between them included)."""
    found, current = [], None
    stripped = [t.strip() for _, t in group]

    def close(open_):
        entries, styles, closed = count_entries(current)
        found.append(Section(current[0][0], entries, styles, open_ and not closed))

    for k, (number, text) in enumerate(group):
        nxt = stripped[k + 1] if k + 1 < len(group) else ""
        if is_heading(stripped[k], nxt):
            if current is not None:
                close(False)
            current = [(number, text)]
        elif current is not None and is_end(stripped[k]):
            close(False)
            current = None
        elif current is not None:
            current.append((number, text))
    if current is not None:
        close(True)
    return tuple(found)


def continuation_label_lines(group, styles):
    """Lines of the first paragraph-run of `group` (before any heading or end line) that carry a label of a style in
    `styles`: a section that ran to the end of the previous group continues there after code."""
    out = []
    for number, text in group:
        s = text.strip()
        if is_heading(s) or is_end(s):
            break
        found = label(text)
        if found is not None and _family(_name(*found)) in styles:
            out.append(number)
    return out
