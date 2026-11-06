"""Deriving a verdict for every mutant from the raw facts in a report.

    unviable      the mutated source did not compile (reported, not counted against the tests)
    equivalent    its object is byte-identical to the unmutated object (trivially compiler-equivalent)
    duplicate     its object equals an earlier mutant's; that mutant's verdict stands for both
    killed-assert some test failed with a check failure (the tests noticed the wrong value)
    killed-crash  a test crashed, was killed, timed out or tripped a sanitizer, or no test failed a check
    survived      every test passed: the tests do not constrain this behaviour
    unrun         a mutant that had to run did not, or its results were unusable (a finding says why)
"""

import re
from dataclasses import dataclass

from rigor_lib import jsonio, results_parse
from rigor_lib.findings import SEVERITY_INFO, finding

VERDICTS = ("killed-assert", "killed-crash", "survived", "equivalent", "duplicate", "unviable", "unrun")
CHECK_FAILURE = re.compile(r"[0-9]+ of [0-9]+ checks failed; first: ")


@dataclass(frozen=True)
class Verdict:
    mutant: object
    verdict: str
    of: str = ""  # for a duplicate: the id it duplicates


def _line_reasons(text):
    """reason of every test line of already validated results, by test id."""
    reasons = {}
    for raw in text.encode("utf-8").split(b"\n"):
        if raw:
            obj = jsonio.strict_loads(raw)
            if "id" in obj:
                reasons[obj["id"]] = obj.get("reason", "")
    return reasons


def outcome_of_run(run):
    """('assert' | 'crash' | 'pass' | 'bad', ids, why) for one test binary run of one mutant."""
    if run.timed_out or run.rc not in (0, 1) or not run.results:
        return "crash", frozenset(), "rc %d%s" % (run.rc, " (timeout)" if run.timed_out else "")
    parsed = results_parse.parse_file("results", run.results.encode("utf-8"))
    if parsed.problems or not parsed.records:
        return "bad", frozenset(), "unparsable results"
    ids = frozenset(record.test_id for record in parsed.records)
    if any(record.status == "skip" for record in parsed.records):
        return "bad", ids, "skipped test"
    failed = [record for record in parsed.records if record.status != "pass"]
    if run.rc == 0 and failed or run.rc == 1 and not failed:
        return "bad", ids, "exit status disagrees with the results"
    reasons = _line_reasons(run.results)
    if any(CHECK_FAILURE.match(reasons.get(record.test_id, "")) for record in failed):
        return "assert", ids, ""
    return ("crash" if failed else "pass"), ids, ""


def accounting_findings(report):
    """B19: every function definition of every source is accounted for. The generator counted the
    definitions in the AST with code of its own (`definitions`); the lists it wrote must add up to that
    count, name every function once, and agree with the mutants. A function that is neither mutated nor
    given a reason, or a mutant of a function nobody listed, means the generator lost something."""
    found = []
    for source in report.sources:
        listed = list(source.functions) + [name for name, _, _ in source.skipped]
        problems = {}
        if len(listed) != source.definitions:
            problems["listed"] = len(listed)
        if len(set(source.functions)) != len(source.functions) \
                or len(set(source.functions) & {name for name, _, _ in source.skipped}):
            problems["duplicates"] = True
        mutated = {m.function for m in report.mutants if m.file == source.file}
        silent = sorted(set(source.functions) - mutated - set(source.unmutated))
        stray = sorted(mutated - set(source.functions))
        reasoned = sorted(set(source.unmutated) & mutated)
        if silent:
            problems["no mutant and no reason"] = silent
        if stray:
            problems["mutants of unlisted functions"] = stray
        if reasoned:
            problems["reason given although mutated"] = reasoned
        lost = sorted({name for name, _, _, _ in source.hidden} - set(source.functions))
        if lost:
            problems["macro-hidden code in unlisted functions"] = lost
        if problems:
            found.append(finding("unaccounted-function", module=report.label, file=source.file,
                                 definitions=source.definitions, listed=len(listed),
                                 problems=problems))
        found.extend(finding("no-mutable-token", severity=SEVERITY_INFO, module=report.label,
                             file=source.file, function=name)
                     for name in source.unmutated if name not in mutated)
    return found


def baseline_findings(report):
    """The unmutated build must reproduce Buck2's objects and pass every test with assertions
    (and, first, every function definition must be accounted for)."""
    found = accounting_findings(report)
    for source in report.sources:
        if source.baseline_status != "ok" or source.baseline_hash != source.original_hash:
            found.append(finding("harness-mismatch", module=report.label, file=source.file))
    ids = {}
    for name in report.tests:
        run = report.baseline_runs[name]
        parsed = results_parse.parse_file(name, run.results.encode("utf-8")) if run.results else None
        ok = parsed is not None and not parsed.problems and parsed.records and run.rc == 0 \
            and not run.timed_out and all(r.status == "pass" and r.asserts >= 1 for r in parsed.records)
        if ok:
            ids[name] = frozenset(r.test_id for r in parsed.records)
        else:
            found.append(finding("baseline-red", module=report.label, test=name))
    return found, ids


def mutant_outcomes(report, mutant, baseline_ids):
    """Combine the per-test outcomes of a live mutant: (verdict, findings)."""
    found = []
    kinds = []
    for name in report.tests:
        run = mutant.runs.get(name)
        if run is None:
            found.append(finding("missing-run", module=report.label, id=mutant.id, test=name))
            continue
        kind, ids, why = outcome_of_run(run)
        if kind == "bad" or (kind != "crash" and name in baseline_ids and ids != baseline_ids[name]):
            found.append(finding("bad-results", module=report.label, id=mutant.id, test=name,
                                 reason=why or "different tests than the baseline"))
            continue
        kinds.append(kind)
    if found:
        return "unrun", found
    if "assert" in kinds:
        return "killed-assert", found
    return ("killed-crash" if "crash" in kinds else "survived"), found


def derive(report, baseline_ids):
    """(verdicts in report order, findings) for every mutant of a report.

    B15 (R001 R2): an object identical to the baseline's (or to an earlier mutant's) at -O2 says little, because the
    optimiser can fold a behaviour-changing mutation away. Such a candidate carries the result of compiling it again
    at -O0 (`mutant.o0`); it is `equivalent` (or a `duplicate`) only if the -O0 object is identical as well (to the
    baseline's -O0 object, or to that of the earlier mutant with the same -O2 object). Otherwise it is live: it was
    run with its -O0 object like any other mutant. A candidate without a usable -O0 result is `unrun`
    (`missing-o0`), never equivalent: the claim could not be checked. `rules/mutate.bzl` `_stage3` decides which
    mutants to run by the same rule; keep the two in step."""
    base_hash = {source.file: source.baseline_hash for source in report.sources}
    seen = set()  # (file, -O2 hash) of every compiled mutant so far
    same = {(source.file, source.baseline_hash, source.baseline_o0_hash): None for source in report.sources}
    verdicts = []
    found = []
    for mutant in report.mutants:
        key = (mutant.file, mutant.hash)
        if mutant.status == "unviable":
            verdict = Verdict(mutant, "unviable")
        elif mutant.hash == base_hash[mutant.file] or key in seen:
            verdict = _folded_verdict(report, mutant, baseline_ids, same, found)
        else:
            verdict = _live_verdict(report, mutant, baseline_ids, found)
            if mutant.o0 is not None and mutant.o0[0] == "ok":
                same.setdefault((mutant.file, mutant.hash, mutant.o0[1]), verdict)
        if mutant.status == "ok":
            seen.add(key)
        verdicts.append(verdict)
    return verdicts, found


def _live_verdict(report, mutant, baseline_ids, found):
    name, problems = mutant_outcomes(report, mutant, baseline_ids)
    found.extend(problems)
    return Verdict(mutant, name)


def _folded_verdict(report, mutant, baseline_ids, same, found):
    """A mutant whose -O2 object equals the baseline's or an earlier mutant's: decided with its -O0 object."""
    if mutant.o0 is None or mutant.o0[0] != "ok":
        found.append(finding("missing-o0", module=report.label, id=mutant.id,
                             reason="no -O0 compile" if mutant.o0 is None else "the -O0 compile failed"))
        return Verdict(mutant, "unrun")
    key = (mutant.file, mutant.hash, mutant.o0[1])
    if key in same:
        earlier = same[key]
        return Verdict(mutant, "equivalent") if earlier is None else Verdict(mutant, "duplicate", earlier.mutant.id)
    verdict = _live_verdict(report, mutant, baseline_ids, found)
    same[key] = verdict
    return verdict


def tce_counts(report, verdicts):
    """B15: how many mutants had the baseline's -O2 object, and how many of those have its -O0 object too
    (the verdict `equivalent`). The difference ran as live mutants (or are `unrun` for want of a -O0 compile)."""
    base_hash = {source.file: source.baseline_hash for source in report.sources}
    folded = [v for v in verdicts if v.mutant.status == "ok" and v.mutant.hash == base_hash[v.mutant.file]]
    return {"equivalent_o2": len(folded), "equivalent_o0": sum(1 for v in folded if v.verdict == "equivalent")}
