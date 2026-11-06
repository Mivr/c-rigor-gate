"""The judgement of the `tests-stub` gate (P002, Q2): every new expected test fails on the stubs.

A test-author head *is* the stub commit, so this reads the head's results of both modes and builds
nothing. The new ids are `expected` minus `previous` (`expected-tests.previous.json`, required in this
role). Findings (errors unless noted):

  * `test-passes-on-stub` (id, mode, status): a new id that did not fail in that mode. A pass in either
    mode is the finding; a `skip` is not a fail either, so it is reported the same way with its status;
  * `missing-test` (id, mode): a new id absent from that mode's results;
  * `no-new-tests`: the new-id set is empty, so the grade judges nothing;
  * info `stub-timeout` (id, mode): a fail by timeout, which costs 10 s of farm time per mode.

Any `status: fail` counts as failing on the stub. Its kind, read from the ctest `reason`, is counted in
metadata per mode: `check` ("N of M checks failed"), `crash` (a signal, an exit status, a sanitizer
report, no or an invalid report), `timeout`, `no-checks`, and `other` (any reason ctest does not write).

`results_parse.TestRecord` carries no `reason`, so `parse_file` reads it back from the line
`results_parse.parse_file` already validated. The NOT_RUN and not-applicable cases are wiring (T041).
"""

import os
import re
from dataclasses import dataclass

from rigor_lib import jsonio, results_parse
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

GATE_ID = "tests-stub"
MODES = ("release", "san")
RESULT_SUFFIX = ".jsonl"
KINDS = ("check", "crash", "timeout", "no-checks", "other")
# ctest's reasons (ctest/ctest.c); a sanitizer summary may follow after "; ".
_KIND_PATTERNS = (
    ("check", re.compile(r"[0-9]+ of [0-9]+ checks failed(;|$)")),
    ("timeout", re.compile(r"timeout after [0-9]+ s(;|$)")),
    ("no-checks", re.compile(r"no checks executed(;|$)")),
    ("crash", re.compile(r"(killed by signal [0-9]+|exited with status [0-9]+ (before|after) reporting|"
                         r"exited without reporting|invalid report from the test process|"
                         r"sanitizer report in a test that looked passing)")),
)


@dataclass(frozen=True)
class ResultsFile:
    parsed: object   # results_parse.ParsedFile
    reasons: dict    # record line number -> reason text, or None when the line has none


def parse_file(name, data):
    """`results_parse.parse_file` plus the `reason` of every valid test record."""
    parsed = results_parse.parse_file(name, data)
    lines = data.split(b"\n")
    reasons = {}
    for record in parsed.records:
        try:
            obj = jsonio.strict_loads(lines[record.line - 1])
        except (IndexError, ValueError, RecursionError) as exc:
            raise InternalError("%s:%d: a parsed record cannot be read back: %s" % (name, record.line, exc)) \
                from exc
        reasons[record.line] = obj.get("reason") if isinstance(obj, dict) else None
    return ResultsFile(parsed, reasons)


def parse_directory(directory):
    """Every `*.jsonl` regular file of `directory` (not recursive), in name order."""
    if not os.path.isdir(directory):
        raise InternalError("results path is not a directory: %s" % directory)
    names = sorted(name for name in os.listdir(directory)
                   if name.endswith(RESULT_SUFFIX) and os.path.isfile(os.path.join(directory, name)))
    return [parse_file(name, jsonio.read_bytes(os.path.join(directory, name))) for name in names]


def fail_kind(reason):
    """The kind of a failed test from its ctest reason."""
    if not isinstance(reason, str):
        return "other"
    for kind, pattern in _KIND_PATTERNS:
        if pattern.match(reason):
            return kind
    return "other"


def _id_set(ids, what):
    if not isinstance(ids, (set, frozenset, list, tuple)):
        raise InternalError("%s must be a collection of test ids" % what)
    for test_id in ids:
        if not isinstance(test_id, str) or not results_parse.TEST_ID.fullmatch(test_id):
            raise InternalError("%s: bad test id %r" % (what, test_id))
    if len(set(ids)) != len(ids):
        raise InternalError("%s: duplicate test ids" % what)
    return set(ids)


def _records_by_id(files, mode):
    if not isinstance(files, (list, tuple)) or not all(isinstance(f, ResultsFile) for f in files):
        raise InternalError("results of mode %s must be a list of stub_judge.ResultsFile" % mode)
    groups = {}
    for item in files:
        for record in item.parsed.records:
            groups.setdefault(record.test_id, []).append((record, item.reasons.get(record.line)))
    return groups


def _judge_id(test_id, mode, entries, counts):
    if not entries:
        return [finding("missing-test", id=test_id, mode=mode)]
    for record, _ in entries:
        if record.status != "fail":
            return [finding("test-passes-on-stub", id=test_id, mode=mode, status=record.status)]
    found = []
    for _, reason in entries:
        kind = fail_kind(reason)
        counts[kind] += 1
        if kind == "timeout":
            found.append(finding("stub-timeout", SEVERITY_INFO, id=test_id, mode=mode))
    return found[:1]


def judge(expected, previous, parsed_by_mode):
    """GateResult of `tests-stub`. `parsed_by_mode` maps "release" and "san" to lists of ResultsFile."""
    if previous is None:
        raise InternalError("role test-author needs expected-tests.previous.json")
    new_ids = sorted(_id_set(expected, "expected") - _id_set(previous, "previous"))
    if not isinstance(parsed_by_mode, dict) or set(parsed_by_mode) != set(MODES):
        raise InternalError("tests-stub needs the results of exactly the modes %s" % ", ".join(MODES))
    found = [] if new_ids else [finding("no-new-tests")]
    kinds = {}
    for mode in MODES:
        groups = _records_by_id(parsed_by_mode[mode], mode)
        counts = {kind: 0 for kind in KINDS}
        for test_id in new_ids:
            found.extend(_judge_id(test_id, mode, groups.get(test_id, []), counts))
        kinds[mode] = counts
    metadata = {"new_ids": new_ids, "new_count": len(new_ids), "fail_kinds": kinds}
    return GateResult(GATE_ID, found, metadata)
