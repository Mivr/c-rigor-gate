"""`ui_deviations`: machine-readable deviation tags and their ratchet (P004 T1xx.13, gate half). docs/ui-deviations.md.

A place where the kiosk knowingly differs from its oracle is written in a C comment of a product header as

    @deviation(<id>, oracle="..", state="..", reason="intentional|substrate|reference-bug", link="..", until="..")

This module finds the tags (comments only), checks them strictly, counts them against an owner-sealed baseline
(`products/<product>/ui/deviations.toml`) and reports header prose that lists deviations without tags. Pure functions
of the file bytes, the baseline and the date passed in: no clock, no locale, no absolute path, independent of the order
the files are read in. Python 3 stdlib only. A defect of an input is a finding; only an input the gate cannot read at all
(baseline, product.toml, root, date) is an InternalError (exit 2).
"""

import datetime
import os
import re
import stat
import tomllib
from dataclasses import dataclass

from rigor_lib import jsonio, product_layout
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "ui-deviations"
SCHEMA = "ui-deviations/1"
REASONS = ("intentional", "substrate", "reference-bug")
KEYS = ("oracle", "state", "reason", "link", "until")
BASELINE_KEYS = ("schema", "product", "cap", "accepted", "reference_bug_link_pattern")
BASELINE_RELATIVE = "ui/deviations.toml"   # next to product.toml: products/<product>/ui/deviations.toml
TAG = "@deviation"

ID_RE = re.compile(r"[A-Z][A-Z0-9]*-[A-Z0-9.-]+")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TASK_RE = re.compile(r"[A-Z][A-Z0-9]*-?[0-9]+")
STATE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")
_NO_SPACE = re.compile(r"\S+")
_ID_TOKEN = re.compile(r'[^\s,()="]+')
_KEY_TOKEN = re.compile(r"[A-Za-z_]+")
_TAG_START = re.compile(re.escape(TAG) + r"(?![A-Za-z0-9_])")
_PRECEDED = re.compile(r"[A-Za-z0-9_@]")
HEADING = re.compile(r"(?:-{2,}[ \t]*)?DISAGREEMENTS(?![A-Za-z0-9_])")
RULE = re.compile(r"-{3,}")
LINE_MARK = re.compile(r"(?:[A-Z]{1,3}[0-9]{1,3}|[0-9]{1,3}[.)]|\([0-9]{1,3}\)|[-*+])[ \t]+\S")
INLINE_MARK = re.compile(r"\(([0-9]{1,3})\)")
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
class Baseline:
    product: str
    cap: int
    accepted: tuple
    link_pattern: str


class _Bad(Exception):
    """One malformed tag; the text is a short stable reason code."""


# ---------------------------------------------------------------------------------------------
# lexer: comments only
# ---------------------------------------------------------------------------------------------

def _logical(text):
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


def _content_lines(s, lnums, start, body, first_strip):
    """[(line number, text)] of a comment body, block decoration (leading `*`) removed."""
    out, offset = [], start
    for k, part in enumerate(body.split("\n")):
        lineno = lnums[min(offset, len(lnums) - 1)]
        out.append((lineno, re.sub(first_strip if k == 0 else r"^[ \t]*\*?", "", part)))
        offset += len(part) + 1
    return out


def lex_comments(text):
    """-> (comments, problems). A comment is a tuple of (line, text); consecutive `//` lines form one comment.
    A tag or section inside `#if 0` text is still read: comments are removed before directives run (C17 5.1.1.2)."""
    s, lnums = _logical(text)
    comments, problems, i, n, last_line_end = [], [], 0, len(s), None
    while i < n:
        c = s[i]
        if c == "/" and s[i + 1:i + 2] == "*":
            end = s.find("*/", i + 2)
            if end < 0:
                problems.append((lnums[i], "unterminated-comment"))
                break
            comments.append(tuple(_content_lines(s, lnums, i + 2, s[i + 2:end], r"^\*?")))
            i, last_line_end = end + 2, None
        elif c == "/" and s[i + 1:i + 2] == "/":
            end = s.find("\n", i)
            end = n if end < 0 else end
            part = _content_lines(s, lnums, i + 2, s[i + 2:end], r"^$")
            if last_line_end is not None and part[0][0] == last_line_end + 1:
                comments[-1] = comments[-1] + tuple(part)
            else:
                comments.append(tuple(part))
            last_line_end = lnums[end - 1] if end > i else lnums[i]
            i = end
        elif c in "\"'":
            after = _skip_literal(s, i, c)
            if after is None:
                problems.append((lnums[i], "unterminated-literal"))
                after = s.find("\n", i)
                after = n if after < 0 else after
            i = after
        else:
            i += 1
    return tuple(comments), tuple(problems)


# ---------------------------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------------------------

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
        i += 1
    raise _Bad("unterminated-tag")


def _parse(s, i):
    """s[i] follows `@deviation`. -> (id, {key: value}, end index). Raises _Bad."""
    if s[i:i + 1] != "(":
        raise _Bad("missing-paren")
    i = _skip(s, i + 1)
    token = _ID_TOKEN.match(s, i)
    if token is None or not ID_RE.fullmatch(token.group(0)):
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


def _check_fields(ident, fields, link_pattern):
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
    if not _NO_SPACE.fullmatch(fields["link"]):
        raise _Bad("bad-link")
    if fields["reason"] == "reference-bug" and not re.fullmatch(link_pattern, fields["link"]):
        raise _Bad("reference-bug-link-not-an-oracle-issue")
    until = fields["until"]
    if DATE_RE.fullmatch(until):
        try:
            datetime.date.fromisoformat(until)
        except ValueError:
            raise _Bad("bad-until-date")
    elif not TASK_RE.fullmatch(until):
        raise _Bad("bad-until")
    return fields["oracle"], states, fields["reason"], fields["link"], until


def _tags_of(comment, path, link_pattern):
    """-> (tags, [(line, id or None, why)]) of one comment."""
    text = "\n".join(part for _, part in comment)
    starts, total = [], 0
    for lineno, part in comment:
        starts.append((total, lineno))
        total += len(part) + 1

    def line_at(index):
        found = starts[0][1]
        for offset, lineno in starts:
            if offset <= index:
                found = lineno
        return found

    tags, bad, i = [], [], 0
    while True:
        m = _TAG_START.search(text, i)
        if m is None:
            return tuple(tags), tuple(bad)
        i = m.end()
        if m.start() and _PRECEDED.match(text[m.start() - 1]):
            continue
        line, ident = line_at(m.start()), None
        try:
            ident, fields, i = _parse(text, m.end())
            oracle, states, reason, link, until = _check_fields(ident, fields, link_pattern)
        except _Bad as why:
            bad.append((line, ident, str(why)))
            continue
        tags.append(Tag(ident, oracle, states, reason, link, until, path, line))


# ---------------------------------------------------------------------------------------------
# DISAGREEMENTS sections
# ---------------------------------------------------------------------------------------------

def count_entries(lines):
    """Entries of one section (`lines`: its stripped text lines, the heading first). Defined in docs/ui-deviations.md:
    the larger of (a) lines that start with a label (`L1`, `1.`, `1)`, `(1)`, or a `-`/`*`/`+` bullet) and (b) the
    longest in-order chain `(1)`, `(2)`, ... anywhere in the section; a section with neither counts as one entry."""
    starts = sum(1 for line in lines if LINE_MARK.match(line))
    expected = 1
    for m in INLINE_MARK.finditer(" ".join(lines)):
        if int(m.group(1)) == expected:
            expected += 1
    return max(starts, expected - 1, 1)


def sections(comment):
    """-> [(heading line number, entries)] of the DISAGREEMENTS sections of one comment. A section runs from its
    heading to the next `----` rule line or the end of the comment."""
    found, current, first = [], None, 0
    for lineno, part in comment:
        stripped = part.strip()
        if HEADING.match(stripped):
            if current is not None:
                found.append((first, count_entries(current)))
            current, first = [stripped], lineno
        elif current is not None and RULE.match(stripped):
            found.append((first, count_entries(current)))
            current = None
        elif current is not None:
            current.append(stripped)
    if current is not None:
        found.append((first, count_entries(current)))
    return found


# ---------------------------------------------------------------------------------------------
# one header, the whole tree
# ---------------------------------------------------------------------------------------------

def scan_header(path, data, link_pattern):
    """-> (tags, malformed [(line, id, why)], section list [(line, entries)]) of one header's bytes."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return (), ((1, None, "not-utf-8"),), ()
    comments, lex_problems = lex_comments(text)
    tags, bad, secs = [], [(line, None, why) for line, why in lex_problems], []
    for comment in comments:
        found, broken = _tags_of(comment, path, link_pattern)
        tags.extend(found)
        bad.extend(broken)
        secs.extend(sections(comment))
    return tuple(tags), tuple(bad), tuple(secs)


def _tag_key(tag):
    return (tag.id, tag.path, tag.line)


def analyse(files, baseline, today):
    """files: [(relative posix path, bytes)]; today: datetime.date. -> (tags sorted by id, file and line, findings)."""
    found, tags = [], []
    for path, data in sorted(files):
        file_tags, bad, secs = scan_header(path, data, baseline.link_pattern)
        tags.extend(file_tags)
        for line, ident, why in bad:
            extra = {} if ident is None else {"id": ident}
            found.append(finding("deviation-malformed", path=path, line=line, why=why, **extra))
        entries = sum(count for _, count in secs)
        if secs and len(file_tags) < entries:
            found.append(finding("deviation-untagged", path=path, line=secs[0][0], entries=entries,
                                 tags=len(file_tags)))
    tags.sort(key=_tag_key)
    found.extend(_tree_findings(tags, baseline, today))
    return tuple(tags), tuple(found)


def _tree_findings(tags, baseline, today):
    found, first = [], {}
    for tag in tags:
        if tag.id in first:
            found.append(finding("deviation-malformed", path=tag.path, line=tag.line, id=tag.id, why="duplicate-id",
                                 first="%s:%d" % (first[tag.id].path, first[tag.id].line)))
        else:
            first[tag.id] = tag
        if DATE_RE.fullmatch(tag.until) and datetime.date.fromisoformat(tag.until) < today:
            found.append(finding("deviation-expired", path=tag.path, line=tag.line, id=tag.id, until=tag.until))
    accepted = set(baseline.accepted)
    for ident in sorted(first):
        if ident not in accepted:
            found.append(finding("deviation-new", path=first[ident].path, line=first[ident].line, id=ident))
    if len(first) > baseline.cap:
        found.append(finding("deviation-over-cap", count=len(first), cap=baseline.cap))
    for ident in sorted(accepted - set(first)):
        found.append(finding("deviation-removed", SEVERITY_INFO, id=ident))
    return found


def judge_tags(tags, diverging):
    """The hook of the parity judge (not implemented here). `tags`: Tag objects; `diverging`: a set of tag ids (the
    subject key of a tag is its id) whose subject really differs from the oracle. A tag in the set is
    `pinned-deviation` (info), a tag outside it is `deviation-stale` (error: it no longer diverges, delete it).
    A key that names no tag is the judge's own finding (a divergence without a tag), not reported here."""
    if not isinstance(diverging, (set, frozenset)) or not all(type(key) is str for key in diverging):
        raise InternalError("judge_tags: `diverging` must be a set of tag ids")
    if not all(isinstance(tag, Tag) for tag in tags):
        raise InternalError("judge_tags: `tags` must be Tag objects")
    out = []
    for tag in sorted(tags, key=_tag_key):
        rule, severity = (("pinned-deviation", SEVERITY_INFO) if tag.id in diverging
                          else ("deviation-stale", SEVERITY_ERROR))
        out.append(finding(rule, severity, path=tag.path, line=tag.line, id=tag.id))
    return tuple(out)


# ---------------------------------------------------------------------------------------------
# the baseline and the tree walk
# ---------------------------------------------------------------------------------------------

def parse_today(text):
    if not isinstance(text, str) or not DATE_RE.fullmatch(text):
        raise InternalError("--today must be an ISO date YYYY-MM-DD, got %r" % (text,))
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise InternalError("--today is not a calendar date: %r" % (text,))


def load_baseline(path, product):
    """The strict loader of `deviations.toml`: exactly the five keys, `accepted` strictly sorted valid ids."""
    try:
        table = tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise InternalError("%s: %s" % (path, error))
    if set(table) != set(BASELINE_KEYS):
        raise InternalError("%s: keys must be exactly %s" % (path, sorted(BASELINE_KEYS)))
    if table["schema"] != SCHEMA:
        raise InternalError("%s: schema must be %r" % (path, SCHEMA))
    if table["product"] != product:
        raise InternalError("%s: product must be %r" % (path, product))
    cap, accepted, pattern = table["cap"], table["accepted"], table["reference_bug_link_pattern"]
    if type(cap) is not int or cap < 0:
        raise InternalError("%s: cap must be an integer >= 0" % path)
    if (not isinstance(accepted, list) or not all(type(i) is str and ID_RE.fullmatch(i) for i in accepted)
            or accepted != sorted(set(accepted))):
        raise InternalError("%s: accepted must be a sorted list of unique valid ids" % path)
    if len(accepted) > cap:
        raise InternalError("%s: more accepted ids than the cap" % path)
    if type(pattern) is not str or not pattern:
        raise InternalError("%s: reference_bug_link_pattern must be a non-empty string" % path)
    try:
        re.compile(pattern)
    except re.error as error:
        raise InternalError("%s: reference_bug_link_pattern: %s" % (path, error))
    return Baseline(product, cap, tuple(accepted), pattern)


def _header(name):
    return name.lower().endswith(".h")


def discover(root, config):
    """-> (sorted [(relative path, bytes)] of the headers the product layout copies, sorted [(path, why)])."""
    files, problems = [], []
    for directory, dirs, names in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(directory, root).replace(os.sep, "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        keep = []
        for name in sorted(dirs):
            full = os.path.join(directory, name)
            if product_layout.is_gate_excluded(prefix + name + "/x"):
                continue
            if not os.path.islink(full):
                keep.append(name)
            elif product_layout.classify(config, prefix + name + "/x.h") == product_layout.COPY:
                problems.append((prefix + name, "symlink"))   # a header below it would be graded: it cannot be read
        dirs[:] = keep
        for name in sorted(names):
            rel = prefix + name
            if not _header(name) or product_layout.classify(config, rel) != product_layout.COPY:
                continue
            full = os.path.join(directory, name)
            if os.path.islink(full):
                problems.append((rel, "symlink"))
            elif not stat.S_ISREG(os.lstat(full).st_mode):
                problems.append((rel, "not-a-regular-file"))
            else:
                files.append((rel, jsonio.read_bytes(full)))
    return sorted(files), sorted(problems)


def run(args):
    if not os.path.isdir(args.root):
        raise InternalError("not a directory: %s" % args.root)
    today = parse_today(args.today)
    try:
        config = product_layout.load_product(args.product)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise InternalError("%s: %s" % (args.product, error))
    baseline = load_baseline(os.path.join(os.path.dirname(os.path.abspath(args.product)), BASELINE_RELATIVE),
                             config.name)
    files, problems = discover(args.root, config)
    tags, found = analyse(files, baseline, today)
    found = list(found) + [finding("deviation-malformed", path=path, line=0, why=why) for path, why in problems]
    meta = {"product": config.name, "headers": len(files), "tags": len(tags), "today": args.today}
    return GateResult(GATE_ID, found, meta)


def add_parser(subparsers):
    parser = subparsers.add_parser("ui-deviations", allow_abbrev=False,
                                   help="deviation tags, their baseline and untagged DISAGREEMENTS (docs/ui-deviations.md)")
    parser.add_argument("--root", required=True, help="the product tree (read only)")
    parser.add_argument("--product", required=True, help="products/<name>/product.toml")
    parser.add_argument("--today", required=True, help="ISO date YYYY-MM-DD; the wall clock is never read")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
