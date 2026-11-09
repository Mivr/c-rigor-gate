"""Reading the report `c_mutants` produces (rules/mutate.bzl, mutate/tool.py `collect`).

The report comes out of a build action but is still input: the reader accepts exactly the documented
shape (exit 2 otherwise), so a malformed or padded file cannot pass. It holds raw facts only; the
verdicts are derived in `mutants_verdict`.
"""

import os
import re
from dataclasses import dataclass

from rigor_lib import jsonio
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL

SCHEMA = 1
HASH = re.compile(r"[0-9a-f]{64}")
MUTANT_ID = re.compile(r"[0-9a-f]{16}")
TEST_NAME = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class Run:
    rc: int
    timed_out: bool
    results: object  # str or None
    killed_by: object = None  # a skipped run (T121): the test that had killed the mutant; rc, timed_out, results are empty


@dataclass(frozen=True)
class Source:
    file: str
    functions: tuple      # names of the functions that were mutated or have a reason
    unmutated: tuple      # of those, the names that carry the reason "no-mutable-token"
    definitions: int      # function definitions in the AST, counted independently of the above
    skipped: tuple  # of (name, file, reason): functions with a body that no mutant can reach
    hidden: tuple   # of (function, macro, line, defined_in): uses of product macros in mutated functions
    baseline_status: str
    baseline_hash: str
    original_hash: str
    baseline_o0_status: str = "ok"  # the unmodified source compiled again at -O0 (B15)
    baseline_o0_hash: str = ""


@dataclass(frozen=True)
class Mutant:
    id: str
    file: str
    line: int
    operator: str
    function: str
    original: str
    replacement: str
    status: str   # compile status: "ok" or "unviable"
    hash: str
    runs: dict    # test name -> Run
    o0: object = None  # (status, hash) of the -O0 compile of a candidate for equivalent / duplicate; else None


@dataclass(frozen=True)
class Report:
    label: str
    tests: tuple
    sources: tuple
    baseline_runs: dict
    mutants: tuple


def _fail(path, why):
    raise InternalError("%s: %s" % (path, why))


def _exact(path, obj, keys, what):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        _fail(path, "%s must be an object with exactly the keys %s" % (what, sorted(keys)))
    return obj


def _text(path, value, what):
    if not isinstance(value, str):
        _fail(path, "%s must be a string" % what)
    return value


def _int(path, value, what):
    if type(value) is not int:
        _fail(path, "%s must be an integer" % what)
    return value


def _digest(path, info, what):
    status = info["status"]
    if status not in ("ok", "unviable"):
        _fail(path, "%s: bad compile status %r" % (what, status))
    value = _text(path, info["hash"], what)
    if (status == "ok") != bool(HASH.fullmatch(value)):
        _fail(path, "%s: hash does not match status" % what)
    return status, value


def parse_run(path, run, what):
    if isinstance(run, dict) and set(run) == {"killed_by"}:   # not run: an earlier test of the mutant failed a check
        return Run(-1, False, None, _text(path, run["killed_by"], what))
    _exact(path, run, ("rc", "timed_out", "results"), what)
    if type(run["timed_out"]) is not bool:
        _fail(path, "%s: timed_out must be a boolean" % what)
    results = run["results"]
    if results is not None:
        _text(path, results, what)
    return Run(_int(path, run["rc"], what), run["timed_out"], results)


def parse_source(path, entry):
    _exact(path, entry, ("file", "sha256", "definitions", "functions", "skipped", "hidden", "baseline",
                         "baseline_o0", "original"), "source")
    baseline = _exact(path, entry["baseline"], ("status", "hash"), "baseline")
    baseline_o0 = _exact(path, entry["baseline_o0"], ("status", "hash"), "baseline_o0")
    original = _exact(path, entry["original"], ("status", "hash"), "original")
    if not isinstance(entry["functions"], list):
        _fail(path, "functions must be a list")
    names, unmutated = parse_functions(path, entry["functions"])
    status, base_hash = _digest(path, baseline, "baseline")
    _, original_hash = _digest(path, original, "original")
    status_o0, base_o0_hash = _digest(path, baseline_o0, "baseline_o0")
    return Source(_text(path, entry["file"], "file"), names, unmutated,
                  _int(path, entry["definitions"], "definitions"), parse_skipped(path, entry["skipped"]),
                  parse_hidden(path, entry["hidden"]), status, base_hash, original_hash,
                  status_o0, base_o0_hash)


def parse_functions(path, entries):
    """(names, names with the reason "no-mutable-token") of a source's `functions` list."""
    names = []
    unmutated = []
    for item in entries:
        if not isinstance(item, dict) or set(item) not in ({"name", "line"}, {"name", "line", "reason"}):
            _fail(path, "a function entry must be {name, line} or {name, line, reason}")
        name = _text(path, item["name"], "function name")
        _int(path, item["line"], "function line")
        if "reason" in item:
            if item["reason"] != "no-mutable-token":
                _fail(path, "bad function reason %r" % (item["reason"],))
            unmutated.append(name)
        names.append(name)
    return tuple(names), tuple(unmutated)


def parse_skipped(path, entries):
    if not isinstance(entries, list):
        _fail(path, "skipped must be a list")
    found = []
    for entry in entries:
        _exact(path, entry, ("name", "file", "reason"), "skipped function")
        if entry["reason"] not in ("macro", "header"):
            _fail(path, "bad reason %r" % (entry["reason"],))
        found.append((_text(path, entry["name"], "name"), _text(path, entry["file"], "file"), entry["reason"]))
    return tuple(found)


def parse_hidden(path, entries):
    """Uses of a product macro inside a function (R002 F1): {function, macro, line, defined_in}."""
    if not isinstance(entries, list):
        _fail(path, "hidden must be a list")
    found = []
    for entry in entries:
        _exact(path, entry, ("function", "macro", "line", "defined_in"), "hidden code entry")
        found.append((_text(path, entry["function"], "function"), _text(path, entry["macro"], "macro"),
                      _int(path, entry["line"], "line"), _text(path, entry["defined_in"], "defined_in")))
    return tuple(found)


def parse_mutant(path, item, tests):
    keys = ("id", "file", "begin_offset", "end_offset", "original", "replacement", "operator",
            "function", "line", "compile", "runs")
    _exact(path, item, keys, "mutant")
    if not MUTANT_ID.fullmatch(_text(path, item["id"], "mutant id")):
        _fail(path, "bad mutant id %r" % item["id"])
    info = item["compile"]
    if not isinstance(info, dict) or not {"status", "hash"} <= set(info) <= {"status", "hash", "detail", "o0"}:
        _fail(path, "mutant %s: bad compile info" % item["id"])
    status, digest = _digest(path, info, "mutant %s" % item["id"])
    low = None
    if "o0" in info:
        low = _digest(path, _exact(path, info["o0"], ("status", "hash"), "mutant %s o0" % item["id"]),
                      "mutant %s o0" % item["id"])
    if not isinstance(item["runs"], dict) or not set(item["runs"]) <= set(tests):
        _fail(path, "mutant %s: runs name unknown tests" % item["id"])
    runs = {t: parse_run(path, r, "mutant %s run" % item["id"]) for t, r in item["runs"].items()}
    return Mutant(item["id"], _text(path, item["file"], "file"), _int(path, item["line"], "line"),
                  _text(path, item["operator"], "operator"), _text(path, item["function"], "function"),
                  _text(path, item["original"], "original"),
                  _text(path, item["replacement"], "replacement"), status, digest, runs, low)


def parse_report(path, data):
    try:
        document = jsonio.strict_loads(data)
    except ValueError as exc:
        raise InternalError("%s: not valid JSON: %s" % (path, exc)) from exc
    _exact(path, document, ("schema", "label", "tests", "sources", "baseline_runs", "mutants"), "report")
    if document["schema"] != SCHEMA or type(document["schema"]) is not int:
        _fail(path, "unsupported schema")
    label = document["label"]
    if not isinstance(label, str) or not LABEL.fullmatch(label):
        _fail(path, "bad label %r" % (label,))
    tests = document["tests"]
    if not isinstance(tests, list) or not tests or not all(
            isinstance(t, str) and TEST_NAME.fullmatch(t) for t in tests) or len(set(tests)) != len(tests):
        _fail(path, "tests must be a non-empty list of distinct names")
    if not isinstance(document["baseline_runs"], dict) or set(document["baseline_runs"]) != set(tests):
        _fail(path, "baseline_runs must name exactly the tests")
    baseline = {t: parse_run(path, r, "baseline run") for t, r in document["baseline_runs"].items()}
    if not isinstance(document["sources"], list) or not isinstance(document["mutants"], list):
        _fail(path, "sources and mutants must be lists")
    sources = tuple(parse_source(path, s) for s in document["sources"])
    mutants = tuple(parse_mutant(path, m, tests) for m in document["mutants"])
    if len({(m.file, m.id) for m in mutants}) != len(mutants):
        _fail(path, "duplicate mutant ids")
    if {m.file for m in mutants} - {s.file for s in sources}:
        _fail(path, "a mutant names a file that is not a source")
    return Report(label, tuple(tests), sources, baseline, mutants)


def load_reports_dir(directory):
    """label -> Report for every `*.json` in `directory` (not recursive); anything else in it,
    an empty directory, or two reports for one label is exit 2."""
    if not os.path.isdir(directory):
        raise InternalError("results path is not a directory: %s" % directory)
    result = {}
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if not name.endswith(".json") or not os.path.isfile(full) or os.path.islink(full):
            raise InternalError("%s: not a mutation report (only regular *.json files belong here)" % full)
        report = parse_report(full, jsonio.read_bytes(full))
        if report.label in result:
            raise InternalError("%s: second report for %s" % (full, report.label))
        result[report.label] = report
    if not result:
        raise InternalError("no mutation reports in %s" % directory)
    return result
