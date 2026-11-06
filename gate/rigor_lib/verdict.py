"""`rigor verdict`: combine gate results into one canonical verdict.

Each gate writes `<gate id>.json` (see findings.GateResult). The verdict lists the gates in the
order of the order file; a gate with no result file is NOT_RUN, which is a failure.
`core` is deterministic and hashed (`core_sha256`); everything volatile is in `metadata`.
"""

import os
import re

from rigor_lib import jsonio, verdict_inputs
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS

GATE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]*")
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_RUN = "NOT_RUN"
_RESULT_KEYS = {"gate", "status", "findings", "metadata"}


def read_order(path):
    """Gate ids, one per line, in order. Blank, malformed or repeated ids are errors."""
    return parse_order(jsonio.read_bytes(path))


def parse_order(data):
    """`read_order` over bytes already read (so a grade hashes the bytes it used)."""
    text = data.decode("utf-8")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    for gate_id in lines:
        if not GATE_ID_PATTERN.fullmatch(gate_id):
            raise InternalError("bad gate id in order file: %r" % gate_id)
    if len(set(lines)) != len(lines):
        raise InternalError("duplicate gate id in order file")
    return lines


def _check_finding(gate_id, item):
    if not isinstance(item, dict) or not isinstance(item.get("rule"), str):
        raise InternalError("%s: finding without a rule" % gate_id)
    if item.get("severity") not in (SEVERITY_ERROR, SEVERITY_INFO):
        raise InternalError("%s: finding with a bad severity" % gate_id)


def read_gate_result(path, gate_id):
    """Load and strictly validate one gate result file."""
    try:
        document = jsonio.strict_loads(jsonio.read_bytes(path))
    except ValueError as exc:
        raise InternalError("%s is not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(document, dict) or set(document) != _RESULT_KEYS:
        raise InternalError("%s has the wrong shape" % path)
    if document["gate"] != gate_id:
        raise InternalError("%s belongs to gate %r, not %r" % (path, document["gate"], gate_id))
    if document["status"] not in (STATUS_PASS, STATUS_FAIL):
        raise InternalError("%s has a bad status" % path)
    if not isinstance(document["findings"], list) or not isinstance(document["metadata"], dict):
        raise InternalError("%s has bad findings or metadata" % path)
    for item in document["findings"]:
        _check_finding(gate_id, item)
    has_error = any(item["severity"] == SEVERITY_ERROR for item in document["findings"])
    if (document["status"] == STATUS_FAIL) != has_error:
        raise InternalError("%s: status disagrees with its findings" % path)
    return document


def _findings_digest(findings):
    ordered = sorted(findings, key=jsonio.canonical_dumps)
    return jsonio.sha256_hex(jsonio.canonical_dumps(ordered))


def gate_entry(gate_id, document):
    """The deterministic summary of one gate for the verdict core."""
    if document is None:
        return {"id": gate_id, "status": STATUS_NOT_RUN, "findings_count": 0,
                "findings_sha256": _findings_digest([])}
    findings = document["findings"]
    return {"id": gate_id, "status": document["status"], "findings_count": len(findings),
            "findings_sha256": _findings_digest(findings)}


def load_results(results_dir, order):
    """gate id -> result document (or None if the gate did not run)."""
    if not os.path.isdir(results_dir):
        raise InternalError("results path is not a directory: %s" % results_dir)
    documents = {}
    for gate_id in order:
        path = os.path.join(results_dir, gate_id + ".json")
        if not os.path.lexists(path):
            documents[gate_id] = None
        elif os.path.isfile(path):
            documents[gate_id] = read_gate_result(path, gate_id)
        else:
            raise InternalError("%s is not a regular file" % path)
    return documents


def build_core(order, documents):
    gates = [gate_entry(gate_id, documents[gate_id]) for gate_id in order]
    passed = bool(gates) and all(entry["status"] == STATUS_PASS for entry in gates)
    return {"overall": STATUS_PASS if passed else STATUS_FAIL, "gates": gates}


def build_verdict(core, order_path, results_dir, order, documents):
    unlisted = sorted(name for name in os.listdir(results_dir)
                      if name.endswith(".json") and name[:-len(".json")] not in order)
    gate_metadata = {gate_id: doc["metadata"] for gate_id, doc in documents.items()
                     if doc is not None}
    return {
        "core": core,
        "core_sha256": jsonio.sha256_hex(jsonio.canonical_dumps(core)),
        "metadata": {"gate_metadata": gate_metadata, "order_file": str(order_path),
                     "results_dir": str(results_dir), "unlisted_results": unlisted},
    }


def run(args):
    order = read_order(args.order)
    documents = load_results(args.results, order)
    core = build_core(order, documents)
    verdict = build_verdict(core, args.order, args.results, order, documents)
    jsonio.write_atomic(args.out, jsonio.canonical_dumps(verdict))
    for entry in core["gates"]:
        print("  %-14s %s" % (entry["id"], entry["status"]))
    print("verdict: %s" % core["overall"])
    return EXIT_PASS if core["overall"] == STATUS_PASS else EXIT_FAIL


def add_parser(subparsers):
    parser = subparsers.add_parser("verdict", allow_abbrev=False,
                                   help="combine gate results into one verdict")
    parser.add_argument("--order", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--out", required=True)
    parser.set_defaults(handler=run, gate_id=None)
    verdict_inputs.add_verify_parser(subparsers)
