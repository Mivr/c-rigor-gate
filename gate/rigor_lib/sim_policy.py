"""Gate-owned inputs of the `sim` gate (T2G2, P330 §1.3, §1.7, §1.8): the policy tables, the spec, the salt, the seeds and the
regressions file. Every defect is exit 2 (InternalError), as for the other gate-owned files.

`products/<p>/policy.toml` (read besides `[module]`; `facts_policy` lets the two tables through):

    [sim]
    required = true                       # the product must have a c_sim (`sim-missing-target`); default false
    target = "//apps/lockers/lkapp/sim:lockers_sim"     # optional: the c_sim that must exist
    profiles = ["wiring", "ui", "safety"]  # modules with one of these profiles must be in some c_sim's link closure
    [sim.seeds]                           # minimum seeds per tier (defaults 200 and 2000)
    merge = 200
    nightly = 2000
    [sim.soak_days]                       # simulated days of soak per tier (defaults 0 and 400)
    merge = 0
    nightly = 400
    [soak.capacity.snapshot_pool]         # a fixed-capacity counter: the soak must exceed 2 * bound events
    event = "snapshot upload"
    bound = 131070
    rate_per_day = 1440

Without a `[sim]` table nothing is required beyond what a present `c_sim` target shows (at least one seed, no soak).

`products/<p>/sim.toml` (the spec, sealed with the policy; optional): `invariants`, `faults`, `screens`, `zero_counters`
(lists of names the stats must show), `[coverage]` (`min_checked`, `min_fired`: integers, default 1) and the opaque tables
`[workload]`, `[fault]`, `[constants]` that the runner side reads; the judge binds the file by its sha256.
"""

import hashlib
import math
import re
import tomllib
from dataclasses import dataclass, field

from rigor_lib import facts_data, grade_policy, jsonio, policy_check
from rigor_lib.errors import InternalError

TIERS = ("merge", "nightly")
DEFAULT_SEEDS = {"merge": 200, "nightly": 2000}
DEFAULT_SOAK_DAYS = {"merge": 0, "nightly": 400}
MAX_SALT_HEX = 128
SEED_TAG = b"rigor-sim-v1"
SOAK_INDEX = 1 << 32      # the seed index of the soak (sim/soak.h `SIM_SOAK_INDEX`); the seed runs never reach it
_HEX = re.compile(r"(?:[0-9a-f]{2})*")
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_SEED = re.compile(r"[0-9a-f]{16}")
_SPEC_LISTS = ("invariants", "faults", "screens", "zero_counters")
_SPEC_TABLES = ("coverage", "workload", "fault", "constants")
_BIG = 1 << 40


def _fail(where, why):
    raise InternalError("sim: %s: %s" % (where, why))


@dataclass(frozen=True)
class Capacity:
    name: str
    event: str
    bound: int
    rate_per_day: int

    @property
    def days(self):
        """The soak length that exceeds 2 * bound events at the production rate (P330 §1.7)."""
        return math.ceil(2 * self.bound / self.rate_per_day)


@dataclass(frozen=True)
class SimPolicy:
    present: bool = False
    required: bool = False
    target: str = ""
    profiles: tuple = ()
    seeds: dict = field(default_factory=lambda: {"merge": 1, "nightly": 1})
    soak_days: dict = field(default_factory=lambda: {"merge": 0, "nightly": 0})
    capacity: tuple = ()

    def soak_required(self, tier):
        """Simulated days of soak the tier demands: 0 for none, else the tier's days or the capacity rule's, the larger."""
        days = self.soak_days[tier]
        return max([days] + [c.days for c in self.capacity]) if days > 0 else 0


@dataclass(frozen=True)
class Spec:
    invariants: tuple = ()
    faults: tuple = ()
    screens: tuple = ()
    zero_counters: tuple = ()
    min_checked: int = 1
    min_fired: int = 1


def _int(where, value, low=0, high=_BIG):
    if type(value) is not int or not low <= value <= high:
        _fail(where, "must be an integer in [%d, %d]" % (low, high))
    return value


def _only(where, table, allowed):
    if not isinstance(table, dict) or not set(table) <= set(allowed):
        _fail(where, "may only contain %s" % sorted(allowed))


def _per_tier(where, table, defaults, low):
    if table is None:
        return dict(defaults)
    _only(where, table, TIERS)
    return {tier: _int("%s.%s" % (where, tier), table.get(tier, defaults[tier]), low) for tier in TIERS}


def _capacity(document):
    soak = document.get("soak", {})
    _only("[soak]", soak, ("capacity",))
    rows = soak.get("capacity", {})
    if not isinstance(rows, dict):
        _fail("[soak.capacity]", "must be a table of tables")
    found = []
    for name, row in sorted(rows.items()):
        where = "[soak.capacity.%s]" % name
        if not _NAME.fullmatch(name):
            _fail(where, "odd name")
        _only(where, row, ("event", "bound", "rate_per_day"))
        if set(row) != {"event", "bound", "rate_per_day"} or not isinstance(row["event"], str) or row["event"] == "":
            _fail(where, "needs `event` (text), `bound` and `rate_per_day` (positive integers)")
        found.append(Capacity(name, row["event"], _int(where + " bound", row["bound"], 1),
                              _int(where + " rate_per_day", row["rate_per_day"], 1)))
    return tuple(found)


def parse_policy(document):
    """The SimPolicy of a parsed policy document (`[sim]`, `[soak.capacity]`); the defaults of "no [sim]" without them."""
    capacity = _capacity(document)
    table = document.get("sim")
    if table is None:
        if capacity:
            _fail("[soak.capacity]", "rows without a [sim] table")
        return SimPolicy()
    _only("[sim]", table, ("required", "target", "profiles", "seeds", "soak_days"))
    required = table.get("required", False)
    if type(required) is not bool:
        _fail("[sim] required", "must be true or false")
    target = table.get("target", "")
    if not isinstance(target, str) or (target != "" and not facts_data.LABEL.fullmatch(target)):
        _fail("[sim] target", "must be a target label")
    names = table.get("profiles", [])
    if not isinstance(names, list) or not all(isinstance(n, str) and _NAME.fullmatch(n) for n in names) \
            or len(set(names)) != len(names):
        _fail("[sim] profiles", "must be a list of distinct profile names")
    return SimPolicy(True, required, target, tuple(names),
                     _per_tier("[sim.seeds]", table.get("seeds"), DEFAULT_SEEDS, 1),
                     _per_tier("[sim.soak_days]", table.get("soak_days"), DEFAULT_SOAK_DAYS, 0), capacity)


def load_policy(path):
    return parse_policy(grade_policy.load_document(path))


def profile_modules(path, policy):
    """Sorted labels of the policy modules that carry one of the policy's `[sim] profiles`."""
    if not policy.profiles:
        return []
    found = []
    for label, table in sorted(grade_policy.module_tables(grade_policy.load_document(path)).items()):
        if set(policy.profiles) & set(policy_check.declared_profiles(label, table) or ()):
            if not facts_data.LABEL.fullmatch(label):
                _fail("policy", "odd module label %r" % label)
            found.append(label)
    return found


def _names(where, value):
    if not isinstance(value, list) or not all(isinstance(n, str) and _NAME.fullmatch(n) for n in value) \
            or len(set(value)) != len(value):
        _fail(where, "must be a list of distinct names")
    return tuple(value)


def load_spec(path):
    """(Spec, sha256 of the file or None). `path` None is the empty spec."""
    if path is None:
        return Spec(), None
    data = jsonio.read_bytes(path)
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (path, exc)) from exc
    _only("spec", document, _SPEC_LISTS + _SPEC_TABLES)
    for key in _SPEC_TABLES:
        if key in document and not isinstance(document[key], dict):
            _fail("spec [%s]" % key, "must be a table")
    coverage = document.get("coverage", {})
    _only("spec [coverage]", coverage, ("min_checked", "min_fired"))
    lists = {key: _names("spec " + key, document.get(key, [])) for key in _SPEC_LISTS}
    return Spec(min_checked=_int("spec min_checked", coverage.get("min_checked", 1), 1),
                min_fired=_int("spec min_fired", coverage.get("min_fired", 1), 1), **lists), jsonio.sha256_hex(data)


def load_regressions(path):
    """{target label: set of seeds (16 lowercase hex)}; {} without a file. Seeds that once failed (docs/sim.md)."""
    if path is None:
        return {}
    try:
        document = jsonio.strict_loads(jsonio.read_bytes(path))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(document, dict):
        _fail(path, "must be an object of target label -> list of seeds")
    found = {}
    for label, seeds in document.items():
        ok = isinstance(seeds, list) and all(isinstance(s, str) and _SEED.fullmatch(s) for s in seeds)
        if not facts_data.LABEL.fullmatch(label) or not ok or len(set(seeds)) != len(seeds):
            _fail(path, "bad entry for %r (a label and a list of distinct 16-digit lowercase hex seeds)" % (label,))
        found[label] = set(seeds)
    return found


def parse_salt(text, where):
    """The salt bytes of a salt file's text: lowercase hex, at most 64 bytes, one optional trailing newline, may be empty."""
    if text.endswith("\n"):
        text = text[:-1]
    if len(text) > MAX_SALT_HEX or not _HEX.fullmatch(text):
        _fail(where, "a salt is lowercase hex of at most 64 bytes")
    return bytes.fromhex(text)


def load_salt(path):
    """(salt bytes, salt id = sha256 of the bytes); the empty salt without a file."""
    if path is None:
        return b"", jsonio.sha256_hex(b"")
    try:
        text = jsonio.read_bytes(path).decode("ascii")
    except UnicodeDecodeError as exc:
        raise InternalError("%s is not ASCII: %s" % (path, exc)) from exc
    salt = parse_salt(text, path)
    return salt, jsonio.sha256_hex(salt)


def seed_of(salt, world, index):
    """P330 §1.3: the first 8 bytes (big endian) of SHA-256("rigor-sim-v1" || salt || world || le64(index)), as 16 hex digits.
    `world` is the 32 bytes of the world's sha256 (sim/seedrun `sim_seed_of`)."""
    digest = hashlib.sha256(SEED_TAG + salt + world + index.to_bytes(8, "little")).digest()
    return digest[:8].hex()
