"""`rigor sim`: the verdict on the whole-app simulation runs of a product (T2G2, P330 §1.3 to §1.8). Run by `rigor grade` as
the gate `sim` (grade_sim.py).

    rigor sim --results DIR --policy P.toml --facts DIR --salt FILE [--salt-id H] [--spec S.toml]
              [--regressions R.json] [--tier merge|nightly] [--out F]

The results directory (flat; anything else in it is exit 2) is what the `c_sim` actions produced, collected by the caller:
`index.json` = `{"<c_sim label>": "<id>"}` and per id `<id>.stats.json` (schema `sim-stats/1`), `<id>.verdict`, `<id>.report`,
`<id>.hashes` (the san run: `index seed trace state` per finished seed), `<id>.release.hashes` (the release run, whose seeds 0
to 9 must equal the san ones) and optionally `<id>.failure.trace` (at most 64 KiB) and `<id>.soak.json` (the soak run of the
tier, schema `sim-soak/1`, T2G6: the days it completed, the day each assertion first failed and what it checked; the merge tier
has none, and a soak result at that tier is exit 2). The judge trusts nothing the runner says
about itself: it recomputes the seeds from the salt and the world hash, the required budget from the policy and the tier,
and what each invariant and fault was required to show from the spec (docs/sim.md). `--salt` is the hex salt file (the
grader's hidden one, or the product's public one; absent: the empty salt); `--salt-id` is checked against its sha256.

Findings (errors; docs/sim.md): `sim-invariant-violated`, `sim-nondeterministic`, `sim-model-divergence`, `sim-crash`,
`sim-deadlock`, `sim-timeout`, `sim-init-failed`, `sim-world-error`, `sim-vacuous`, `fault-not-observed`,
`sim-module-unreached`, `sim-module-unexercised`, `sim-seeds-short`, `soak-assertion`, `soak-too-short`,
`sim-missing-target`, `sim-stats-counter`, plus `sim-not-run` (a c_sim target without results) and `sim-regression-missing`.
Volatile data lives only in metadata. Every malformed input is exit 2.
"""

import os
import re
from dataclasses import dataclass

from rigor_lib import facts_data, jsonio, sim_policy
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "sim"
INDEX = "index.json"
SCHEMA = "sim-stats/1"
IDENTITY_SEEDS = 10     # seeds 0..9 of every build are compared between release and san (sim_merge.IDENTITY_SEEDS)
TRACE_LIMIT = 64 * 1024
_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_SHA = re.compile(r"[0-9a-f]{64}")
_HEX16 = re.compile(r"[0-9a-f]{16}")
_VERDICT = re.compile(r"pass|fail sim-[a-z-]+")
_SUFFIXES = (".stats.json", ".verdict", ".report", ".hashes", ".release.hashes", ".failure.trace", ".soak.json")
_REQUIRED_SUFFIXES = _SUFFIXES[:5]
SOAK_SCHEMA = "sim-soak/1"
_SOAK_KEYS = {"checked", "days", "failures", "salt_sha256", "schema", "seed", "state_hash", "trace_hash", "uploads", "world_sha256"}
SOAK_CHECKS = ("I11", "I12", "I13")     # the invariants a soak evaluates at its daily checkpoints
_BASE_KEYS = {"count", "distinct_hashes", "failures", "schema", "seeds_run", "shards"}
_WORLD_KEYS = {"run_ms", "salt_sha256", "world_sha256"}
_OPTIONAL_KEYS = {"invariants", "faults", "screens", "counters", "soak", "unexercised", "first"}
# Rules a failure row of the stats may carry (the runner's and the invariant engine's).
_FAILURE_RULES = {"sim-invariant-violated", "sim-nondeterministic", "sim-model-divergence", "sim-crash", "sim-deadlock",
                  "sim-timeout", "sim-init-failed", "sim-world-error"}
_FAILURE_REQUIRED = {"index", "rule", "seed"}
_FAILURE_OPTIONAL = {"detail", "invariant", "step", "at_ms", "kind", "digest"}
# What a verdict of the runner may say without a failure row behind it.
_VERDICT_ONLY = {"sim-vacuous", "sim-no-seeds", "sim-world-error"}


def _fail(where, why):
    raise InternalError("sim: %s: %s" % (where, why))


@dataclass(frozen=True)
class Result:
    """What one `c_sim` target produced (validated)."""
    label: str
    stats: dict
    verdict: str
    rows: dict          # san hashes: index -> (seed, trace, state)
    release: dict       # release hashes, the same shape
    hashes_sha256: str
    release_sha256: str
    soak: dict = None               # the validated `<id>.soak.json`, None without one
    soak_sha256: str = None


def _text(path):
    try:
        return jsonio.read_bytes(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InternalError("%s is not UTF-8: %s" % (path, exc)) from exc


def _nonneg(where, value):
    if type(value) is not int or value < 0:
        _fail(where, "must be a non-negative integer")
    return value


def _failure_rows(path, stats):
    rows = stats["failures"]
    if not isinstance(rows, list):
        _fail(path, "failures must be a list")
    for row in rows:
        keys = set(row) if isinstance(row, dict) else set()
        if not _FAILURE_REQUIRED <= keys or not keys <= _FAILURE_REQUIRED | _FAILURE_OPTIONAL:
            _fail(path, "a failure row needs index, rule and seed (and may carry %s)" % sorted(_FAILURE_OPTIONAL))
        if row["rule"] not in _FAILURE_RULES or not _HEX16.fullmatch(str(row["seed"])):
            _fail(path, "bad failure row %r" % (row,))
        _nonneg(path + " failure index", row["index"])
    return rows


def _stats(path):
    try:
        stats = jsonio.strict_loads(jsonio.read_bytes(path))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(stats, dict) or not _BASE_KEYS <= set(stats) or set(stats) - _BASE_KEYS - _WORLD_KEYS - _OPTIONAL_KEYS:
        _fail(path, "must be an object with the keys %s (and optionally %s)" % (
            sorted(_BASE_KEYS), sorted(_WORLD_KEYS | _OPTIONAL_KEYS)))
    if stats["schema"] != SCHEMA:
        _fail(path, "schema must be %s" % SCHEMA)
    present = _WORLD_KEYS & set(stats)
    if present and present != _WORLD_KEYS:
        _fail(path, "run_ms, salt_sha256 and world_sha256 come together")
    for key in ("count", "distinct_hashes", "seeds_run", "shards"):
        _nonneg(path + " " + key, stats[key])
    if present:
        _nonneg(path + " run_ms", stats["run_ms"])
        if not all(isinstance(stats[k], str) and _SHA.fullmatch(stats[k]) for k in ("salt_sha256", "world_sha256")):
            _fail(path, "salt_sha256 and world_sha256 must be lowercase sha256")
    _failure_rows(path, stats)
    return stats


def _hashes(path):
    """{index: (seed, trace, state)} of a hashes file; any defect is exit 2."""
    rows = {}
    text = _text(path)
    for line in text.splitlines():
        parts = line.split(" ")
        if len(parts) != 4 or not parts[0].isdigit() or int(parts[0]) in rows or not all(_HEX16.fullmatch(p) for p in parts[1:]):
            _fail(path, "bad hashes line %r" % line)
        rows[int(parts[0])] = tuple(parts[1:])
    if text and not text.endswith("\n"):
        _fail(path, "the last line is not terminated")
    return rows


def _soak_file(path):
    """The parsed and validated soak result at PATH; any defect is exit 2."""
    try:
        soak = jsonio.strict_loads(jsonio.read_bytes(path))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(soak, dict) or set(soak) != _SOAK_KEYS or soak["schema"] != SOAK_SCHEMA:
        _fail(path, "must be an object with exactly the keys %s and schema %s" % (sorted(_SOAK_KEYS), SOAK_SCHEMA))
    _nonneg(path + " days", soak["days"])
    _nonneg(path + " uploads", soak["uploads"])
    checked = soak["checked"]
    if not isinstance(checked, dict) or set(checked) != set(SOAK_CHECKS):
        _fail(path, "checked must have exactly %s" % list(SOAK_CHECKS))
    for name in SOAK_CHECKS:
        _nonneg("%s checked.%s" % (path, name), checked[name])
    if not all(isinstance(soak[k], str) and _SHA.fullmatch(soak[k]) for k in ("salt_sha256", "world_sha256")) \
            or not all(isinstance(soak[k], str) and _HEX16.fullmatch(soak[k]) for k in ("seed", "state_hash", "trace_hash")):
        _fail(path, "the hashes and the seed must be lowercase hex")
    failures = soak["failures"]
    if not isinstance(failures, list):
        _fail(path, "failures must be a list")
    for item in failures:
        if not isinstance(item, dict) or set(item) != {"assertion", "day"} or not isinstance(item["assertion"], str) \
                or not item["assertion"]:
            _fail(path, "a soak failure is {assertion, day}")
        _nonneg(path + " failure day", item["day"])
    return soak


def load_result(directory, label, ident):
    base = os.path.join(directory, ident)
    stats = _stats(base + ".stats.json")
    verdict = _text(base + ".verdict").rstrip("\n")
    if not _VERDICT.fullmatch(verdict):
        _fail(base + ".verdict", "must be 'pass' or 'fail sim-<rule>'")
    if verdict == "pass" and stats["failures"]:
        _fail(label, "a passing verdict with failures in the stats")
    rule = verdict.split(" ")[1] if " " in verdict else None
    if rule is not None and rule not in _VERDICT_ONLY and rule not in {f["rule"] for f in stats["failures"]}:
        _fail(label, "the verdict names %s, which no failure row shows" % rule)
    _text(base + ".report")   # must exist and be text
    trace = base + ".failure.trace"
    if os.path.exists(trace) and os.path.getsize(trace) > TRACE_LIMIT:
        _fail(trace, "larger than %d bytes" % TRACE_LIMIT)
    soak_path = base + ".soak.json"
    soak = _soak_file(soak_path) if os.path.exists(soak_path) else None
    if soak is not None and "soak" in stats:
        _fail(label, "a soak in the stats and a soak file")
    return Result(label, stats, verdict, _hashes(base + ".hashes"), _hashes(base + ".release.hashes"),
                  jsonio.sha256_hex(jsonio.read_bytes(base + ".hashes")),
                  jsonio.sha256_hex(jsonio.read_bytes(base + ".release.hashes")),
                  soak, None if soak is None else jsonio.sha256_hex(jsonio.read_bytes(soak_path)))


def load_results(directory):
    """{target label: Result}. The directory holds the index and the files of its ids, nothing else."""
    if not os.path.isdir(directory):
        _fail(directory, "results path is not a directory")
    path = os.path.join(directory, INDEX)
    if not os.path.isfile(path):
        _fail(directory, "missing %s" % INDEX)
    index = jsonio.strict_loads(jsonio.read_bytes(path))
    ids = list(index.values()) if isinstance(index, dict) else []
    if not isinstance(index, dict) or len(set(ids)) != len(ids) or not all(
            facts_data.LABEL.fullmatch(k) and isinstance(v, str) and _ID.fullmatch(v) for k, v in index.items()):
        _fail(INDEX, "must map distinct ids to target labels (label -> id)")
    allowed = {INDEX} | {i + s for i in ids for s in _SUFFIXES}
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if name not in allowed or not os.path.isfile(full) or os.path.islink(full):
            _fail(full, "not a results file")
    for ident in ids:
        for suffix in _REQUIRED_SUFFIXES:
            if not os.path.isfile(os.path.join(directory, ident + suffix)):
                _fail(ident, "missing %s" % (ident + suffix))
    return {label: load_result(directory, label, ident) for label, ident in sorted(index.items())}


def seed_digest(results):
    """sha256 over the sha256 of every target's san and release hashes, in label order: it commits to which seeds ran and what
    they did (the verdict's `sim_seed_digest`); a soak result adds its own hash to its target's row."""
    return jsonio.sha256_hex(jsonio.canonical_dumps([
        [r.label, r.hashes_sha256, r.release_sha256] + ([] if r.soak_sha256 is None else [r.soak_sha256])
        for _, r in sorted(results.items())]))


# ---------------------------------------------------------------------------------------------------- findings

def _check_world(result, salt, salt_id):
    stats = result.stats
    if "world_sha256" not in stats:
        return None
    if stats["salt_sha256"] != salt_id:
        _fail(result.label, "the run used another salt than the grader's (salt_sha256 %s)" % stats["salt_sha256"])
    return bytes.fromhex(stats["world_sha256"])


def _expected_seeds(result, salt, world):
    """Checks that the hashes file and the failure rows name exactly the seeds 0..seeds_run-1 of the derivation."""
    stats, label = result.stats, result.label
    failed = {f["index"]: f["seed"] for f in stats["failures"]}
    if len(failed) != len(stats["failures"]) or set(failed) & set(result.rows):
        _fail(label, "a seed is both finished and failed, or failed twice")
    if set(failed) | set(result.rows) != set(range(stats["seeds_run"])):
        _fail(label, "the hashes and failure rows do not name exactly the seeds 0..%d" % (stats["seeds_run"] - 1))
    for index, row in result.rows.items():
        if row[0] != sim_policy.seed_of(salt, world, index):
            _fail(label, "seed %d is not the one the salt and the world give" % index)
    for index, seed in failed.items():
        if seed != sim_policy.seed_of(salt, world, index):
            _fail(label, "failed seed %d is not the one the salt and the world give" % index)


def seed_findings(result, required):
    """`sim-seeds-short` and `sim-vacuous` (200 seeds must give 200 distinct traces), recomputed from the hashes."""
    stats, found = result.stats, []
    if stats["count"] < required or stats["seeds_run"] != stats["count"]:
        found.append(finding("sim-seeds-short", target=result.label, required=required, count=stats["count"],
                             seeds_run=stats["seeds_run"]))
    distinct = len({row[1] for row in result.rows.values()})
    if not stats["failures"] and stats["distinct_hashes"] != distinct:
        _fail(result.label, "distinct_hashes says %d, the hashes file has %d" % (stats["distinct_hashes"], distinct))
    if len(result.rows) >= 2 and distinct < len(result.rows):
        found.append(finding("sim-vacuous", target=result.label, what="seeds", seeds=len(result.rows), distinct=distinct))
    return found


def failure_findings(result):
    found = []
    for row in sorted(result.stats["failures"], key=lambda f: f["index"]):
        extra = {k: v for k, v in row.items() if k not in ("rule",)}
        found.append(finding(row["rule"], target=result.label, **extra))
    return found


def mode_findings(result):
    """Seeds 0..9 of the release run must equal the san run (P330 §1.3); a seed that failed in san is reported by its failure."""
    found, failed = [], {f["index"] for f in result.stats["failures"]}
    for index in range(min(IDENTITY_SEEDS, result.stats["seeds_run"])):
        san, release = result.rows.get(index), result.release.get(index)
        if index in failed and san is None:
            continue
        if san is None or release is None or san != release:
            found.append(finding("sim-nondeterministic", target=result.label, index=index, why="release and san differ"
                                 if release is not None else "missing in the release run"))
    return found


def _counts(table, key, name):
    row = table.get(name) if isinstance(table, dict) else None
    if row is not None and (not isinstance(row, dict) or set(row) != set(key) or not all(
            type(row[k]) is int and row[k] >= 0 for k in key)):
        _fail("stats", "%s entry %s must be an object with the integers %s" % (key, name, list(key)))
    return row


def spec_findings(result, spec):
    """What the spec requires the stats to show: invariants checked and clean, faults fired and observed, screens, counters."""
    stats, label, found = result.stats, result.label, []
    seen = {f.get("invariant") for f in result.stats["failures"]}
    table = stats.get("invariants", {})
    for name in sorted(set(spec.invariants) | set(table)):
        row = _counts(table, ("checked", "violated"), name)
        if name in spec.invariants and (row is None or row["checked"] < spec.min_checked):
            found.append(finding("sim-vacuous", target=label, invariant=name, count=0 if row is None else row["checked"]))
        if row is not None and row["violated"] > 0 and name not in seen:
            found.append(finding("sim-invariant-violated", target=label, invariant=name, count=row["violated"]))
    faults = stats.get("faults", {})
    for name in spec.faults:
        row = _counts(faults, ("fired", "observed"), name)
        if row is None or row["fired"] < spec.min_fired or row["observed"] < 1:
            found.append(finding("fault-not-observed", target=label, fault=name, fired=0 if row is None else row["fired"],
                                 observed=0 if row is None else row["observed"]))
    reached = stats.get("screens", [])
    if not isinstance(reached, list) or not all(isinstance(s, str) for s in reached):
        _fail("stats", "screens must be a list of names")
    found.extend(finding("sim-vacuous", target=label, screen=name, count=0) for name in spec.screens if name not in reached)
    counters = stats.get("counters", {})
    if not isinstance(counters, dict) or not all(type(v) is int and v >= 0 for v in counters.values()):
        _fail("stats", "counters must be an object of non-negative integers")
    for name in spec.zero_counters:
        if name not in counters or counters[name] != 0:
            found.append(finding("sim-stats-counter", target=label, counter=name, value=counters.get(name, -1)))
    return found


def _soak_checked(result, policy, spec):
    """`sim-vacuous` for a soak that never evaluated what it must (the spec's I11 to I13, and I12 whenever the policy has
    capacity rows): a soak whose world reports nothing passes every day and proves nothing."""
    required = {name for name in spec.invariants if name in SOAK_CHECKS}
    if policy.capacity:
        required.add("I12")
    return [finding("sim-vacuous", target=result.label, soak=name, count=result.soak["checked"][name])
            for name in sorted(required) if result.soak["checked"][name] == 0]


def soak_findings(result, policy, tier, spec=None):
    """`soak-too-short` (the days the tier and the capacity rows demand), `soak-assertion` (day of each failed assertion) and
    `sim-vacuous` (a soak that checked nothing). The soak is the result's soak file, or a `soak` object of the stats."""
    label, found = result.label, []
    soak = result.stats.get("soak") if result.soak is None else {"days": result.soak["days"], "failures": result.soak["failures"]}
    need = policy.soak_required(tier)
    if soak is not None and (not isinstance(soak, dict) or set(soak) != {"days", "failures"} or
                             type(soak["days"]) is not int or soak["days"] < 0 or not isinstance(soak["failures"], list)):
        _fail("stats", "soak must be an object with `days` and `failures`")
    days = 0 if soak is None else soak["days"]
    if days < need:
        found.append(finding("soak-too-short", target=label, required_days=need, days=days))
    for item in [] if soak is None else soak["failures"]:
        if not isinstance(item, dict) or set(item) != {"assertion", "day"} or type(item["day"]) is not int \
                or not isinstance(item["assertion"], str):
            _fail("stats", "a soak failure is {assertion, day}")
        found.append(finding("soak-assertion", target=label, assertion=item["assertion"], day=item["day"]))
    if result.soak is not None and spec is not None:
        found.extend(_soak_checked(result, policy, spec))
    return found


def check_soak(result, salt, world, tier, policy):
    """The soak file belongs to this run: same world and salt as the shards, the seed the derivation gives for the soak, and
    only at a tier that demands days (the merge tier does not, unless the policy says so: P330 §4)."""
    soak = result.soak
    if soak is None:
        return
    if policy.soak_required(tier) == 0:
        _fail(result.label, "a soak result at the %s tier, which demands no soak" % tier)
    stats = result.stats
    if soak["world_sha256"] != stats["world_sha256"] or soak["salt_sha256"] != stats["salt_sha256"]:
        _fail(result.label, "the soak ran another world or salt than the seeds")
    if soak["seed"] != sim_policy.seed_of(salt, world, sim_policy.SOAK_INDEX):
        _fail(result.label, "the soak's seed is not the one the salt and the world give")


def regression_findings(regressions, results):
    """Every seed of the regressions file must be among the finished or failed seeds of its target's run."""
    found = []
    for label, seeds in sorted(regressions.items()):
        result = results.get(label)
        ran = set() if result is None else {r[0] for r in result.rows.values()} | {f["seed"] for f in result.stats["failures"]}
        found.extend(finding("sim-regression-missing", target=label, seed=seed) for seed in sorted(seeds - ran))
    return found


def closure(facts_by_label, roots):
    """Every label reachable from `roots` through `deps` (labels without facts are ends)."""
    seen, todo = set(), sorted(roots)
    while todo:
        label = todo.pop()
        if label in seen:
            continue
        seen.add(label)
        if label in facts_by_label:
            todo.extend(facts_by_label[label].deps)
    return seen


def module_findings(facts_by_label, targets, modules, results):
    found = []
    reached = closure(facts_by_label, targets)
    found.extend(finding("sim-module-unreached", module=m) for m in modules if m not in reached)
    for label, result in sorted(results.items()):
        listed = result.stats.get("unexercised", [])
        if not isinstance(listed, list) or not all(isinstance(m, str) and facts_data.LABEL.fullmatch(m) for m in listed):
            _fail("stats", "unexercised must be a list of module labels")
        found.extend(finding("sim-module-unexercised", target=label, module=m) for m in sorted(listed) if m in modules)
    return found


# ---------------------------------------------------------------------------------------------------- the judge

def sim_targets(facts_by_label):
    return sorted(label for label, facts in facts_by_label.items() if facts.kind == "c_sim")


def judge(facts_by_label, policy, modules, spec, results, regressions, salt, salt_id, tier):
    targets = sim_targets(facts_by_label)
    for label in sorted(set(results) - set(targets)):
        _fail(label, "a sim result for something that is not a c_sim target of the facts")
    for label in sorted(set(regressions) - set(targets)):
        _fail("regressions", "%s is not a c_sim target of the facts" % label)
    for label in modules:
        if label not in facts_by_label:
            _fail("policy", "module %s has no facts" % label)
    found = []
    if policy.required and (not targets or (policy.target and policy.target not in targets)):
        found.append(finding("sim-missing-target", target=policy.target or ""))
    elif targets:
        found.extend(module_findings(facts_by_label, targets, modules, results))
    required = policy.seeds[tier]
    for label in targets:
        result = results.get(label)
        if result is None:
            found.append(finding("sim-not-run", target=label))
            continue
        world = _check_world(result, salt, salt_id)
        if world is None:     # the shards disagreed about the world or the salt: only the runner's own rule is left
            found.extend(failure_findings(result) or [finding("sim-world-error", target=label)])
            continue
        _expected_seeds(result, salt, world)
        check_soak(result, salt, world, tier, policy)
        found.extend(failure_findings(result))
        found.extend(seed_findings(result, required))
        found.extend(mode_findings(result))
        found.extend(spec_findings(result, spec))
        if not policy.target or policy.target == label:
            found.extend(soak_findings(result, policy, tier, spec))
    found.extend(regression_findings(regressions, results))
    return found


def _target_metadata(result):
    stats = result.stats
    row = {"count": stats["count"], "seeds_run": stats["seeds_run"], "distinct_hashes": stats["distinct_hashes"],
           "failures": len(stats["failures"])}
    if result.soak is not None:
        row["soak_days"] = result.soak["days"]
    return row


def run(args):
    policy = sim_policy.load_policy(args.policy)
    modules = sim_policy.profile_modules(args.policy, policy)
    spec, spec_sha = sim_policy.load_spec(args.spec)
    salt, salt_id = sim_policy.load_salt(args.salt)
    if args.salt_id is not None and args.salt_id != salt_id:
        _fail("--salt-id", "%s is not the sha256 of the salt file (%s)" % (args.salt_id, salt_id))
    facts_by_label = facts_data.load_facts_dir(args.facts)
    results = load_results(args.results)
    regressions = sim_policy.load_regressions(args.regressions)
    tier = args.tier
    found = judge(facts_by_label, policy, modules, spec, results, regressions, salt, salt_id, tier)
    metadata = {"tier": tier, "required_seeds": policy.seeds[tier], "salt_id": salt_id, "spec_sha256": spec_sha,
                "seed_digest": seed_digest(results) if results else None,
                "targets": {label: _target_metadata(r) for label, r in sorted(results.items())}}
    return GateResult(GATE_ID, found, metadata)


def add_parser(subparsers):
    parser = subparsers.add_parser("sim", allow_abbrev=False,
                                   help="whole-app simulation runs: seeds, budget, invariants shown, faults, soak")
    parser.add_argument("--results", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--salt", help="the salt file (lowercase hex); the empty salt without it")
    parser.add_argument("--salt-id", help="sha256 of the salt; checked against --salt")
    parser.add_argument("--spec", help="products/<p>/sim.toml")
    parser.add_argument("--regressions", help="products/<p>/sim-regressions.json")
    parser.add_argument("--tier", choices=sim_policy.TIERS, default="nightly")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
