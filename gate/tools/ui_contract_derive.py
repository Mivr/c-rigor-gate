#!/usr/bin/env -S python3 -I
"""Re-derive the timers of the UI contract from `ui-rules.md` and fail if the checked-in contract disagrees.

    gate/tools/ui_contract_derive.py --ui-rules PATH --contract PATH [--print]

Reads the "Screen timers" and "Message catalogue" tables of ui-rules.md, derives for every timer kind its limit and
whether a countdown is shown, and compares with the `[[timer]]` rows of the contract (kind set, `lifetime_ms`,
`countdown_shown`). `--print` writes the derived table as `kind lifetime_ms countdown_shown` lines. Exit 0: they
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

# The first column of the "Screen timers" table, as ui-rules.md writes it, to the contract's timer kind.
SCREEN_ROWS = {
    "Choose a size": "choose_size",
    "Opened": "opened",
    "Rejection, no-locker, and operational fault dialogs": "dialog",
    "End-of-shift report": "report",
    "Lockout": "lockout",
    "Reservation saved snackbar": "snackbar",
}
MESSAGE_KINDS = {"Dialog": "dialog", "Banner": "banner", "Snackbar": "snackbar"}
_LIMIT = re.compile(r"^(\d+) (s|min)$")


def _fail(why):
    raise InternalError("ui-contract-derive: %s" % why)


def table_rows(text, heading):
    """The body rows (lists of cells) of the first markdown table under the `## heading` line."""
    lines = text.splitlines()
    try:
        start = lines.index("## " + heading)
    except ValueError:
        _fail("ui-rules.md has no section '## %s'" % heading)
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            break
    if len(rows) < 3:
        _fail("section '%s' has no table" % heading)
    return rows[2:]   # the header and the separator row are dropped


def limit_ms(cell, where):
    """'30 s' -> 30000, '5 min' -> 300000, 'None' -> 0 (no limit)."""
    if cell == "None":
        return 0
    found = _LIMIT.match(cell)
    if found is None:
        _fail("%s: cannot read the limit %r" % (where, cell))
    return int(found.group(1)) * (1000 if found.group(2) == "s" else 60000)


def derive(text):
    """{kind: (lifetime_ms, countdown_shown)} from the two tables."""
    derived = {}
    for cells in table_rows(text, "Screen timers"):
        if len(cells) != 4 or cells[0] not in SCREEN_ROWS:
            _fail("Screen timers: unknown or malformed row %r (extend SCREEN_ROWS only with the owner)" % cells[:1])
        derived[SCREEN_ROWS[cells[0]]] = (limit_ms(cells[1], cells[0]), cells[2].startswith("Countdown"))
    if set(derived) != set(SCREEN_ROWS.values()):
        _fail("Screen timers: rows missing: %s" % ", ".join(sorted(set(SCREEN_ROWS.values()) - set(derived))))
    seen = {}
    for cells in catalogue_rows(text):
        kind = MESSAGE_KINDS.get(cells[1])
        if kind is not None:
            seen.setdefault(kind, set()).add(limit_ms(cells[4], cells[0]))
    for kind, limits in sorted(seen.items()):
        if len(limits) != 1:
            _fail("Message catalogue: kind %s has several limits %s" % (kind, sorted(limits)))
        limit = limits.pop()
        if kind in derived and derived[kind][0] != limit:
            _fail("ui-rules.md contradicts itself: %s is %d ms in one table and %d ms in the other"
                  % (kind, derived[kind][0], limit))
        derived.setdefault(kind, (limit, limit > 0))
    if set(seen) != set(MESSAGE_KINDS.values()):
        _fail("Message catalogue: no row of kind %s" % ", ".join(sorted(set(MESSAGE_KINDS.values()) - set(seen))))
    return derived


def catalogue_rows(text):
    return [cells for cells in table_rows(text, "Message catalogue") if len(cells) == 5]


def compare(derived, contract):
    """Differences between the derived table and the contract's timers, as sorted strings."""
    have = {r["kind"]: (r["lifetime_ms"], r["countdown_shown"]) for r in contract.tables["timer"]}
    out = []
    for kind in sorted(set(derived) | set(have)):
        if kind not in have:
            out.append("timer %s: derived from ui-rules.md but missing in the contract" % kind)
        elif kind not in derived:
            out.append("timer %s: in the contract but not in ui-rules.md" % kind)
        elif derived[kind] != have[kind]:
            out.append("timer %s: ui-rules.md gives (lifetime_ms, countdown_shown) = %r, the contract %r"
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
            print("%s %d %s" % (kind, derived[kind][0], str(derived[kind][1]).lower()))
    differences = compare(derived, contract)
    for line in differences:
        print(line, file=sys.stderr)
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
