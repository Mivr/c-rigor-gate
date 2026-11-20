"""`rigor fuzz`: the verdict on the fuzz runs of a product (T126, P003 §7.2, G23). Run by `rigor grade` as the gate `fuzz` (grade_fuzz.py, T129).

    rigor fuzz --results DIR --policy P.toml --facts DIR [--regressions R.json] [--out F]

Policy (gate-owned, the same `policy.toml` the other gates read; only these keys are read here):

    [module."//pkg:name"]
    fuzz = true            # the module must be fuzzed: some c_fuzz target lists it in `deps`
    profile = ["parser"]   # the same, without `fuzz = true` (T127); `fuzz_runs` then applies as well
    fuzz_runs = 200000     # optional: the budget the run must have completed (default DEFAULT_RUNS, at most MAX_RUNS)

The results directory (flat; anything else in it is exit 2) is what the `c_fuzz` action produced, collected by the
caller: `index.json` = `{"<target label>": "<id>"}` and, per id, `<id>.stats.json`, `<id>.verdict`, `<id>.report`,
`<id>.replayed` (the sha256 of every replayed corpus file, one per line) and optionally `<id>.crash` (the reproducer,
whose sha256 must match the stats). `R.json` is gate-owned: `{"<target label>": ["<sha256>", ...]}`, the inputs that once
crashed. Findings are errors unless noted (docs/fuzz.md): `fuzz-missing`, `fuzz-harness-no-call`, `fuzz-crash`,
`fuzz-not-run`, `fuzz-short`, `fuzz-regression-missing`, and the info `fuzz-empty-corpus`. Counts go to metadata only.
Every malformed input is exit 2.
"""

import os
import re
from dataclasses import dataclass

from rigor_lib import facts_data, grade_policy, jsonio, policy_check
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "fuzz"
PARSER = "parser"   # a module with this profile must be fuzzed (T127, P003 §4)
DEFAULT_RUNS = 200000   # the same as FUZZ_DEFAULT_RUNS / FUZZ_MAX_RUNS in rules/fuzz.bzl (a unit test compares them)
MAX_RUNS = 2000000
INDEX = "index.json"
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_VERDICT = re.compile(r"pass|fail rc=[0-9]+")
_FRAME = re.compile(r"\s+#[0-9]+ 0x[0-9A-Za-z]+ in (.+?)(?: \([^()]*\))?")
_STATS_KEYS = {"runs_done", "corpus_files", "replayed", "phase", "reproducer_sha256"}
_SUFFIXES = (".stats.json", ".verdict", ".report", ".replayed", ".crash")
_FRAME_LIMIT = 300


@dataclass(frozen=True)
class Result:
    """What one fuzz run produced (validated)."""
    label: str
    passed: bool
    runs_done: int
    corpus_files: int
    phase: str
    reproducer: str
    replayed: frozenset
    top_frame: str


def _fail(where, why):
    raise InternalError("fuzz: %s: %s" % (where, why))


def _json(path):
    try:
        return jsonio.strict_loads(jsonio.read_bytes(path))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid JSON: %s" % (path, exc)) from exc


def _text(path):
    try:
        return jsonio.read_bytes(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InternalError("%s is not UTF-8: %s" % (path, exc)) from exc


def load_policy(path):
    """{module label: budget in runs} of the modules that must be fuzzed: `fuzz = true`, or the `parser` profile."""
    modules = grade_policy.load_document(path).get("module", {})
    if not isinstance(modules, dict):
        _fail("policy", "[module] must be a table of tables")
    required = {}
    for label, table in modules.items():
        if not isinstance(table, dict):
            _fail("policy", "module %s must be a table" % label)
        if "fuzz" in table and type(table["fuzz"]) is not bool:
            _fail("policy", "module %s: fuzz must be true or false" % label)
        runs = table.get("fuzz_runs")
        if runs is not None and (type(runs) is not int or not 1 <= runs <= MAX_RUNS):
            _fail("policy", "module %s: fuzz_runs must be an integer in [1, %d]" % (label, MAX_RUNS))
        must = table.get("fuzz", False) or PARSER in (policy_check.declared_profiles(label, table) or ())
        if runs is not None and not must:
            _fail("policy", "module %s: fuzz_runs without fuzz = true or the parser profile" % label)
        if must:
            if not facts_data.LABEL.fullmatch(label):
                _fail("policy", "odd module label %r" % label)
            required[label] = DEFAULT_RUNS if runs is None else runs
    return required


def load_regressions(path):
    """{target label: set of sha256}; {} without a file."""
    if path is None:
        return {}
    document = _json(path)
    if not isinstance(document, dict):
        _fail(path, "must be an object of target label -> list of sha256")
    found = {}
    for label, shas in document.items():
        ok = isinstance(shas, list) and all(isinstance(s, str) and _SHA.fullmatch(s) for s in shas)
        if not facts_data.LABEL.fullmatch(label) or not ok or len(set(shas)) != len(shas):
            _fail(path, "bad entry for %r (a label and a list of distinct lowercase sha256)" % (label,))
        found[label] = set(shas)
    return found


def top_frame(report):
    """The symbolized top frame of the report (`function file:line:col`), or ''."""
    for line in report.split("\n"):
        match = _FRAME.fullmatch(line)
        if match:
            return match.group(1)[:_FRAME_LIMIT]
    return ""


def _stats(path):
    stats = _json(path)
    if not isinstance(stats, dict) or set(stats) != _STATS_KEYS:
        _fail(path, "must be an object with exactly the keys %s" % sorted(_STATS_KEYS))
    for key in ("runs_done", "corpus_files", "replayed"):
        if type(stats[key]) is not int or stats[key] < 0:
            _fail(path, "%s must be a non-negative integer" % key)
    if stats["phase"] not in ("replay", "budget"):
        _fail(path, "phase must be replay or budget")
    sha = stats["reproducer_sha256"]
    if not isinstance(sha, str) or (sha != "" and not _SHA.fullmatch(sha)):
        _fail(path, "reproducer_sha256 must be empty or a lowercase sha256")
    if stats["replayed"] > stats["corpus_files"]:
        _fail(path, "replayed exceeds corpus_files")
    return stats


def _replayed(path, count):
    lines = _text(path).split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) != count or not all(_SHA.fullmatch(line) for line in lines):
        _fail(path, "must list exactly %d sha256 values, one per line" % count)
    return frozenset(lines)


def _check_consistent(label, passed, stats, crash_path):
    if passed and (stats["reproducer_sha256"] != "" or stats["phase"] != "budget" or stats["replayed"] != stats["corpus_files"]):
        _fail(label, "a passing verdict with a reproducer, a replay stop or a partial replay")
    if not passed and stats["phase"] == "budget" and stats["replayed"] != stats["corpus_files"]:
        _fail(label, "a budget-phase stop with a partial replay")
    if crash_path is not None:
        data = jsonio.read_bytes(crash_path)
        expected = jsonio.sha256_hex(data) if data else ""
        if expected != stats["reproducer_sha256"]:
            _fail(label, "the crash file does not match reproducer_sha256")


def load_result(directory, label, ident):
    base = os.path.join(directory, ident)
    stats = _stats(base + ".stats.json")
    verdict = _text(base + ".verdict").rstrip("\n")
    if not _VERDICT.fullmatch(verdict):
        _fail(base + ".verdict", "must be 'pass' or 'fail rc=N'")
    passed = verdict == "pass"
    crash = base + ".crash" if os.path.exists(base + ".crash") else None
    _check_consistent(label, passed, stats, crash)
    frame = "" if passed else top_frame(_text(base + ".report"))
    return Result(label, passed, stats["runs_done"], stats["corpus_files"], stats["phase"],
                  stats["reproducer_sha256"], _replayed(base + ".replayed", stats["replayed"]), frame)


def load_results(directory):
    """{target label: Result}. The directory holds the index and the files of its ids, nothing else."""
    if not os.path.isdir(directory):
        _fail(directory, "results path is not a directory")
    index = _json(os.path.join(directory, INDEX)) if os.path.isfile(os.path.join(directory, INDEX)) else None
    if index is None:
        _fail(directory, "missing %s" % INDEX)
    ids = list(index.values()) if isinstance(index, dict) else []
    if not isinstance(index, dict) or len(set(ids)) != len(ids) or not all(
            facts_data.LABEL.fullmatch(k) and isinstance(v, str) and _ID.fullmatch(v) for k, v in index.items()):
        _fail(INDEX, "must map distinct ids to target labels (label -> id)")
    allowed = {INDEX} | {i + s for i in ids for s in _SUFFIXES}
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if name not in allowed or not os.path.isfile(full) or os.path.islink(full):
            _fail(full, "not a results file")
    return {label: load_result(directory, label, ident) for label, ident in sorted(index.items())}


def exports_of(facts):
    return frozenset().union(*(unit.defined for unit in facts.units)) if facts.units else frozenset()


def references_of(facts):
    return frozenset().union(*(unit.undefined for unit in facts.units)) if facts.units else frozenset()


def load_targets(facts_by_label, required):
    """{c_fuzz label: [required modules it lists in deps]} for every c_fuzz target, after checking the facts exist."""
    for label in sorted(required):
        if label not in facts_by_label:
            _fail("policy", "module %s has no facts" % label)
    return {label: [dep for dep in facts.deps if dep in required]
            for label, facts in sorted(facts_by_label.items()) if facts.kind == "c_fuzz"}


def structure_findings(facts_by_label, required, targets):
    """`fuzz-missing` and `fuzz-harness-no-call`: what the facts say, before anything ran."""
    found = []
    fuzzed = {dep for deps in targets.values() for dep in deps}
    for module in sorted(set(required) - fuzzed):
        found.append(finding("fuzz-missing", module=module))
    for label, deps in targets.items():
        called = references_of(facts_by_label[label])
        for module in deps:
            if not exports_of(facts_by_label[module]) & called:
                found.append(finding("fuzz-harness-no-call", target=label, module=module))
    return found


def run_findings(result, budget):
    """The findings of one run: a crash, or too few runs; the info for an empty corpus."""
    found = []
    if not result.passed:
        found.append(finding("fuzz-crash", target=result.label, phase=result.phase,
                             reproducer_sha256=result.reproducer, top_frame=result.top_frame))
    elif result.runs_done < budget:
        found.append(finding("fuzz-short", target=result.label))
    if result.corpus_files == 0:
        found.append(finding("fuzz-empty-corpus", severity=SEVERITY_INFO, target=result.label))
    return found


def regression_findings(regressions, results):
    """Every listed input must be among the replayed corpus files of its target (a stopped replay is `fuzz-crash`)."""
    found = []
    for label, shas in sorted(regressions.items()):
        result = results.get(label)
        if result is not None and not result.passed and result.phase == "replay":
            continue
        replayed = result.replayed if result is not None else frozenset()
        for sha in sorted(shas - replayed):
            found.append(finding("fuzz-regression-missing", target=label, sha256=sha))
    return found


def target_budget(deps, required):
    """The runs a target must complete: the largest budget of the required modules it fuzzes (the default for none)."""
    return max([required[m] for m in deps], default=DEFAULT_RUNS)


def judge(facts_by_label, required, results, regressions):
    targets = load_targets(facts_by_label, required)
    for label in sorted(set(results) - set(targets)):
        _fail(label, "a fuzz result for something that is not a c_fuzz target of the facts")
    found = structure_findings(facts_by_label, required, targets)
    for label, deps in targets.items():
        if label in results:
            found.extend(run_findings(results[label], target_budget(deps, required)))
        elif deps:
            found.append(finding("fuzz-not-run", target=label))
    found.extend(regression_findings(regressions, results))
    return found


def run(args):
    required = load_policy(args.policy)
    facts_by_label = facts_data.load_facts_dir(args.facts)
    results = load_results(args.results)
    regressions = load_regressions(args.regressions)
    found = judge(facts_by_label, required, results, regressions)
    metadata = {"required_modules": sorted(required),
                "targets": {label: {"runs_done": r.runs_done, "corpus_files": r.corpus_files,
                                    "replayed": len(r.replayed), "phase": r.phase}
                            for label, r in sorted(results.items())}}
    return GateResult(GATE_ID, found, metadata)


def add_parser(subparsers):
    parser = subparsers.add_parser("fuzz", allow_abbrev=False,
                                   help="fuzz runs: required targets, crashes, budget, regression inputs")
    parser.add_argument("--results", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--regressions")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
