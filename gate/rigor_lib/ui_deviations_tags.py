"""`ui_deviations_tags`: the tag grammar of `rigor ui-deviations` (docs/ui-deviations.md "Grammar").

    @deviation(<id>, oracle="..", state="..", reason="..", link="..", until="..")

`tags_of(comment, path, ctx)` -> (tags, [(line, id or None, why)]). Strict: every text shaped like a tag (`@deviation` in any
letter case, ASCII or fullwidth at-sign, whatever precedes or follows) is either a well-formed tag or a malformed finding.
"""

import bisect
import datetime
import re
from dataclasses import dataclass

from rigor_lib import jsonio

REASONS = ("intentional", "substrate", "reference-bug")
KEYS = ("oracle", "state", "reason", "link", "until")
MAX_ID = 64              # characters of an id
MAX_VALUE = 512          # characters of a value
ISSUE_RE = re.compile(r"[0-9]{1,7}")   # the issue number after the link prefix of a `reference-bug`
HORIZON_DAYS = 366       # an `until` date further than this from --today is refused
ID_RE = re.compile(r"[A-Z][A-Z0-9]*-[A-Z0-9.-]+")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TASK_RE = re.compile(r"[A-Z][0-9]{2,4}[a-z]?")      # T123, L045, U13, U04a
STATE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")
_NO_SPACE = re.compile(r"\S+")
_ID_TOKEN = re.compile(r'[^\s,()="]+')
_KEY_TOKEN = re.compile(r"[A-Za-z_]+")
SHAPE = re.compile("[@＠]deviation", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9_@＠]")
_WS = " \t\n"


@dataclass(frozen=True)
class Tag:
    id: str
    oracle: str
    states: tuple
    reason: str
    link: str
    until: str
    path: str
    line: int


@dataclass(frozen=True)
class Context:
    """What the checks need besides the tag: the link prefix of the baseline and today's date."""
    link_prefix: str
    today: datetime.date


class _Bad(Exception):
    """One malformed tag; the text is a short stable reason code."""


def canonical_bytes(tag):
    """The canonical form the baseline hashes: canonical JSON (sorted keys, compact, ASCII) of the six fields and the path of
    the header they stand in (so a tag cannot move to another header unnoticed)."""
    return jsonio.canonical_dumps({"id": tag.id, "oracle": tag.oracle, "state": list(tag.states), "reason": tag.reason,
                                   "link": tag.link, "until": tag.until, "path": tag.path})


def canonical_sha256(tag):
    return jsonio.sha256_hex(canonical_bytes(tag))


def _skip(s, i):
    while i < len(s) and s[i] in _WS:
        i += 1
    return i


def _read_string(s, i):
    if s[i:i + 1] != '"':
        raise _Bad("expected-string")
    out, i = [], i + 1
    while i < len(s):
        c = s[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "\\":
            if s[i + 1:i + 2] not in ('"', "\\"):
                raise _Bad("bad-escape")
            out.append(s[i + 1])
            i += 2
            continue
        if c == "\n":
            raise _Bad("newline-in-string")
        if ord(c) < 32 or ord(c) == 127:
            raise _Bad("control-character")
        out.append(c)
        if len(out) > MAX_VALUE:
            raise _Bad("value-too-long")
        i += 1
    raise _Bad("unterminated-tag")


def _parse(s, i):
    """s[i] is the `(` after `@deviation`. -> (id, {key: value}, end index). Raises _Bad."""
    i = _skip(s, i + 1)
    token = _ID_TOKEN.match(s, i)
    if token is None or len(token.group(0)) > MAX_ID or not ID_RE.fullmatch(token.group(0)):
        raise _Bad("bad-id")
    ident, fields, i = token.group(0), {}, token.end()
    while True:
        i = _skip(s, i)
        if s[i:i + 1] == ")":
            return ident, fields, i + 1
        if s[i:i + 1] != ",":
            raise _Bad("expected-comma-or-close")
        key = _KEY_TOKEN.match(s, _skip(s, i + 1))
        if key is None:
            raise _Bad("bad-key")
        name = key.group(0)
        if name not in KEYS:
            raise _Bad("unknown-key:" + name)
        if name in fields:
            raise _Bad("duplicate-key:" + name)
        i = _skip(s, key.end())
        if s[i:i + 1] != "=":
            raise _Bad("expected-equals")
        fields[name], i = _read_string(s, _skip(s, i + 1))


def _check_until(until, today):
    if DATE_RE.fullmatch(until):
        try:
            when = datetime.date.fromisoformat(until)
        except ValueError:
            raise _Bad("bad-until-date")
        if when > today + datetime.timedelta(days=HORIZON_DAYS):
            raise _Bad("until-too-far")
    elif not TASK_RE.fullmatch(until):
        raise _Bad("bad-until")


def _check_fields(fields, ctx):
    """-> (oracle, states, reason, link, until) of a parsed tag. Raises _Bad."""
    for key in KEYS:
        if key not in fields:
            raise _Bad("missing-key:" + key)
        if fields[key] == "" or fields[key] != fields[key].strip():
            raise _Bad("empty-or-padded-value:" + key)
    states = tuple(item.strip() for item in fields["state"].split(","))
    if not all(STATE_RE.fullmatch(item) for item in states) or len(set(states)) != len(states):
        raise _Bad("bad-state")
    if fields["reason"] not in REASONS:
        raise _Bad("bad-reason")
    link = fields["link"]
    if not _NO_SPACE.fullmatch(link):
        raise _Bad("bad-link")
    if fields["reason"] == "reference-bug" and not (link.startswith(ctx.link_prefix)
                                                    and ISSUE_RE.fullmatch(link[len(ctx.link_prefix):])):
        raise _Bad("reference-bug-link-not-an-oracle-issue")
    _check_until(fields["until"], ctx.today)
    return fields["oracle"], states, fields["reason"], link, fields["until"]


def tags_of(comment, path, ctx):
    """-> (tags, [(line, id or None, why)], [(line, first column, last line, end column)]) of one comment (a tuple of
    (line, text)). The last value is where every tag-shaped text stands (its own characters only), so the section reader can
    leave the tags out of its prose and nothing else."""
    text = "\n".join(part for _, part in comment)
    starts, total = [], 0
    for _, part in comment:
        starts.append(total)
        total += len(part) + 1
    linenos = [lineno for lineno, _ in comment]

    def place(offset):
        k = bisect.bisect_right(starts, offset) - 1
        return linenos[k], offset - starts[k]

    tags, bad, spans, i = [], [], [], 0
    while True:
        m = SHAPE.search(text, i)
        if m is None:
            return tuple(tags), tuple(bad), tuple(spans)
        i = m.end()
        (line, column), ident = place(m.start()), None
        clean = (m.group(0) == "@deviation" and text[i:i + 1] == "("
                 and not (m.start() and _WORD.match(text[m.start() - 1])))
        if not clean:
            bad.append((line, None, "bad-tag-start"))
            spans.append((line, column, line, column + len(m.group(0))))
            continue
        try:
            ident, fields, i = _parse(text, i)
            spans.append((line, column) + place(i))
            oracle, states, reason, link, until = _check_fields(fields, ctx)
        except _Bad as why:
            bad.append((line, ident, str(why)))
            spans.append((line, column, line, column + len(m.group(0))))
            continue
        tags.append(Tag(ident, oracle, states, reason, link, until, path, line))
