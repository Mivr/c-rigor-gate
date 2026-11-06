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
from rigor_lib.findings import finding

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


def baseline_findings(report):
    """The unmutated build must reproduce Buck2's objects and pass every test with assertions."""
    found = []
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
    """(verdicts in report order, findings) for every mutant of a report."""
    base_hash = {source.file: source.baseline_hash for source in report.sources}
    first = {}  # (file, hash) -> the Verdict of the first mutant with that object
    verdicts = []
    found = []
    for mutant in report.mutants:
        key = (mutant.file, mutant.hash)
        if mutant.status == "unviable":
            verdict = Verdict(mutant, "unviable")
        elif mutant.hash == base_hash[mutant.file]:
            verdict = Verdict(mutant, "equivalent")
        elif key in first:
            verdict = Verdict(mutant, "duplicate", first[key].mutant.id)
        else:
            name, problems = mutant_outcomes(report, mutant, baseline_ids)
            found.extend(problems)
            verdict = Verdict(mutant, name)
            first[key] = verdict
        verdicts.append(verdict)
    return verdicts, found
