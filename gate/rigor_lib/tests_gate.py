"""`rigor tests`: the expected tests all ran, passed, and asserted something."""

import os

from rigor_lib import approval_args, approvals, jsonio, results_parse
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "tests"
RESULT_SUFFIX = ".jsonl"


def load_id_list(path):
    """Read `{"ids": [...]}`. The file is gate-owned input, so any defect is an internal error."""
    try:
        document = jsonio.strict_loads(jsonio.read_bytes(path))
    except ValueError as exc:
        raise InternalError("%s is not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(document, dict) or set(document) != {"ids"}:
        raise InternalError("%s must be an object with exactly the key 'ids'" % path)
    ids = document["ids"]
    if not isinstance(ids, list):
        raise InternalError("%s: 'ids' must be a list" % path)
    for test_id in ids:
        if not isinstance(test_id, str) or not results_parse.TEST_ID.fullmatch(test_id):
            raise InternalError("%s: bad test id %r" % (path, test_id))
    if len(set(ids)) != len(ids):
        raise InternalError("%s: duplicate test ids" % path)
    return set(ids)


def parse_results_directory(directory):
    """Parse every `*.jsonl` file (not recursive), in name order."""
    if not os.path.isdir(directory):
        raise InternalError("results path is not a directory: %s" % directory)
    names = sorted(name for name in os.listdir(directory)
                   if name.endswith(RESULT_SUFFIX) and os.path.isfile(os.path.join(directory, name)))
    return [results_parse.parse_file(name, jsonio.read_bytes(os.path.join(directory, name)))
            for name in names]


def group_by_id(parsed_files):
    groups = {}
    for parsed in parsed_files:
        for record in parsed.records:
            groups.setdefault(record.test_id, []).append(record)
    return groups


def expected_test_findings(test_id, records):
    if not records:
        return [finding("missing-test", id=test_id)]
    if len(records) > 1:
        return [finding("duplicate-test", id=test_id)]
    record = records[0]
    found = []
    if record.status != "pass":
        found.append(finding("test-not-pass", id=test_id, status=record.status))
    if record.asserts < 1:
        found.append(finding("no-assertions", id=test_id, asserts=record.asserts))
    return found


def unexpected_test_findings(test_id, records):
    if len(records) > 1:
        return [finding("duplicate-test", id=test_id)]
    if records[0].status == "fail":
        return [finding("unexpected-failing-test", id=test_id)]
    return [finding("unexpected-test", severity=SEVERITY_INFO, id=test_id)]


def removal_findings(expected, previous, approval_set, used):
    """Tests in the previous expected list but not in this one need a test-removal approval."""
    found = []
    for test_id in sorted(previous - expected):
        approval = approval_set.covering(approvals.KIND_TEST_REMOVAL, test_id)
        if approval is None:
            found.append(finding("test-removed", id=test_id))
        else:
            used.add(approval.stem)
    return found


def run(args):
    expected = load_id_list(args.expected)
    previous = load_id_list(args.previous) if args.previous else None
    parsed_files = parse_results_directory(args.results)
    approval_set = approval_args.load_from_args(args)
    used = set()
    found = list(approval_set.problems)
    if not expected:
        found.append(finding("expected-empty"))
    if not parsed_files:
        found.append(finding("no-results"))
    for parsed in parsed_files:
        found.extend(parsed.problems)
    groups = group_by_id(parsed_files)
    for test_id in sorted(expected):
        found.extend(expected_test_findings(test_id, groups.get(test_id, [])))
    for test_id in sorted(set(groups) - expected):
        found.extend(unexpected_test_findings(test_id, groups[test_id]))
    if previous is not None:
        found.extend(removal_findings(expected, previous, approval_set, used))
    metadata = {"result_files": [parsed.name for parsed in parsed_files],
                "expected_count": len(expected), "approvals_used": sorted(used)}
    return GateResult(GATE_ID, found, metadata)


def add_parser(subparsers):
    parser = subparsers.add_parser("tests", allow_abbrev=False,
                                   help="expected tests ran, passed and asserted")
    parser.add_argument("--results", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--out")
    approval_args.add_approval_arguments(parser, repo_and_head_optional=True)
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
