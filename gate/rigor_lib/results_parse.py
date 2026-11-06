"""Parse the JSON Lines test results written by the `ctest` framework.

Line formats (one JSON object per line):
  {"id": "<suite>/<name>", "status": "pass"|"fail"|"skip", "asserts": <int >= 0>}
  {"summary": {"total": <int>, "passed": <int>}}      exactly one, as the last line of a file
Anything else is reported as a finding; nothing here raises for bad product data.
"""

import re
from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.findings import finding

TEST_ID = re.compile(r"[A-Za-z0-9_.+:-]+/[A-Za-z0-9_.+:-]+")
STATUSES = ("pass", "fail", "skip")
_TEST_KEYS = {"id", "status", "asserts"}
_SUMMARY_KEYS = {"total", "passed"}


@dataclass(frozen=True)
class TestRecord:
    __test__ = False  # not a unittest case, despite the name

    test_id: str
    status: str
    asserts: int
    file: str
    line: int


@dataclass(frozen=True)
class ParsedFile:
    name: str
    records: list
    problems: list  # findings


class _BadLine(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_test(obj):
    if set(obj) != _TEST_KEYS:
        raise _BadLine("test-keys")
    if not isinstance(obj["id"], str) or not TEST_ID.fullmatch(obj["id"]):
        raise _BadLine("bad-id")
    if obj["status"] not in STATUSES:
        raise _BadLine("bad-status")
    if not _is_count(obj["asserts"]):
        raise _BadLine("bad-asserts")
    return obj["id"], obj["status"], obj["asserts"]


def _parse_summary(obj):
    if set(obj) != {"summary"}:
        raise _BadLine("summary-keys")
    inner = obj["summary"]
    if not isinstance(inner, dict) or set(inner) != _SUMMARY_KEYS:
        raise _BadLine("bad-summary")
    if not _is_count(inner["total"]) or not _is_count(inner["passed"]):
        raise _BadLine("bad-summary")
    return inner["total"], inner["passed"]


def _parse_line(raw):
    """Returns ("test", (id, status, asserts)) or ("summary", (total, passed))."""
    try:
        obj = jsonio.strict_loads(raw)
    except (ValueError, RecursionError):
        raise _BadLine("not-json") from None
    if not isinstance(obj, dict):
        raise _BadLine("not-object")
    if "summary" in obj:
        return "summary", _parse_summary(obj)
    return "test", _parse_test(obj)


def _split_lines(data):
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return lines


def parse_file(name, data):
    """Parse one results file; every defect becomes a finding in `problems`."""
    records = []
    problems = []
    summary = None
    for number, raw in enumerate(_split_lines(data), start=1):
        try:
            kind, payload = _parse_line(raw)
        except _BadLine as bad:
            problems.append(finding("malformed-line", file=name, line=number, reason=bad.reason))
            continue
        if summary is not None:
            reason = "second-summary" if kind == "summary" else "line-after-summary"
            problems.append(finding("malformed-line", file=name, line=number, reason=reason))
        elif kind == "summary":
            summary = payload
        else:
            records.append(TestRecord(payload[0], payload[1], payload[2], name, number))
    problems.extend(_summary_problems(name, records, summary))
    return ParsedFile(name, records, problems)


def _summary_problems(name, records, summary):
    if summary is None:
        return [finding("missing-summary", file=name)]
    total = len(records)
    passed = sum(1 for record in records if record.status == "pass")
    if (total, passed) == summary:
        return []
    return [finding("summary-mismatch", file=name, counted_total=total, counted_passed=passed,
                    summary_total=summary[0], summary_passed=summary[1])]
