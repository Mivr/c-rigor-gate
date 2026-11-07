"""Perf kills (T090, G30): a mutant that passes every test but makes a declared perf target leave its complexity
class is `killed-perf`, not a survivor.

Input: the `perf.json` files of the `c_mutants` targets (rules/mutate.bzl, stage 4; the `[perf]` sub-target), one per
module with `perf = [...]`, and the classes from the policy:

    {"schema": 1, "label": "//gate-mutants:m000_x",
     "targets": {"//x:y_perf": {"baseline": [<record>...],
                                "mutants": {"<mutant id>": [<record>...] | [{"marker": ...}]}}}}

Records are those of `perf.jsonl` (docs/perf.md). The unmutated module is measured through the same link as the mutants
(`baseline`); a mutant is judged only when its baseline is in the class. The cost is one link and one perf run per
target for each mutant that survived all tests (functional killers cost nothing).

A mutant is killed-perf when, for some target, its records are `ok` and a counter leaves the class (`perf_judge.exceeded`),
or its harness run timed out (`timeout` status: the run exceeded 100 s, which is a blown class by any measure). A mutant that
crashes, fails to link, or whose run is not ok otherwise stays `survived` (that is a behaviour the tests did not notice, not a
complexity change). Findings: `perf-counter-unavailable` (the baseline could not be counted: no verdict; severity follows
the level), `perf-baseline-bad` (baseline not ok, or outside its class), `perf-evidence-missing` (a survivor without a
perf record: the rule and the verdicts disagree; always an error).
"""

import os

from rigor_lib import jsonio, perf_judge
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO, finding
from rigor_lib.mutants_verdict import Verdict

SCHEMA = 1
STRICT_LEVELS = ("L3", "L4", "L5")


def _fail(path, why):
    raise InternalError("%s: %s" % (path, why))


def _records(path, value, what):
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        _fail(path, "%s must be a list of objects" % what)
    return tuple(value)


def parse(path, data):
    """(label, {target: (baseline records, {key: records})}) of one perf.json."""
    try:
        document = jsonio.strict_loads(data)
    except ValueError as exc:
        raise InternalError("%s: not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(document, dict) or set(document) != {"schema", "label", "targets"} \
            or document["schema"] != SCHEMA or type(document["schema"]) is not int:
        _fail(path, "not a perf evidence file (schema %d)" % SCHEMA)
    label = document["label"]
    if not isinstance(label, str) or not LABEL.fullmatch(label) or not isinstance(document["targets"], dict):
        _fail(path, "bad label or targets")
    targets = {}
    for name, entry in document["targets"].items():
        if not LABEL.fullmatch(name) or not isinstance(entry, dict) or set(entry) != {"baseline", "mutants"} \
                or not isinstance(entry["mutants"], dict):
            _fail(path, "bad target %r" % (name,))
        targets[name] = (_records(path, entry["baseline"], "baseline"),
                         {key: _records(path, value, "mutant records") for key, value in entry["mutants"].items()})
    return label, targets


def load_dir(directory):
    """label -> targets for every `*.json` in the directory (a missing directory is no evidence)."""
    if directory is None or not os.path.isdir(directory):
        return {}
    found = {}
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if not name.endswith(".json") or not os.path.isfile(full) or os.path.islink(full):
            _fail(full, "not a perf evidence file (only regular *.json files belong here)")
        label, targets = parse(full, jsonio.read_bytes(full))
        if label in found:
            _fail(full, "second perf evidence for %s" % label)
        found[label] = targets
    return found


def mutant_key(mutant):
    return mutant.id


def baseline_state(cost_class, records):
    """'ok', 'unavailable', or a reason text for a baseline that cannot judge mutants."""
    _, _, why = perf_judge.usable(records)
    if why == "unavailable":
        return "unavailable"
    if why is not None:
        return "not ok (%s)" % perf_judge.status_of(records)
    if perf_judge.exceeded(cost_class, records):
        return "outside %s" % cost_class
    return "ok"


def mutant_kill(cost_class, records):
    """The evidence dict if these records of a surviving mutant leave the class, else None."""
    if any(r.get("status") == "timeout" for r in records):
        return {"counter": "timeout", "n1": 0, "n2": 0, "count1": 0, "count2": 0, "ratio": "inf", "limit": 0}
    _, _, why = perf_judge.usable(records)
    if why is not None:
        return None
    bad = perf_judge.exceeded(cost_class, records)
    return bad[0] if bad else None


def apply(report, level, verdicts, targets, classes):
    """(verdicts with the perf kills, findings, summary) for one module. `targets` is the evidence of the module
    (label -> (baseline, mutants)); `classes` the declared {target: class}."""
    severity = SEVERITY_ERROR if level in STRICT_LEVELS else SEVERITY_INFO
    survivors = [v for v in verdicts if v.verdict == "survived"]
    found = []
    usable = {}
    for target, cost_class in sorted(classes.items()):
        if target not in targets:
            found.append(finding("perf-evidence-missing", module=report.label, target=target, mutant="*"))
            continue
        state = baseline_state(cost_class, targets[target][0])
        if state == "ok":
            usable[target] = cost_class
        elif survivors:
            rule = "perf-counter-unavailable" if state == "unavailable" else "perf-baseline-bad"
            extra = {} if state == "unavailable" else {"reason": state}
            found.append(finding(rule, severity=severity, module=report.label, target=target,
                                 **{"class": cost_class}, **extra))
    kills = {}
    for verdict in survivors:
        for target, cost_class in sorted(usable.items()):
            records = targets[target][1].get(mutant_key(verdict.mutant))
            if records is None:
                found.append(finding("perf-evidence-missing", module=report.label, target=target, mutant=verdict.mutant.id))
                continue
            evidence = mutant_kill(cost_class, records)
            if evidence is not None and mutant_key(verdict.mutant) not in kills:
                kills[mutant_key(verdict.mutant)] = dict(evidence, target=target, **{"class": cost_class})
    result = [Verdict(v.mutant, "killed-perf") if mutant_key(v.mutant) in kills and v.verdict == "survived" else v
              for v in verdicts]
    summary = {"targets": sorted(classes), "candidates": len(survivors),
               "killed": [dict(kills[mutant_key(v.mutant)], id=v.mutant.id, at="%s:%d" % (v.mutant.file, v.mutant.line))
                          for v in survivors if mutant_key(v.mutant) in kills]}
    return result, found, summary
