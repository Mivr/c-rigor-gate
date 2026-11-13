"""Builders for the `rigor fuzz` tests: facts files, a results directory, policy and regression files."""

import json
import re
from pathlib import Path

LIB = "//p:parse"
FUZZ = "//p:fz"
SHA_A = "a" * 64
SHA_B = "b" * 64
FRAME = "    #0 0xADDR in parse_run p/parse.c:15:22\n    #1 0xADDR in LLVMFuzzerTestOneInput p/fz.c:11:14\n"
CRASH_REPORT = "fuzz: -seed=1 -runs=200000 verdict: fail rc=1\n==PID==ERROR: AddressSanitizer: x\n" + FRAME


def unit(defined=(), undefined=()):
    return {"name": "a.c.o", "defined": sorted(defined), "weak": [], "undefined": sorted(undefined),
            "mutable": [], "data": [], "pragmas": [], "attributes": [], "identifiers": [], "line_directives": []}


def facts_doc(label, kind, units, deps=()):
    return {"schema": 1, "label": label, "kind": kind, "deps": sorted(deps), "units": units, "system_libs": []}


def write_facts(directory, docs):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for number, doc in enumerate(docs):
        (directory / ("f%d.json" % number)).write_text(json.dumps(doc))
    return directory


def default_facts(directory, calls=True, with_target=True):
    docs = [facts_doc(LIB, "c_library", [unit(defined=["parse_run"])])]
    if with_target:
        undefined = ["parse_run"] if calls else ["memcpy"]
        docs.append(facts_doc(FUZZ, "c_fuzz", [unit(defined=["LLVMFuzzerTestOneInput"], undefined=undefined)], deps=[LIB]))
    return write_facts(directory, docs)


def stats_doc(passed=True, runs_done=200000, corpus_files=0, replayed=0, phase="budget", sha=""):
    return {"runs_done": runs_done, "corpus_files": corpus_files, "replayed": replayed, "phase": phase,
            "reproducer_sha256": sha}


def write_run(directory, ident, label, stats, verdict="pass", report="fuzz: ok\n", replayed=(), index=None):
    """Writes the files of one run and (re)writes `index.json` with it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (ident + ".stats.json")).write_text(json.dumps(stats))
    (directory / (ident + ".verdict")).write_text(verdict + "\n")
    (directory / (ident + ".report")).write_text(report)
    (directory / (ident + ".replayed")).write_text("".join(s + "\n" for s in replayed))
    path = directory / "index.json"
    current = json.loads(path.read_text()) if path.exists() else {}
    current[label] = ident
    path.write_text(json.dumps(current if index is None else index))
    return directory


def passing_results(directory, **kw):
    return write_run(directory, "fz", FUZZ, stats_doc(**kw))


def policy_file(path, text=None):
    Path(path).write_text(text if text is not None else '[module."%s"]\nfuzz = true\n' % LIB)
    return path


def rules(path):
    return sorted(f["rule"] for f in json.loads(Path(path).read_text())["findings"])


def findings(path, rule):
    return [f for f in json.loads(Path(path).read_text())["findings"] if f["rule"] == rule]


def default_budget_from_bzl(root):
    text = (Path(root) / "rules" / "fuzz.bzl").read_text()
    return (int(re.search(r"^FUZZ_DEFAULT_RUNS = (\d+)$", text, re.M).group(1)),
            int(re.search(r"^FUZZ_MAX_RUNS = (\d+)$", text, re.M).group(1)))
