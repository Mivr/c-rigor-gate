"""`ui_deviations`: machine-readable deviation tags, their ratchet and the untagged deviation prose (P004 T1xx.13).
docs/ui-deviations.md. Split over `ui_deviations_{lex,tags,sections,baseline}.py`; this module is the analysis, the tree
walk and the command line.

A place where the kiosk knowingly differs from its oracle is written in a C comment of a product header as a tag

    @deviation(<id>, oracle="..", state="..", reason="intentional|substrate|reference-bug", link="..", until="..")

The tags are checked strictly and counted against the gate-owned baseline (`products/<product>/ui/deviations.toml`);
prose that records deviations without tags is debt (`deviation-untagged`), checked against the gate-owned
`deviation-sections.toml`. Pure functions of the file bytes, the two files and the date passed in: no clock, no locale, no
absolute path, independent of the order the files are read in. Python 3 stdlib only. A defect of an input file is a finding;
only an input the gate cannot read at all (baseline, product.toml, root, date) is an InternalError (exit 2).
"""

import datetime
import os
import stat
import tomllib
from dataclasses import dataclass

from rigor_lib import product_layout
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler
from rigor_lib.ui_deviations_baseline import (BASELINE_RELATIVE, SECTIONS_RELATIVE, Baseline, Expectation,  # noqa: F401
                                              load_baseline, load_expectation)
from rigor_lib.ui_deviations_conf import fold
from rigor_lib.ui_deviations_lex import lex
from rigor_lib.ui_deviations_sections import continuation_label_lines, is_heading, sections_of
from rigor_lib.ui_deviations_tags import (DATE_RE, REASONS, SHAPE, Context, Tag, canonical_bytes,  # noqa: F401
                                          canonical_sha256, tags_of)

GATE_ID = "ui-deviations"
MAX_BYTES = 2000000      # a file larger than this is `deviation-malformed` (file-too-large), never read
C_EXTENSIONS = frozenset(("c", "h", "inc", "def", "cc", "cpp", "cxx", "c++", "hpp", "hh", "hxx", "ipp", "tpp", "inl"))


@dataclass(frozen=True)
class FileScan:
    tags: tuple
    bad: tuple         # [(line, id or None, why)]
    sections: tuple    # [(heading line, entries)], entries 0 = no recognised entry
    splits: tuple = ()  # lines where a section continues after code (`deviation-section-split`)


def is_header(path):
    return path.lower().endswith(".h")


def _blank(spans):
    """{line: [(first column, end column or None)]} of the tag spans (line, column, line, column)."""
    out = {}
    for first, column, last, end in spans:
        for line in range(first, last + 1):
            out.setdefault(line, []).append((column if line == first else 0, end if line == last else None))
    return out


def _blanked(text, ranges):
    for start, end in ranges:
        stop = len(text) if end is None else end
        text = text[:start] + " " * (stop - start) + text[stop:]
    return text


def _confusable_tags(comment):
    return [(line, None, "confusable") for line, part in comment if len(SHAPE.findall(fold(part))) > len(SHAPE.findall(part))]


def _confusable_headings(group):
    folded = [fold(t).strip() for _, t in group]
    raw = [t.strip() for _, t in group]
    return [(n, None, "confusable") for k, (n, _) in enumerate(group)
            if is_heading(folded[k], folded[k + 1] if k + 1 < len(group) else "")
            and not is_heading(raw[k], raw[k + 1] if k + 1 < len(group) else "")]


def scan_file(path, data, ctx):
    """One file's bytes -> FileScan."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return FileScan((), ((1, None, "not-utf-8"),), ())
    comments, groups, problems = lex(text)
    tags, bad, spans, confusable = [], [(line, None, why) for line, why in problems], [], set()
    for comment in comments:
        found, broken, where = tags_of(comment, path, ctx)
        tags.extend(found)
        bad.extend(broken)
        confusable.update(line for line, _, _ in _confusable_tags(comment))
        spans.extend(where)
    covered = _blank(spans)
    # the text of a tag is not prose: its own characters are blanked before the sections are read
    clean = [tuple((n, _blanked(t, covered.get(n, ()))) for n, t in group) for group in groups]
    sections, splits, previous = [], [], None
    for group in clean:
        confusable.update(line for line, _, _ in _confusable_headings(group))
        found = sections_of(group)
        if previous is not None and previous.open:
            splits.extend(continuation_label_lines(group, previous.styles)[:1])
        sections.extend((item.line, item.entries) for item in found)
        previous = found[-1] if found else None
    bad.extend((line, None, "confusable") for line in confusable)
    return FileScan(tuple(tags), tuple(sorted(bad, key=lambda item: (item[0], item[1] or "", item[2]))), tuple(sections), tuple(splits))


def _tag_key(tag):
    return (tag.id, tag.path, tag.line)


def _file_findings(path, data, scan, expectation):
    """The findings of one scanned file (tags and prose); tree-wide rules are in `_tree_findings`."""
    found = [finding("deviation-malformed", path=path, line=line, why=why, **({} if ident is None else {"id": ident}))
             for line, ident, why in scan.bad]
    if not is_header(path):
        found += [finding("deviation-misplaced", path=path, line=tag.line, what="tag", id=tag.id) for tag in scan.tags]
        found += [finding("deviation-misplaced", path=path, line=line, what="section") for line, _ in scan.sections]
        return found
    found += [finding("deviation-unlabelled", path=path, line=line) for line, entries in scan.sections if entries == 0]
    found += [finding("deviation-section-split", path=path, line=line) for line in scan.splits]
    detected = sum(entries for _, entries in scan.sections)
    acknowledged = expectation.headers.get(path, 0)
    distinct = len({tag.id for tag in scan.tags})
    if detected == 0 and acknowledged and distinct < acknowledged:
        found.append(finding("deviation-section-missing", path=path, acknowledged=acknowledged, tags=distinct))
    elif distinct < max(detected, acknowledged):
        first = min((line for line, entries in scan.sections if entries), default=0)
        found.append(finding("deviation-untagged", path=path, line=first, entries=max(detected, acknowledged),
                             detected=detected, acknowledged=acknowledged, tags=distinct))
    return found


def analyse(files, baseline, expectation, today):
    """files: [(relative posix path, bytes or None when too large)]; today: datetime.date.
    -> (tags sorted by id, file and line, findings)."""
    ctx = Context(baseline.link_prefix, today)
    found, tags, headers = [], [], set()
    for path, data in sorted(files, key=lambda item: item[0]):
        if is_header(path):
            headers.add(path)
        if data is None:
            found.append(finding("deviation-malformed", path=path, line=0, why="file-too-large"))
            continue
        scan = scan_file(path, data, ctx)
        tags.extend(scan.tags)
        found.extend(_file_findings(path, data, scan, expectation))
    seen = sorted(path for path, _ in files)
    for path, acknowledged in sorted(expectation.headers.items()):
        if path not in headers:
            stem = path.rsplit(".", 1)[0].lower()
            actual = [p for p in seen if p.rsplit(".", 1)[0].lower() == stem]
            extra = {"actual": actual[0]} if actual else {}
            found.append(finding("deviation-section-missing", path=path, acknowledged=acknowledged, tags=0, header="absent",
                                 **extra))
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
    for ident in sorted(first):
        tag = first[ident]
        if ident not in baseline.accepted:
            found.append(finding("deviation-new", path=tag.path, line=tag.line, id=ident))
        elif baseline.accepted[ident] != (tag.until, canonical_sha256(tag)):
            found.append(finding("deviation-changed", path=tag.path, line=tag.line, id=ident))
    if len(first) > baseline.cap:
        found.append(finding("deviation-over-cap", count=len(first), cap=baseline.cap))
    for ident in sorted(set(baseline.accepted) - set(first)):
        found.append(finding("deviation-removed", SEVERITY_INFO, id=ident))
    return found


def judge_tags(tags, diverging):
    """The hook of the parity judge (not implemented here). `tags`: any iterable of Tag; `diverging`: a set of tag ids (the
    subject key of a tag is its id) whose subject really differs from the oracle. A tag in the set is `pinned-deviation`
    (info), a tag outside it is `deviation-stale` (error, a deliberate deviation from P004 8.3: docs/ui-deviations.md). A key
    that names no tag is the judge's own finding (a divergence without a tag), not reported here."""
    try:
        tags = tuple(tags)
    except TypeError:
        raise InternalError("judge_tags: `tags` must be an iterable of Tag objects")
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


def parse_today(text):
    if not isinstance(text, str) or not DATE_RE.fullmatch(text):
        raise InternalError("--today must be an ISO date YYYY-MM-DD, got %r" % (text,))
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise InternalError("--today is not a calendar date: %r" % (text,))


def _scanned(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in C_EXTENSIONS


def discover(root, config):
    """-> (sorted [(relative path, bytes or None)] of the C files the product layout copies, sorted [(path, why)]).
    A directory is skipped only when the layout itself would exclude every file below it as a gate path; a
    symlink the layout would copy is reported, never followed."""
    files, problems = [], []
    def unreadable(error):
        raise InternalError("cannot read %s: %s" % (error.filename, error.strerror))

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=unreadable):
        rel_dir = os.path.relpath(directory, root).replace(os.sep, "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        keep = []
        for name in sorted(dirs):
            verdict = product_layout.classify(config, prefix + name + "/x.h")
            if verdict == product_layout.EXCLUDED_BY_GATE:
                continue
            if not os.path.islink(os.path.join(directory, name)):
                keep.append(name)
            elif verdict == product_layout.COPY:
                problems.append((prefix + name, "symlink"))
        dirs[:] = keep
        for name in sorted(names):
            rel = prefix + name
            if not _scanned(name) or product_layout.classify(config, rel) != product_layout.COPY:
                continue
            full = os.path.join(directory, name)
            if os.path.islink(full):
                problems.append((rel, "symlink"))
            elif not stat.S_ISREG(os.lstat(full).st_mode):
                problems.append((rel, "not-a-regular-file"))
            else:
                with open(full, "rb") as handle:
                    data = handle.read(MAX_BYTES + 1)
                files.append((rel, data if len(data) <= MAX_BYTES else None))
    return sorted(files, key=lambda item: item[0]), sorted(problems)


def _one(args, name):
    values = getattr(args, name) or []
    if len(values) != 1:
        raise InternalError("--%s must be given exactly once" % name)
    return values[0]


def run(args):
    root, product, today_text = _one(args, "root"), _one(args, "product"), _one(args, "today")
    if not os.path.isdir(root):
        raise InternalError("not a directory: %s" % root)
    today = parse_today(today_text)
    try:
        config = product_layout.load_product(product)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise InternalError("%s: %s" % (product, error))
    home = os.path.dirname(os.path.abspath(product))
    baseline = load_baseline(os.path.join(home, BASELINE_RELATIVE), config.name, today)
    expectation = load_expectation(os.path.join(home, SECTIONS_RELATIVE), config.name)
    files, problems = discover(root, config)
    tags, found = analyse(files, baseline, expectation, today)
    found = list(found) + [finding("deviation-malformed", path=path, line=0, why=why) for path, why in problems]
    meta = {"product": config.name, "files": len(files), "tags": len(tags), "today": today_text}
    return GateResult(GATE_ID, found, meta)


def add_parser(subparsers):
    parser = subparsers.add_parser("ui-deviations", allow_abbrev=False,
                                   help="deviation tags, their baseline and untagged deviation prose (docs/ui-deviations.md)")
    parser.add_argument("--root", action="append", help="the product tree (read only)")
    parser.add_argument("--product", action="append", help="products/<name>/product.toml")
    parser.add_argument("--today", action="append",
                        help="ISO date YYYY-MM-DD; the wall clock is never read; each of the three options is required, exactly once")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
