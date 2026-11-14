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

Historical canaries (T2G8, `canaries/hist-<id>/`, docs/canaries.md): a canary with a `pin.toml` is graded on a
clone of the REAL product (a repository named by `--hist-repo NAME=PATH`, or the generated fixture of its
`history.sh`) at the pinned `base`, with `regress.patch` applied as the head commit. `tools/hist_canary.py` first
proves provenance and that the patch still applies (else the canary is refused or `stale`, and the pack fails
closed). The unpatched base is graded too, as the control, and must PASS. Without `regress.patch` the canary is
`pending` (expect.json says so) and is not graded.
"""

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANARIES = os.path.join(ROOT, "canaries")
BASE = os.path.join(ROOT, "canaries", "_base")  # the shared tree and witness, for every pack root
GATE_ORDER = os.path.join(ROOT, "gate", "order.txt")
UNCACHED_DEFAULT = "weak-test"
DEFAULT_JOBS = 8
EXPECT_KEYS = {"description", "bypass", "fail", "not_run", "exit", "pending", "control", "absent", "contains", "verify"}
TIERS = ("merge", "nightly")
VERIFY_NAMESPACE = "c-rigor-gate-verdict"
# Gates no product can make fail: they judge the grader, not the product, so no canary can expect them to
# fail. They are exempt from the coverage check only because a selftest proves each one fails:
#   toolchain: the last step of selftest/grade.sh (a scratch gate clone with one manifest sha256 flipped,
#              graded --uncached: toolchain FAIL toolchain-mismatch, every compiling gate NOT_RUN, exit 1).
GRADER_INTEGRITY_GATES = frozenset({"toolchain"})

# Canaries whose `contains` pins a finding of an L2 module's mutation: that module is deferred at tier `merge`
# (docs/grade.md), so in the tier `merge` pass the pin is not applicable (the rest of the expectation still is).
MERGE_DEFERS_CONTAINS = frozenset({"third-party-link"})

HIST_REPOS = {}   # `--hist-repo NAME=PATH`: the product (and fix) repositories of the historical canaries
OUT_NAMES = {"grade": "verdict.json", "control": "control.json"}
HIST_TOOL = os.path.join(ROOT, "tools", "hist_canary.py")

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "canary", "GIT_AUTHOR_EMAIL": "canary@example.invalid",
    "GIT_COMMITTER_NAME": "canary", "GIT_COMMITTER_EMAIL": "canary@example.invalid",
}


def is_tripwire_root():
    """True when the pack root is a tripwire pack (`--root tripwires`, T086): a green grade is then a blind gate."""
    return os.path.basename(os.path.normpath(CANARIES)) == "tripwires"


def green_message(canary_id, expect):
    """The reason a tripwire that graded PASS is a failure: the gates it expected to fail did not look."""
    return "tripwire %s is green: %s is blind" % (canary_id, ", ".join(sorted(expect.get("fail", {}))))


def load_expect(canary_id):
    with open(os.path.join(CANARIES, canary_id, "expect.json"), encoding="utf-8") as handle:
        expect = json.load(handle)
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise SystemExit("canaries/%s/expect.json: unknown keys %s" % (canary_id, sorted(unknown)))
    if "fail" not in expect and not expect.get("control") and "verify" not in expect:
        raise SystemExit("canaries/%s/expect.json: a canary needs `fail` or `verify`" % canary_id)
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


def hist_tool():
    spec = importlib.util.spec_from_file_location("hist_canary", HIST_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_hist(canary_id):
    return os.path.isfile(os.path.join(CANARIES, canary_id, "pin.toml"))


class HistRefused(Exception):
    """A historical canary that cannot be graded: provenance refused, or the patch is stale (fails the pack closed)."""


def hist_task(canary_id, work, pin):
    """The task contract of a historical canary: its own `task.toml`, else one allowing exactly the pinned paths."""
    own = os.path.join(CANARIES, canary_id, "task.toml")
    if os.path.isfile(own):
        return own
    path = os.path.join(work, "task.toml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('id = "hist"\nallowed = [%s]\n' % ", ".join(json.dumps(p) for p in pin["paths"]))
    return path


def build_hist_repo(canary_id, work):
    """(repo, base, head, control head, pin): a clone of the product at `base`; `head` = base + regress.patch,
    `control head` = base + an empty commit. Raises HistRefused when the canary is refused or stale."""
    hist = hist_tool()
    source = os.path.join(CANARIES, canary_id)
    try:
        ctx = hist.Context(source, HIST_REPOS, os.path.join(work))
        verdict = hist.verify(ctx)
    except hist.HistError as error:
        raise HistRefused("hist_canary: %s" % error)
    if verdict.errors:
        raise HistRefused("refused: " + "; ".join(verdict.errors))
    if verdict.stale:
        raise HistRefused("stale: " + verdict.stale)
    pin = ctx.pin
    repo = os.path.join(work, "repo")
    run(["git", "clone", "-q", "--shared", "--no-checkout", ctx.product, repo], work)
    git(repo, "checkout", "-q", "-B", "control", pin["base"])
    git(repo, "commit", "-q", "--allow-empty", "-m", "control")
    control = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-B", "main", pin["base"])
    git(repo, "apply", os.path.join(source, "regress.patch"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", canary_id)
    return repo, pin["base"], git(repo, "rev-parse", "HEAD"), control, pin


def build_repo(canary_id, work):
    """Create <work>/repo with the base commit and the head commit; returns (repo, base, head)."""
    source = os.path.join(CANARIES, canary_id)
    tree = os.path.join(source, "product")
    if not os.path.isdir(tree):
        tree = os.path.join(BASE, "product")
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
    if "verify" in expect:
        return "PASS, verify --require-tier %s refused" % expect["verify"]["require_tier"]
    fail = {gate: sorted(rules) for gate, rules in expect["fail"].items()}
    return render(fail, sorted(expect.get("not_run", [])))


def witness_dir(canary_id):
    """The witness bundle a canary is graded with: its own `witness/`, else the shared `_base/witness/` (T040)."""
    own = os.path.join(CANARIES, canary_id, "witness")
    if os.path.isdir(own):
        return own
    return os.path.join(BASE, "witness")


def signing_files(work):
    """(private key, allowed_signers file) of a throwaway key, for a canary whose verdict `rigor verify` must judge."""
    key = os.path.join(work, "key")
    run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "canary", "-f", key], work)
    with open(key + ".pub", encoding="utf-8") as handle:
        kind, blob = handle.read().split()[:2]
    signers = os.path.join(work, "allowed_signers")
    with open(signers, "w", encoding="utf-8") as handle:
        handle.write('canary namespaces="%s" %s %s\n' % (VERIFY_NAMESPACE, kind, blob))
    return key, signers


def verify_verdict(verdict, signers, tier, head):
    """(exit code, output) of `rigor verify --require-tier TIER` on a verdict."""
    result = run(["python3", "-I", "-B", os.path.join(ROOT, "gate", "rigor"), "verify", "--verdict", verdict,
                  "--allowed-signers", signers, "--expect-head", head, "--require-tier", tier], ROOT, check=False)
    return result.returncode, result.stdout + result.stderr


def judge_verify(expect, verdict, signers, head):
    """Reasons a `verify` canary failed. The verdict is a signed PASS of the grade tier the canary names; it must be
    accepted with that tier required (so it is refused for its tier alone) and refused with the other one."""
    want = expect["verify"]
    own = [t for t in TIERS if t != want["require_tier"]][0]
    why = []
    code, out = verify_verdict(verdict, signers, own, head)
    if code != 0 or "tier %s" % own not in out:
        why.append("the verdict is not accepted at its own tier %s (exit %d): %s" % (own, code, out.strip()[-300:]))
    code, out = verify_verdict(verdict, signers, want["require_tier"], head)
    if code != 1 or want["refused"] not in out:
        why.append("verify --require-tier %s was not refused as %r (exit %d): %s"
                   % (want["require_tier"], want["refused"], code, out.strip()[-300:]))
    return why


def grade_command(canary_id, repo, base, head, task, work, name, only=()):
    """The `rigor grade` command line. `only` (a historical canary's `gates`) restricts the gates graded."""
    source = os.path.join(CANARIES, canary_id)
    command = ["python3", "-I", "-B", os.path.join(ROOT, "gate", "rigor"), "grade",
               "--product-repo", repo, "--base", base, "--head", head,
               "--task", task,
               "--product", os.path.join(source, "product.toml"),
               "--work", os.path.join(work, name), "--out", os.path.join(work, OUT_NAMES[name])]
    command += ["--witness", witness_dir(canary_id)]
    if only:
        command += ["--only", ",".join(only)]
    return command


def grade_one(canary_id, scratch, uncached, keep=True, tier=None):
    expect = load_expect(canary_id)
    work = os.path.join(scratch, canary_id)
    os.makedirs(work)
    started = time.time()
    outcome = {"id": canary_id, "expected": expected_text(expect), "pending": expect.get("pending"),
               "control": bool(expect.get("control")), "uncached": uncached, "ok": False}
    try:
        control = pin = None
        if is_hist(canary_id) and not os.path.isfile(os.path.join(CANARIES, canary_id, "regress.patch")):
            outcome.update(got="no regress.patch", ok=False,
                           why=["no regress.patch: %s" % ("pending, not graded" if expect.get("pending") else
                                                          "and the canary is not pending")])
            outcome["seconds"] = time.time() - started
            return outcome
        if is_hist(canary_id):
            repo, base, head, control, pin = build_hist_repo(canary_id, work)
        else:
            repo, base, head = build_repo(canary_id, work)
        source = os.path.join(CANARIES, canary_id)
        task = hist_task(canary_id, work, pin) if pin else os.path.join(source, "task.toml")
        only = pin.get("gates", []) if pin else []
        command = grade_command(canary_id, repo, base, head, task, work, "grade", only)
        verdict = os.path.join(work, OUT_NAMES["grade"])
        signers = None
        if "verify" in expect:   # graded at the tier the canary names, signed with a throwaway key
            key, signers = signing_files(work)
            tier = [t for t in TIERS if t != expect["verify"]["require_tier"]][0]
            command += ["--sign-key", key]
        if tier is not None:
            command += ["--tier", tier]
        if uncached:
            command.append("--uncached")
        result = run(command, ROOT, {"TMPDIR": work}, check=False)
        with open(os.path.join(work, "grade.log"), "w", encoding="utf-8") as log:
            log.write(result.stdout + result.stderr)
        outcome.update(judge(expect, result.returncode, os.path.join(work, "grade"), verdict, work, canary_id, tier))
        if signers is not None and os.path.isfile(verdict):
            why = judge_verify(expect, verdict, signers, head)
            outcome["why"] = outcome.get("why", []) + why
            outcome["ok"] = outcome["ok"] and not why
        if control:
            judge_control(outcome, canary_id, repo, base, control, task, work, only, tier)
    except HistRefused as error:   # a refused or stale historical canary fails the pack closed
        outcome.update(got=str(error)[:300], ok=False, stale=str(error).startswith("stale"), why=[str(error)])
    except Exception as error:  # a canary that cannot run is a failed canary, never a skipped one
        outcome.update(got="ERROR %s" % str(error)[:300], ok=False, why=["harness error"])
    outcome["seconds"] = time.time() - started
    if not keep:  # the verdict is judged; a canary's tree (buck-out) is the bulk of the scratch disk
        remove_tree(work)
    return outcome


def judge_control(outcome, canary_id, repo, base, control, task, work, only, tier):
    """Grade the unpatched base (an empty commit on it): it must PASS, else the red verdict proves nothing."""
    command = grade_command(canary_id, repo, base, control, task, work, "control", only)
    if tier is not None:
        command += ["--tier", tier]
    result = run(command, ROOT, {"TMPDIR": work}, check=False)
    with open(os.path.join(work, "control.log"), "w", encoding="utf-8") as log:
        log.write(result.stdout + result.stderr)
    judged = judge({"control": True}, result.returncode, os.path.join(work, "control"),
                   os.path.join(work, OUT_NAMES["control"]), work, canary_id, tier)
    outcome["got"] += "; control %s" % judged["got"]
    outcome["expected"] += "; control PASS"
    outcome["why"] = outcome.get("why", []) + ["control: " + reason for reason in judged["why"]]
    outcome["ok"] = outcome["ok"] and judged["ok"]


def find_daemons(root):
    """[(pid, cwd)] of processes whose working directory is under `root` (ported from selftest/grade.sh)."""
    root = os.path.realpath(root)
    found = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cwd = os.path.realpath(os.readlink("/proc/%s/cwd" % pid))
        except OSError:
            continue
        if cwd == root or cwd.startswith(root + os.sep):
            found.append((int(pid), cwd))
    return sorted(found)


def leak_reasons(leaked):
    return ["a process is still running in the grading tree: %s" % ", ".join("%d (%s)" % item for item in leaked)] if leaked else []


def judge(expect, code, grade_work, verdict, work, canary_id="", tier=None):
    leaked = find_daemons(work)
    if not os.path.isfile(verdict):
        return {"got": "no verdict (exit %d)" % code, "ok": False,
                "why": ["no verdict.json"] + leak_reasons(leaked)}
    overall, failed, not_run, passed = summarize(grade_work, verdict)
    got = render(failed, not_run) + ("" if code == expect.get("exit", 1) or expect.get("control") or "verify" in expect
                                     else " exit %d" % code)
    why = []
    if expect.get("control") or "verify" in expect:
        if overall != "PASS" or code != 0:
            why.append("%s must PASS (overall %s, exit %d)" % ("control" if expect.get("control") else "a verify canary",
                                                                overall, code))
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
        if overall == "PASS" and is_tripwire_root():
            why.insert(0, green_message(canary_id, expect))
    skip_contains = tier == "merge" and canary_id in MERGE_DEFERS_CONTAINS
    for gate, text in sorted({} if skip_contains else expect.get("contains", {}).items()):
        path = os.path.join(grade_work, "results", gate + ".json")
        if not os.path.isfile(path) or text not in open(path, encoding="utf-8").read():
            why.append("results/%s.json lacks %r: it failed for another reason" % (gate, text))
    for name in expect.get("absent", []):
        if os.path.exists(os.path.join(work, name)):
            why.append("%s exists: code that must never run did run" % name)
    why += leak_reasons(leaked)
    return {"got": got, "ok": not why, "why": why}


def print_table(outcomes):
    rows = [("canary", "expected", "got", "ok")]
    for item in outcomes:
        if item["ok"]:
            mark = "ok"
        elif item["pending"]:
            mark = "pending(%s)" % item["pending"]
        elif item.get("stale"):
            mark = "STALE"
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


def uncovered(gates, expects):
    """The gates of `gates` that no live (not pending, not control) expectation of `expects` fails, except
    GRADER_INTEGRITY_GATES."""
    covered = set()
    for expect in expects:
        if not expect.get("pending") and not expect.get("control"):
            covered |= set(expect.get("fail", {}))
    return [gate for gate in gates if gate not in covered and gate not in GRADER_INTEGRITY_GATES]


def check_coverage(ids):
    """Every gate of gate/order.txt must be the expected failing gate of at least one live canary
    (grader-integrity gates excepted)."""
    with open(GATE_ORDER, encoding="utf-8") as handle:
        gates = [line.strip() for line in handle if line.strip()]
    return uncovered(gates, [load_expect(canary_id) for canary_id in ids])


def uncached_for_day(ids, day):
    """The tripwire graded --uncached on day number `day` (days since the epoch, UTC): rotates through the sorted ids."""
    return sorted(ids)[day % len(ids)] if ids else None


def cost(canary_id):
    """Expected relative cost of grading a canary: the more gates it is expected to run, the longer it takes.

    Only the order canaries are started in depends on this, never a verdict.
    """
    expect = load_expect(canary_id)
    if expect.get("control") or "verify" in expect:
        return 99
    skipped = len(expect.get("not_run", []))
    return 10 - skipped


def schedule(selected, uncached_id):
    """(control ids, uncached ids, the rest longest-first). Every selected id appears exactly once."""
    first = [i for i in selected if load_expect(i).get("control")]
    slow = [i for i in selected if i == uncached_id and i not in first]
    rest = sorted((i for i in selected if i not in first and i not in slow), key=lambda i: (-cost(i), i))
    return first, slow, rest


def misses(outcomes, selected):
    """Ids that count against the pack: a canary that is not ok and not pending, or that has no outcome."""
    seen = {o["id"] for o in outcomes}
    absent = [i for i in selected if i not in seen]
    return sorted(absent + [o["id"] for o in outcomes if not o["ok"] and not o["pending"]])


def announce(done):
    print("  %-28s %s (%.0fs)" % (done["id"], "ok" if done["ok"] else "done", done["seconds"]), flush=True)


def grade_all(selected, scratch, uncached_id, jobs, keep, tier=None):
    """Grade every selected canary, each in its own clone, `jobs` at a time (the uncached one counts as one).

    The control runs first and warms the cache the others share; the uncached canary shares nothing with
    the others, so it starts at once on its own thread and runs alongside the control and the rest.
    """
    first, slow, rest = schedule(selected, uncached_id)
    outcomes, lock = [], threading.Lock()

    def one(canary_id):
        done = grade_one(canary_id, scratch, canary_id == uncached_id, keep, tier)
        with lock:
            outcomes.append(done)
        announce(done)

    def uncached_lane():
        for canary_id in slow:
            one(canary_id)

    lane = threading.Thread(target=uncached_lane)
    lane.start()
    for canary_id in first:
        one(canary_id)
    width = max(1, jobs - (1 if slow else 0))
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        for future in [pool.submit(one, i) for i in rest]:
            future.result()
    lane.join()
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help="canaries graded at once, the uncached one included (default %(default)s)")
    parser.add_argument("--only", action="append", default=[], help="run only this canary id")
    parser.add_argument("--uncached", default=None,
                        help="the canary graded with --uncached (default %s; tripwires: rotated by day)" % UNCACHED_DEFAULT)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--tier", choices=TIERS, default=None,
                        help="grade every canary at this tier (T137). `merge` is the second pass: every canary that "
                             "is red on `mutants` at an L3 or L4 module must still be red; the pack's expectations "
                             "are the same (default: the grade's own default, nightly)")
    parser.add_argument("--hist-repo", action="append", default=[], metavar="NAME=PATH",
                        help="a repository a historical canary's pin.toml names (its `product` or `fix_repo`)")
    parser.add_argument("--root", default="canaries", help="the pack directory (default %(default)s; tripwires)")
    args = parser.parse_args()
    global CANARIES
    CANARIES = os.path.abspath(os.path.join(ROOT, args.root))
    for item in args.hist_repo:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            print("--hist-repo wants NAME=PATH, got %r" % item, file=sys.stderr)
            return 2
        HIST_REPOS[name] = os.path.abspath(path)
    if not os.path.isdir(CANARIES):
        print("no such pack directory: %s" % CANARIES, file=sys.stderr)
        return 2

    ids = list_ids()
    unknown = [i for i in args.only if i not in ids]
    if unknown:
        print("unknown canaries: %s" % unknown, file=sys.stderr)
        return 2
    missing = [] if is_tripwire_root() else check_coverage(ids)
    if args.uncached is None:
        args.uncached = uncached_for_day(ids, int(time.time() // 86400)) if is_tripwire_root() else UNCACHED_DEFAULT
    selected = args.only or ids
    if not args.only and missing:
        print("FAIL: no live canary expects these gates to fail: %s" % missing, file=sys.stderr)
        return 1
    scratch = tempfile.mkdtemp(prefix="rigor-canaries.", dir=os.environ.get("TMPDIR", "/var/tmp"))
    started = time.time()
    try:
        outcomes = grade_all(selected, scratch, args.uncached, args.jobs, args.keep, args.tier)
        outcomes.sort(key=lambda item: (not item["control"], item["id"]))
        print()
        print_table(outcomes)
        missed = misses(outcomes, selected)
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
            len(outcomes), len(live), len(pending), len(missed), time.time() - started, args.jobs,
            scratch if args.keep else "(removed)"))
        return 1 if missed else 0
    finally:
        if not args.keep:
            remove_tree(scratch)


if __name__ == "__main__":
    sys.exit(main())
