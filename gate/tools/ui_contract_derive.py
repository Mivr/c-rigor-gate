#!/usr/bin/env -S python3 -I
"""Re-derive the timers of the UI contract from `ui-rules.md` and fail if the checked-in contract disagrees.

    gate/tools/ui_contract_derive.py --ui-rules PATH --contract PATH [--print]

Reads the "Screen timers" and "Message catalogue" tables of ui-rules.md, derives for every timer kind its limit and
whether a countdown is shown, and compares with the `[[timer]]` rows of the contract (kind set, `class`,
`lifetime_ms`, `countdown_shown`, `dismiss`). `--print` writes `kind class lifetime_ms countdown_shown dismiss`
lines. Exit 0: they
agree. Exit 1: they differ (each difference on stderr). Exit 2: an unreadable or unrecognised input.
"""

import argparse
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

from rigor_lib import jsonio, ui_contract  # noqa: E402
from rigor_lib.errors import InternalError  # noqa: E402

# The first column of the "Screen timers" table, as ui-rules.md writes it, to (timer kind, class).
SCREEN_ROWS = {
    "Choose a size": ("choose_size", "screen"),
    "Opened": ("opened", "screen"),
    "Rejection, no-locker, and operational fault dialogs": ("dialog", "message"),
    "End-of-shift report": ("report", "screen"),
    "Lockout": ("lockout", "screen"),
    "Reservation saved snackbar": ("snackbar", "message"),
}
MESSAGE_KINDS = {"Dialog": "dialog", "Banner": "banner", "Snackbar": "snackbar"}
# Rows of the Message catalogue that are not a notice (their Kind cell), named so that nothing else is skipped.
NOT_A_NOTICE = ("Part of the report screen, not a notice",)
SCREEN_HEADER = ("Screen or notice", "Limit", "What the visitor sees", "Dismiss")
CATALOGUE_HEADER = ("Message", "Kind", "Underneath", "Dismiss intent", "Countdown")
_LIMIT = re.compile(r"^(\d+) (s|min)$")


def _fail(why):
    raise InternalError("ui-contract-derive: %s" % why)


def table_rows(text, heading, header):
    """The body rows (lists of cells) of the table under the `## heading` line. The header row must be `header`;
    every row must have exactly as many cells; an escaped pipe is refused."""
    lines = text.splitlines()
    if lines.count("## " + heading) != 1:
        _fail("ui-rules.md must have exactly one section '## %s'" % heading)
    rows = []
    for line in lines[lines.index("## " + heading) + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            if "\\|" in line:
                _fail("%s: an escaped pipe in a table row is not supported: %r" % (heading, line[:60]))
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            break
    if len(rows) < 3 or tuple(rows[0]) != header:
        _fail("section '%s' has no table with the header %s" % (heading, " | ".join(header)))
    for row in rows[1:]:
        if len(row) != len(header):
            _fail("%s: a row has %d cells, not %d: %r" % (heading, len(row), len(header), row[:1]))
    return rows[2:]   # the header and the separator row are dropped


def limit_ms(cell, where):
    """'30 s' -> 30000, '5 min' -> 300000, 'None' -> 0 (no limit)."""
    if cell == "None":
        return 0
    found = _LIMIT.match(cell)
    if found is None:
        _fail("%s: cannot read the limit %r" % (where, cell))
    return int(found.group(1)) * (1000 if found.group(2) == "s" else 60000)


def dismiss_list(cell, where):
    """The dismiss controls named by the first sentence of a Dismiss cell: '**Done**, or the countdown. ...'."""
    first = cell.split(". ")[0].rstrip(".")
    if first == "None":
        return ()
    items = []
    for part in first.split(","):
        word = re.sub(r"^(or )?(the )?", "", part.replace("**", "").strip().lower()).replace(" ", "-")
        if not re.fullmatch(r"[a-z][a-z-]*", word):
            _fail("%s: cannot read the dismiss control %r" % (where, part))
        items.append(word)
    return tuple(items)


def derive(text):
    """{kind: (class, lifetime_ms, countdown_shown, dismiss)} from the two tables."""
    derived = {}
    for cells in table_rows(text, "Screen timers", SCREEN_HEADER):
        if cells[0] not in SCREEN_ROWS:
            _fail("Screen timers: unknown row %r (extend SCREEN_ROWS only with the owner)" % cells[0])
        kind, klass = SCREEN_ROWS[cells[0]]
        if kind in derived:
            _fail("Screen timers: duplicate row for %s" % kind)
        derived[kind] = (klass, limit_ms(cells[1], cells[0]), cells[2].startswith("Countdown"),
                         dismiss_list(cells[3], cells[0]))
    if set(derived) != {kind for kind, _ in SCREEN_ROWS.values()}:
        _fail("Screen timers: rows missing")
    limits, dismissed = {}, {}
    for cells in table_rows(text, "Message catalogue", CATALOGUE_HEADER):
        kind = MESSAGE_KINDS.get(cells[1])
        if kind is None:
            if cells[1] not in NOT_A_NOTICE:
                _fail("Message catalogue: unknown kind %r in row %r" % (cells[1], cells[0]))
            continue
        limits.setdefault(kind, set()).add(limit_ms(cells[4], cells[0]))
        dismissed.setdefault(kind, set()).add(cells[3] != "None" and cells[3] != "")
    if set(limits) != set(MESSAGE_KINDS.values()):
        _fail("Message catalogue: no row of kind %s" % ", ".join(sorted(set(MESSAGE_KINDS.values()) - set(limits))))
    for kind in sorted(limits):
        if len(limits[kind]) != 1:
            _fail("Message catalogue: kind %s has several limits %s" % (kind, sorted(limits[kind])))
        if dismissed[kind] != {True}:
            _fail("Message catalogue: a %s row has no dismiss intent (every message can be dismissed)" % kind)
        limit = next(iter(limits[kind]))
        if kind in derived and derived[kind][1] != limit:
            _fail("ui-rules.md contradicts itself: %s is %d ms in one table and %d ms in the other"
                  % (kind, derived[kind][1], limit))
        derived.setdefault(kind, ("message", limit, limit > 0, ("dismiss",)))
    return derived


def compare(derived, contract):
    """Differences between the derived table and the contract's timers, as sorted strings."""
    have = {r["kind"]: (r["class"], r["lifetime_ms"], r["countdown_shown"], tuple(r["dismiss"]))
            for r in contract.tables["timer"]}
    out = []
    for kind in sorted(set(derived) | set(have)):
        if kind not in have:
            out.append("timer %s: derived from ui-rules.md but missing in the contract" % kind)
        elif kind not in derived:
            out.append("timer %s: in the contract but not in ui-rules.md" % kind)
        elif derived[kind] != have[kind]:
            out.append("timer %s: ui-rules.md gives (class, lifetime_ms, countdown_shown, dismiss) = %r, the contract %r"
                       % (kind, derived[kind], have[kind]))
    return out


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ui-rules", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--print", action="store_true", dest="show")
    args = parser.parse_args(argv)
    try:
        derived = derive(jsonio.read_bytes(args.ui_rules).decode("utf-8"))
        contract = ui_contract.load(args.contract)
    except (InternalError, UnicodeDecodeError, OSError) as error:
        print("ui_contract_derive: %s" % error, file=sys.stderr)
        return 2
    if args.show:
        for kind in sorted(derived):
            klass, limit, shown, dismiss = derived[kind]
            print("%s %s %d %s %s" % (kind, klass, limit, str(shown).lower(), ",".join(dismiss) or "-"))
    differences = compare(derived, contract)
    for line in differences:
        print(line, file=sys.stderr)
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
