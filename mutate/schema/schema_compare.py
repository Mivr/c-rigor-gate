#!/usr/bin/env python3
"""Report and comparison of the schema mutation engine (T124). Python 3 stdlib only.

    schema_compare.py collect --manifest M --out F
        Merge what the schema build made (the mutant lists, the tables, the reach and kill results) into one report
        {"engine": "schema", ...}: for every mutant v1 would run, its status (`eligible` with a class, `ineligible`
        with a reason code, `schema-unviable`), its runs per test (`unreached` where no run was made) and the counts.
    schema_compare.py compare --v1 REPORT --schema REPORT [--out F] [--strict]
        For every schema-eligible mutant: the v1 class (killed-assert, killed-crash, survived) against the schema class.
        Every disagreement is listed with file, line, operator and both records. `unreached` means "no test executes
        the mutated site", which v1 can only see as a survivor, so the two compare as equal. A disagreement that is
        explained by construction (v1 ran the -O0 object of a mutant the optimiser had folded) says so. With
        --strict the exit status is 1 if any disagreement is unexplained.

The class of a mutant is decided from its run records by `classify`, the one definition both sides use; it is the rule
of `rigor mutants` (mutants_verdict.outcome_of_run / mutant_outcomes) without the baseline-id cross-check.
"""

import argparse
import json
import re
import sys

CHECK_FAILURE = re.compile(r"[0-9]+ of [0-9]+ checks failed; first: ")
SURVIVED, KILLED_ASSERT, KILLED_CRASH, UNREACHED, BAD = "survived", "killed-assert", "killed-crash", "unreached", "bad-results"
EQUAL_CLASSES = {(SURVIVED, UNREACHED), (UNREACHED, SURVIVED)}


def read_json(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read())


def write_json(path, obj):
    with open(path, "wb") as handle:
        handle.write((json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode())


def outcome(record):
    """'assert' | 'crash' | 'pass' | 'bad' for one run record {"rc", "timed_out", "results"}."""
    if record["timed_out"] or record["rc"] not in (0, 1) or not record["results"]:
        return "crash"
    lines = []
    for raw in record["results"].split("\n"):
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            return "bad"
        if isinstance(obj, dict) and "summary" in obj and "id" not in obj:
            continue  # the closing line of ctest's results
        if not isinstance(obj, dict) or "status" not in obj or obj["status"] == "skip":
            return "bad"
        lines.append(obj)
    failed = [obj for obj in lines if obj["status"] != "pass"]
    if not lines or (record["rc"] == 0 and failed) or (record["rc"] == 1 and not failed):
        return "bad"
    if any(isinstance(obj.get("reason"), str) and CHECK_FAILURE.match(obj["reason"]) for obj in failed):
        return "assert"
    return "crash" if failed else "pass"


def classify(runs):
    """The class of a mutant from its runs {test: record}: a record is a run, {"killed_by": T} a run v1 skipped after
    a kill, {"unreached": True} a run the schema engine did not make because no execution reaches the mutant."""
    kinds = []
    for record in runs.values():
        if "killed_by" in record:
            kinds.append("assert")
        elif not record.get("unreached"):
            kinds.append(outcome(record))
    if "bad" in kinds:
        return BAD
    if "assert" in kinds:
        return KILLED_ASSERT
    if "crash" in kinds:
        return KILLED_CRASH
    return SURVIVED if kinds else UNREACHED


def reached_by(tests, reach, index):
    return [t for t in tests if index in reach[t]]


def mutant_runs(tests, reach, kills, entry):
    runs = {}
    for test in tests:
        runs[test] = kills[test][entry["id"]] if entry["index"] in reach[test] else {"unreached": True}
    return runs


def saved_runs(tests, runs):
    """Runs of this mutant after the first test that killed it by a failed check (v1's stop at the first kill, T121)."""
    made = [t for t in tests if not runs[t].get("unreached")]
    for position, test in enumerate(made):
        if outcome(runs[test]) == "assert":
            return len(made) - position - 1
    return 0


def load_runs(manifest):
    reach = {t: set(read_json(p)["reached"]) for t, p in manifest["reach"].items()}
    kills = {t: {} for t in manifest["reach"]}
    for test, paths in manifest["kills"].items():
        for path in paths:
            kills[test].update(read_json(path)["records"])
    return reach, kills


def baseline_check(manifest):
    """{test: True when the reach run reproduced the unmutated run of the v1 path}."""
    same = {}
    for test, path in manifest["reach"].items():
        same[test] = read_json(path)["record"] == read_json(manifest["baseline_runs"][test])
    return same


def source_entry(spec, tests, reach, kills):
    listing = read_json(spec["gen"])
    table = read_json(spec["table"]) if spec.get("table") else {"entries": [], "ineligible": {}, "unviable": [], "reasons": {},
                                                               "compiles": 0, "live": 0, "eligible": 0}
    by_id = {e["id"]: e for e in table["entries"]}
    live = set(spec["live"])
    mutants = []
    for m in listing["mutants"]:
        item = {k: m[k] for k in ("id", "file", "function", "line", "operator", "original", "replacement")}
        if m["id"] in by_id:
            entry = by_id[m["id"]]
            runs = mutant_runs(tests, reach, kills, entry)
            item.update(status="eligible", index=entry["index"], runs=runs, **{"class": classify(runs)},
                        saved=saved_runs(tests, runs))
        elif m["id"] in table["ineligible"]:
            item.update(status="ineligible", reason=table["ineligible"][m["id"]])
        elif m["id"] in table["unviable"]:
            item.update(status="schema-unviable", reason="schema-unviable")
        else:
            item.update(status="v1-not-run" if m["id"] not in live else "missing")
        mutants.append(item)
    return {"file": listing["file"], "sha256": listing["sha256"], "table": {k: table[k] for k in (
        "live", "eligible", "reasons", "compiles")}}, mutants


def summary(sources, mutants, tests, checks):
    count = {}
    for m in mutants:
        count[m["status"]] = count.get(m["status"], 0) + 1
    classes, reasons, runs_made, saved = {}, {}, 0, 0
    for m in mutants:
        if m["status"] == "eligible":
            classes[m["class"]] = classes.get(m["class"], 0) + 1
            runs_made += sum(1 for r in m["runs"].values() if not r.get("unreached"))
            saved += m["saved"]
        elif m["status"] in ("ineligible", "schema-unviable"):
            reasons[m["reason"]] = reasons.get(m["reason"], 0) + 1
    return {"mutants": len(mutants), "status": dict(sorted(count.items())), "not_eligible": dict(sorted(reasons.items())),
            "classes": dict(sorted(classes.items())), "kill_runs": runs_made, "kill_runs_after_first_kill": saved,
            "v1_runs_without_stop": count.get("eligible", 0) * len(tests), "baseline_reproduced": checks,
            "schema_compiles": sum(s["table"]["compiles"] for s in sources)}


def cmd_collect(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    manifest = read_json(args.manifest)
    tests = manifest["tests"]
    reach, kills = load_runs(manifest)
    sources, mutants = [], []
    for spec in manifest["sources"]:
        source, found = source_entry(spec, tests, reach, kills)
        sources.append(source)
        mutants.extend(found)
    write_json(args.out, {"schema": 1, "engine": "schema", "label": manifest["label"], "tests": tests,
                          "sources": sources, "mutants": mutants,
                          "summary": summary(sources, mutants, tests, baseline_check(manifest))})


def folded_live(report):
    """{(file, id)} of the mutants v1 ran through their -O0 object: their -O2 object equalled the baseline's or an
    earlier mutant's, and the -O0 object told them apart."""
    base = {s["file"]: s["baseline"]["hash"] for s in report["sources"]}
    seen, found = set(), set()
    for m in report["mutants"]:
        comp = m["compile"]
        if comp["status"] != "ok":
            continue
        key = (m["file"], comp["hash"])
        if (comp["hash"] == base[m["file"]] or key in seen) and "o0" in comp:
            found.add((m["file"], m["id"]))
        seen.add(key)
    return found


def compare(v1, schema):
    """{"agree": n, "disagreements": [...], "unexplained": n, ...} of two reports of one module."""
    by_key = {(m["file"], m["id"]): m for m in v1["mutants"]}
    folded = folded_live(v1)
    agree, found = 0, []
    for m in schema["mutants"]:
        if m["status"] != "eligible":
            continue
        old = by_key.get((m["file"], m["id"]))
        if old is None or "runs" not in old:
            found.append({"file": m["file"], "line": m["line"], "operator": m["operator"], "id": m["id"],
                          "v1": None, "schema": m["class"], "explained": None, "why": "v1 has no run of it"})
            continue
        v1_class = classify(old["runs"])
        if v1_class == m["class"] or (v1_class, m["class"]) in EQUAL_CLASSES:
            agree += 1
            continue
        why = "v1 ran the -O0 object of a mutant the optimiser folded at -O2" if (m["file"], m["id"]) in folded else None
        found.append({"file": m["file"], "line": m["line"], "operator": m["operator"], "id": m["id"],
                      "function": m["function"], "original": m["original"], "replacement": m["replacement"],
                      "v1": v1_class, "schema": m["class"], "explained": why is not None, "why": why,
                      "v1_runs": old["runs"], "schema_runs": m["runs"]})
    return {"compared": agree + len(found), "agree": agree, "disagreements": found,
            "unexplained": sum(1 for d in found if not d["explained"])}


def render(result, label):
    lines = ["%s: %d mutants compared, %d agree, %d disagree (%d unexplained)"
             % (label, result["compared"], result["agree"], len(result["disagreements"]), result["unexplained"])]
    for d in result["disagreements"]:
        lines.append("  %s:%s %s %s: v1 %s, schema %s%s" % (d["file"], d["line"], d["operator"], d["id"], d["v1"], d["schema"],
                                                           " (explained: %s)" % d["why"] if d["explained"] else ""))
    return "\n".join(lines) + "\n"


def cmd_compare(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--v1", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--out")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    schema = read_json(args.schema)
    result = compare(read_json(args.v1), schema)
    result["label"] = schema["label"]
    sys.stdout.write(render(result, schema["label"]))
    if args.out:
        write_json(args.out, result)
    if args.strict and result["unexplained"]:
        sys.exit(1)


COMMANDS = {"collect": cmd_collect, "compare": cmd_compare}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit("usage: schema_compare.py {%s} ..." % "|".join(COMMANDS))
    COMMANDS[sys.argv[1]](sys.argv[2:])
