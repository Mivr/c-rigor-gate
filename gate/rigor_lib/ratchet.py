"""`rigor ratchet`: tracked numbers and sets may only move in the direction the spec allows.

old/new files: flat TOML, each key is a number or a list of strings.
spec file: one table per key, e.g.  [max_mutants]  direction = "down"
Directions: "down" (numbers may not rise), "up" (numbers may not fall),
"shrink" (a set of strings may not gain elements).
An approval of kind `ratchet` with scope `<file name of --new>:<key>` allows one regression.
"""

import math
import os
import tomllib

from rigor_lib import approval_args, approvals, jsonio
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "ratchet"
DOWN = "down"
UP = "up"
SHRINK = "shrink"
DIRECTIONS = (DOWN, UP, SHRINK)


def load_toml(path):
    try:
        return tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (path, exc)) from exc


def load_spec(path):
    """key -> direction. The spec is gate-owned, so any defect is an internal error."""
    table = load_toml(path)
    if not table:
        raise InternalError("ratchet spec is empty")
    spec = {}
    for key, entry in table.items():
        if not isinstance(entry, dict) or set(entry) != {"direction"}:
            raise InternalError("spec entry %r must be a table with only 'direction'" % key)
        if entry["direction"] not in DIRECTIONS:
            raise InternalError("spec entry %r has an unknown direction" % key)
        spec[key] = entry["direction"]
    return spec


def _is_finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not (isinstance(value, float) and not math.isfinite(value))


def value_problem(direction, value):
    """Why `value` does not fit `direction`, or None."""
    if direction == SHRINK:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return "not-string-list"
        if len(set(value)) != len(value):
            return "duplicate-elements"
        return None
    if not _is_finite_number(value):
        return "not-finite-number"
    return None


def regression_fields(direction, old, new):
    """Finding fields describing a wrong-way move, or None if the move is allowed."""
    if direction == DOWN and new > old:
        return {"old": old, "new": new}
    if direction == UP and new < old:
        return {"old": old, "new": new}
    if direction == SHRINK:
        added = sorted(set(new) - set(old))
        if added:
            return {"added": added}
    return None


def _bad_value_findings(key, direction, old, new):
    found = []
    for side, table in (("old", old), ("new", new)):
        if key in table:
            reason = value_problem(direction, table[key])
            if reason is not None:
                found.append(finding("bad-value", key=key, side=side, reason=reason))
    return found


def key_findings(key, direction, old, new, scope_file, approval_set, used):
    if key not in new:
        return [finding("missing-key", key=key)]
    problems = _bad_value_findings(key, direction, old, new)
    if problems:
        return problems
    if key not in old:
        return [finding("new-key", severity=SEVERITY_INFO, key=key)]
    fields = regression_fields(direction, old[key], new[key])
    if fields is None:
        return []
    approval = approval_set.covering(approvals.KIND_RATCHET, "%s:%s" % (scope_file, key))
    if approval is None:
        return [finding("ratchet-regressed", key=key, **fields)]
    used.add(approval.stem)
    return []


def run(args):
    spec = load_spec(args.spec)
    old = load_toml(args.old)
    new = load_toml(args.new)
    approval_set = approval_args.load_from_args(args)
    scope_file = os.path.basename(args.new)
    used = set()
    found = list(approval_set.problems)
    for key in sorted(spec):
        found.extend(key_findings(key, spec[key], old, new, scope_file, approval_set, used))
    for key in sorted(set(new) - set(spec)):
        found.append(finding("unspecified-key", key=key))
    return GateResult(GATE_ID, found, {"approvals_used": sorted(used), "scope_file": scope_file})


def add_parser(subparsers):
    parser = subparsers.add_parser("ratchet", allow_abbrev=False,
                                   help="tracked values may only move the allowed way")
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out")
    approval_args.add_approval_arguments(parser, repo_and_head_optional=True)
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
