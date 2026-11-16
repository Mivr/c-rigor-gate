"""The optional catalogue tables of U05e (docs/ui-explore.md, "The event catalogue"): `taps` (state-scoped taps and
the layer target of an intent), `[boot]` (the boot seeds), `[[prefix]]` (word lists a bfs starts after) and a pad
macro's `digit_map`. Strict: an unknown key, a wrong type, a value out of range or a provenance of the wrong form is
the gate's input error (exit 2). A catalogue without them loads exactly as before."""

import re
from dataclasses import dataclass

from rigor_lib import ui_contract
from rigor_lib.errors import InternalError

TAP_SCOPES = ("fixed", "scene")
INTENT_NODES = ("key", "intent")      # how a u1 intent names its scene node: by node key, or by its `intent:arg`
_TAPS_KEYS = ("scope", "provenance")
_TAPS_OPTIONAL = ("max_per_state", "grid_pct", "intent_node")
MAX_PER_STATE = 4096
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
PREFIX_WORDS = 256


@dataclass(frozen=True)
class Taps:
    """`taps`: `scope` scene derives the u2 and u3 taps of every state from its scene (fixed: the catalogue's points
    only); `max_per_state` caps each class per state; `grid_pct` the probe grid without a contract (None: required
    only for scope scene without --contract); `intent_node` how a u1 intent names its scene node, or None."""
    scope: str
    max_per_state: object
    grid_pct: object
    intent_node: object


def _fail(where, why):
    raise InternalError("event catalogue: %s: %s" % (where, why))


def _int(where, value, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        _fail(where, "must be an integer in %d..%d, got %r" % (lo, hi, value))
    return value


def _keys(where, table, required, optional=()):
    if type(table) is not dict:
        _fail(where, "must be a table")
    unknown = sorted(set(table) - set(required) - set(optional))
    missing = sorted(set(required) - set(table))
    if unknown or missing:
        _fail(where, "unknown key(s) %s, missing key(s) %s"
              % (", ".join(unknown) or "none", ", ".join(missing) or "none"))


def taps(raw):
    """The `taps` table, or None without one."""
    if raw is None:
        return None
    _keys("taps", raw, _TAPS_KEYS, _TAPS_OPTIONAL)
    scope = raw["scope"]
    if scope not in TAP_SCOPES or type(scope) is not str:
        _fail("taps.scope", "must be one of %s" % ", ".join(TAP_SCOPES))
    ui_contract.check_provenance("taps.provenance", raw["provenance"])
    if (scope == "scene") != ("max_per_state" in raw):
        _fail("taps.max_per_state", "is required with scope \"scene\" and only there (the explicit cap per state)")
    if "grid_pct" in raw and scope != "scene":
        _fail("taps.grid_pct", "is only for scope \"scene\"")
    cap = _int("taps.max_per_state", raw["max_per_state"], 1, MAX_PER_STATE) if scope == "scene" else None
    grid = None
    if "grid_pct" in raw:
        grid = raw["grid_pct"]
        if type(grid) is not list or not 1 <= len(grid) <= 9 or any(type(v) is not int or not 0 <= v <= 100
                                                                      for v in grid) \
                or any(a >= b for a, b in zip(grid, grid[1:])):
            _fail("taps.grid_pct", "must be 1 to 9 strictly increasing integers in 0..100")
        grid = tuple(grid)
    node = raw.get("intent_node")
    if node is not None and (type(node) is not str or node not in INTENT_NODES):
        _fail("taps.intent_node", "must be one of %s" % ", ".join(INTENT_NODES))
    return Taps(scope, cap, grid, node)


def boot(raw):
    """The boot seeds of `[boot]` (distinct uint64 in file order), or () without one."""
    if raw is None:
        return ()
    _keys("boot", raw, ("seeds", "provenance"))
    ui_contract.check_provenance("boot.provenance", raw["provenance"])
    seeds = raw["seeds"]
    if type(seeds) is not list or not 1 <= len(seeds) <= 256 or len(set(seeds)) != len(seeds):
        _fail("boot.seeds", "must be 1 to 256 distinct integers")
    return tuple(_int("boot.seeds", seed, 0, 2**63 - 1) for seed in seeds)


def prefixes(raw):
    """((name, words), ...) of the `[[prefix]]` rows, or () without any. The words are checked as path words when a run
    uses them (they need the catalogue and the probe's capabilities)."""
    if raw is None:
        return ()
    if type(raw) is not list or not raw:
        _fail("prefix", "must be a non-empty array of tables")
    out, names = [], set()
    for index, row in enumerate(raw):
        where = "prefix[%d]" % index
        _keys(where, row, ("name", "words", "provenance"))
        name = row["name"]
        if type(name) is not str or not _NAME.fullmatch(name) or name in names:
            _fail(where + ".name", "must be a distinct name matching %s" % _NAME.pattern)
        names.add(name)
        ui_contract.check_provenance(where + ".provenance", row["provenance"])
        words = row["words"]
        if type(words) is not list or not 1 <= len(words) <= PREFIX_WORDS or any(type(w) is not str for w in words):
            _fail(where + ".words", "must be 1 to %d path words" % PREFIX_WORDS)
        out.append((name, tuple(words)))
    return tuple(out)


def digit_map(where, raw, digits):
    """A pad macro's `digit_map`: ((digit, intent, arg), ...) for the digits 0-9 it names, sorted; every digit of
    `digits` must be mapped."""
    if type(raw) is not dict or not raw:
        _fail(where, "must be a non-empty table of digit -> { intent, arg }")
    out = []
    for digit, item in sorted(raw.items()):
        if not re.fullmatch(r"[0-9]", digit):
            _fail(where, "keys must be single digits, got %r" % digit)
        _keys("%s.%s" % (where, digit), item, ("intent", "arg"))
        out.append((digit, _int("%s.%s.intent" % (where, digit), item["intent"], 0, 0xffffffff),
                    _int("%s.%s.arg" % (where, digit), item["arg"], -2**31, 2**31 - 1)))
    missing = sorted(set(digits) - {d for d, _, _ in out})
    if missing:
        _fail(where, "does not map the digit(s) %s of `digits`" % ", ".join(missing))
    return tuple(out)
