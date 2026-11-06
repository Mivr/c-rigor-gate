"""The canary pack runner (T018, backlog B6). Python 3 standard library only.

Run through `selftest/canaries.sh`. For every `canaries/<id>/` it builds a throwaway product
repository (history generated here, never committed), grades it with `rigor grade`, and compares
the verdict with `expect.json`. A canary passes only when the verdict has exactly the expected
failing gates, each with exactly the expected error rules, exactly the expected NOT_RUN gates, every
other gate PASS, and the expected exit code. A FAIL for any other reason is a failed canary: a
fixture that fails for the wrong reason hides a disarmed check.

`canaries/<id>/` holds: `product.toml`, `policy.toml`, `expected-tests.json`, `task.toml` (the task
contract), `expect.json`, and the product itself: `product/` (a full tree) or, when absent, the
shared `canaries/_base/product`, plus `edit.sh` (run inside the repo on top of the base commit; its
changes become the head commit) or `history.sh` (full control, see docs/canaries.md).
"""

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANARIES = os.path.join(ROOT, "canaries")
GATE_ORDER = os.path.join(ROOT, "gate", "order.txt")
UNCACHED_DEFAULT = "weak-test"
EXPECT_KEYS = {"description", "bypass", "fail", "not_run", "exit", "pending", "control", "absent", "contains"}

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "canary", "GIT_AUTHOR_EMAIL": "canary@example.invalid",
    "GIT_COMMITTER_NAME": "canary", "GIT_COMMITTER_EMAIL": "canary@example.invalid",
}


def load_expect(canary_id):
    with open(os.path.join(CANARIES, canary_id, "expect.json"), encoding="utf-8") as handle:
        expect = json.load(handle)
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise SystemExit("canaries/%s/expect.json: unknown keys %s" % (canary_id, sorted(unknown)))
    if "fail" not in expect and not expect.get("control"):
        raise SystemExit("canaries/%s/expect.json: a canary needs `fail`" % canary_id)
    return expect


def list_ids():
    ids = []
    for name in sorted(os.listdir(CANARIES)):
        if os.path.isfile(os.path.join(CANARIES, name, "expect.json")):
            ids.append(name)
    return ids


def run(args, cwd, env_extra=None, check=True):
    env = dict(os.environ)
    env.update(GIT_ENV)
    env.update(env_extra or {})
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError("%s failed (%d): %s" % (args, result.returncode, result.stderr[-2000:]))
    return result


def git(repo, *args):
    return run(["git", *args], repo).stdout.strip()


def build_repo(canary_id, work):
    """Create <work>/repo with the base commit and the head commit; returns (repo, base, head)."""
    source = os.path.join(CANARIES, canary_id)
    tree = os.path.join(source, "product")
    if not os.path.isdir(tree):
        tree = os.path.join(CANARIES, "_base", "product")
    repo = os.path.join(work, "repo")
    shutil.copytree(tree, repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    env = {"CANARY_DIR": source, "CANARY_SCRATCH": work, "BASE": base}
    history = os.path.join(source, "history.sh")
    if os.path.isfile(history):
        out = run(["bash", history], repo, env).stdout.split()
        if len(out) < 2:
            raise RuntimeError("history.sh must print `<base> <head>` as its last line")
        return repo, out[-2], out[-1]
    edit = os.path.join(source, "edit.sh")
    if os.path.isfile(edit):
        run(["bash", edit], repo, env)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", canary_id)
    return repo, base, git(repo, "rev-parse", "HEAD")


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def summarize(work, verdict_path):
    """(overall, {gate: sorted error rules} for FAIL gates, [NOT_RUN gates], [PASS gates])."""
    core = read_json(verdict_path)["core"]
    failed, not_run, passed = {}, [], []
    for gate in core["gates"]:
        if gate["status"] == "FAIL":
            rules = set()
            path = os.path.join(work, "results", gate["id"] + ".json")
            if os.path.isfile(path):
                rules = {f["rule"] for f in read_json(path)["findings"] if f.get("severity") == "error"}
            failed[gate["id"]] = sorted(rules)
        elif gate["status"] == "NOT_RUN":
            not_run.append(gate["id"])
        else:
            passed.append(gate["id"])
    return core["overall"], failed, not_run, passed


def render(failed, not_run):
    if not failed:
        return "PASS"
    text = ",".join("%s:%s" % (gate, "+".join(rules) or "-") for gate, rules in sorted(failed.items()))
    return text + (" (NOT_RUN %s)" % ",".join(not_run) if not_run else "")


def expected_text(expect):
    if expect.get("control"):
        return "PASS"
    fail = {gate: sorted(rules) for gate, rules in expect["fail"].items()}
    return render(fail, sorted(expect.get("not_run", [])))


def grade_one(canary_id, scratch, uncached):
    expect = load_expect(canary_id)
    work = os.path.join(scratch, canary_id)
    os.makedirs(work)
    started = time.time()
    outcome = {"id": canary_id, "expected": expected_text(expect), "pending": expect.get("pending"),
               "control": bool(expect.get("control")), "uncached": uncached, "ok": False}
    try:
        repo, base, head = build_repo(canary_id, work)
        source = os.path.join(CANARIES, canary_id)
        verdict = os.path.join(work, "verdict.json")
        command = ["python3", "-I", "-B", os.path.join(ROOT, "gate", "rigor"), "grade",
                   "--product-repo", repo, "--base", base, "--head", head,
                   "--task", os.path.join(source, "task.toml"),
                   "--product", os.path.join(source, "product.toml"),
                   "--work", os.path.join(work, "grade"), "--out", verdict]
        if uncached:
            command.append("--uncached")
        result = run(command, ROOT, {"TMPDIR": work}, check=False)
        with open(os.path.join(work, "grade.log"), "w", encoding="utf-8") as log:
            log.write(result.stdout + result.stderr)
        outcome.update(judge(expect, result.returncode, os.path.join(work, "grade"), verdict, work))
    except Exception as error:  # a canary that cannot run is a failed canary, never a skipped one
        outcome.update(got="ERROR %s" % str(error)[:300], ok=False, why=["harness error"])
    outcome["seconds"] = time.time() - started
    return outcome


def judge(expect, code, grade_work, verdict, work):
    if not os.path.isfile(verdict):
        return {"got": "no verdict (exit %d)" % code, "ok": False, "why": ["no verdict.json"]}
    overall, failed, not_run, passed = summarize(grade_work, verdict)
    got = render(failed, not_run) + ("" if code == expect.get("exit", 1) or expect.get("control")
                                     else " exit %d" % code)
    why = []
    if expect.get("control"):
        if overall != "PASS" or code != 0:
            why.append("control must PASS (overall %s, exit %d)" % (overall, code))
    else:
        want = {gate: sorted(rules) for gate, rules in expect["fail"].items()}
        if failed != want:
            why.append("failing gates/rules differ")
        if sorted(not_run) != sorted(expect.get("not_run", [])):
            why.append("NOT_RUN gates differ: got %s" % sorted(not_run))
        if code != expect.get("exit", 1):
            why.append("exit %d, expected %d" % (code, expect.get("exit", 1)))
        if overall != "FAIL":
            why.append("overall %s" % overall)
    for gate, text in sorted(expect.get("contains", {}).items()):
        path = os.path.join(grade_work, "results", gate + ".json")
        if not os.path.isfile(path) or text not in open(path, encoding="utf-8").read():
            why.append("results/%s.json lacks %r: it failed for another reason" % (gate, text))
    for name in expect.get("absent", []):
        if os.path.exists(os.path.join(work, name)):
            why.append("%s exists: code that must never run did run" % name)
    return {"got": got, "ok": not why, "why": why}


def print_table(outcomes):
    rows = [("canary", "expected", "got", "ok")]
    for item in outcomes:
        if item["ok"]:
            mark = "ok"
        elif item["pending"]:
            mark = "pending(%s)" % item["pending"]
        else:
            mark = "MISS"
        rows.append((item["id"] + (" [uncached]" if item["uncached"] else ""),
                     item["expected"], item["got"], mark))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(3)) + "  " + row[3])


def remove_tree(path):
    def writable(function, target, _error):
        os.chmod(os.path.dirname(target), 0o700)
        os.chmod(target, 0o700)
        function(target)
    shutil.rmtree(path, onerror=writable)


def check_coverage(ids):
    """Every gate of gate/order.txt must be the expected failing gate of at least one live canary."""
    with open(GATE_ORDER, encoding="utf-8") as handle:
        gates = [line.strip() for line in handle if line.strip()]
    covered = set()
    for canary_id in ids:
        expect = load_expect(canary_id)
        if not expect.get("pending") and not expect.get("control"):
            covered |= set(expect["fail"])
    return [gate for gate in gates if gate not in covered]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--only", action="append", default=[], help="run only this canary id")
    parser.add_argument("--uncached", default=UNCACHED_DEFAULT, help="the canary graded with --uncached")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    ids = list_ids()
    unknown = [i for i in args.only if i not in ids]
    if unknown:
        print("unknown canaries: %s" % unknown, file=sys.stderr)
        return 2
    missing = check_coverage(ids)
    selected = args.only or ids
    if not args.only and missing:
        print("FAIL: no live canary expects these gates to fail: %s" % missing, file=sys.stderr)
        return 1
    scratch = tempfile.mkdtemp(prefix="rigor-canaries.", dir=os.environ.get("TMPDIR", "/var/tmp"))
    started = time.time()
    outcomes = []
    try:
        # The control goes first and alone: it fills the cache every canary shares.
        first = [i for i in selected if load_expect(i).get("control")]
        rest = [i for i in selected if i not in first]
        for canary_id in first:
            outcomes.append(grade_one(canary_id, scratch, False))
            print("  control %s: %s (%.0fs)" % (canary_id, "ok" if outcomes[-1]["ok"] else "MISS",
                                               outcomes[-1]["seconds"]), flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = [pool.submit(grade_one, i, scratch, i == args.uncached) for i in rest]
            for future in futures:
                outcomes.append(future.result())
                done = outcomes[-1]
                print("  %-28s %s (%.0fs)" % (done["id"], "ok" if done["ok"] else "done", done["seconds"]),
                      flush=True)
        outcomes.sort(key=lambda item: (not item["control"], item["id"]))
        print()
        print_table(outcomes)
        misses = [o for o in outcomes if not o["ok"] and not o["pending"]]
        pending = [o for o in outcomes if o["pending"]]
        print()
        for item in outcomes:
            if not item["ok"]:
                print("%s %s: %s" % ("PENDING" if item["pending"] else "MISS", item["id"],
                                     "; ".join(item.get("why", []))))
        if pending:
            print("pending (run, verdict printed, do not fail the pack): " +
                  ", ".join("%s (%s)" % (o["id"], o["pending"]) for o in pending))
        live = [o for o in outcomes if not o["pending"]]
        print("SUMMARY: %d canaries (%d live, %d pending), %d live misses, wall %.0fs, jobs %d, scratch %s" % (
            len(outcomes), len(live), len(pending), len(misses), time.time() - started, args.jobs,
            scratch if args.keep else "(removed)"))
        return 1 if misses else 0
    finally:
        if not args.keep:
            remove_tree(scratch)


if __name__ == "__main__":
    sys.exit(main())
