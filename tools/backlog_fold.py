#!/usr/bin/env python3
"""Fold plan/backlog.d/ into plan/backlog.md (T047).

plan/backlog.md is generated; never edit it by hand. Each row is one fragment, plan/backlog.d/B<N>.md:

    found_by: <text, one line>
    fix: <text, one line>
    <blank line>
    <gap text, one line>

An optional third header line, "closing_pipe: no", omits the row's final " |" (today's B21 has none).
An empty fix is written "fix:" and renders as "| |" (today's B25).
The row id comes from the file name (B<N>, N >= 1, no leading zero). plan/backlog.d/_header.md holds the title and
the table header, verbatim. Rows are sorted by N. Cells must be one line, non-empty, and must not contain a
'|' outside a `code span` unless escaped as \\| (B21 and B28 have pipes inside code spans).

Usage: python3 -I tools/backlog_fold.py [--check] [--root DIR]
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

NAME = re.compile(r"B([1-9][0-9]*)\.md\Z")
KEYS = ("found_by", "fix")
OPTIONAL = ("closing_pipe",)  # "no" omits the row's final " |" (legacy B21 only)
CODE_SPAN = re.compile(r"`[^`]*`")


class FoldError(Exception):
    pass


def check_cell(where, label, text):
    if not text or text != text.strip():
        raise FoldError(f"{where}: {label} is empty or has leading/trailing whitespace")
    if "\n" in text or "\r" in text:
        raise FoldError(f"{where}: {label} contains a newline")
    if re.search(r"(?<!\\)\|", CODE_SPAN.sub("", text)):
        raise FoldError(f"{where}: {label} contains a '|' that would break the table")


def parse_fragment(path):
    where = path.name
    lines = path.read_text(encoding="utf-8").split("\n")
    fields = {}
    i = 0
    while i < len(lines) and lines[i] != "":
        key, sep, val = lines[i].partition(": ")
        if lines[i] == "fix:":  # an empty planned fix (legacy B25)
            key, sep, val = "fix", ": ", ""
        if not sep or key not in KEYS + OPTIONAL or key in fields:
            raise FoldError(f"{where}: line {i + 1}: expected one of {KEYS + OPTIONAL} as 'key: value', each once")
        fields[key] = val
        i += 1
    if not set(KEYS) <= set(fields):
        raise FoldError(f"{where}: missing header line(s): {sorted(set(KEYS) - set(fields))}")
    if fields.get("closing_pipe", "yes") not in ("yes", "no"):
        raise FoldError(f"{where}: closing_pipe must be yes or no")
    if i >= len(lines):
        raise FoldError(f"{where}: no blank line before the gap text")
    rest = lines[i + 1:]
    if len(rest) != 2 or rest[1] != "":
        raise FoldError(f"{where}: the gap must be exactly one line ending in a single newline")
    gap = rest[0]
    for label, text in (("found_by", fields["found_by"]), ("fix", fields["fix"]), ("gap", gap)):
        if label != "fix" or text:
            check_cell(where, label, text)
    if not fields["fix"] and fields.get("closing_pipe", "yes") != "yes":
        raise FoldError(f"{where}: an empty fix cannot combine with closing_pipe: no")
    return gap, fields["found_by"], fields["fix"], fields.get("closing_pipe", "yes") == "yes"


def fold(root):
    d = root / "plan" / "backlog.d"
    if not d.is_dir():
        raise FoldError(f"{d} is not a directory")
    header = d / "_header.md"
    if not header.is_file():
        raise FoldError("plan/backlog.d/_header.md is missing")
    rows = {}
    for p in sorted(d.iterdir()):
        if p.name == "_header.md":
            continue
        m = NAME.match(p.name)
        if not m or not p.is_file():
            raise FoldError(f"{p.name}: not a fragment name (expected B<N>.md, N >= 1, no leading zero)")
        n = int(m.group(1))
        if n in rows:
            raise FoldError(f"duplicate id B{n}")
        rows[n] = parse_fragment(p)
    out = [header.read_text(encoding="utf-8")]
    for n in sorted(rows):
        gap, found_by, fix, closed = rows[n]
        tail = (fix + (" |" if closed else "")) if fix else "|"
        out.append(f"| B{n} | {gap} | {found_by} | {tail}\n")
    return "".join(out)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if plan/backlog.md differs from the fold")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args(argv)
    target = args.root / "plan" / "backlog.md"
    try:
        text = fold(args.root)
    except FoldError as e:
        print(f"backlog_fold: {e}", file=sys.stderr)
        return 2
    if args.check:
        have = target.read_text(encoding="utf-8") if target.is_file() else ""
        if have == text:
            return 0
        sys.stdout.writelines(difflib.unified_diff(
            have.splitlines(True), text.splitlines(True), "plan/backlog.md", "fold(plan/backlog.d)"))
        print("backlog_fold: plan/backlog.md is stale; run tools/backlog_fold.py", file=sys.stderr)
        return 1
    target.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
