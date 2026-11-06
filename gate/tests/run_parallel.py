"""Run the gate unit tests with one subprocess per test module.

Usage: python3 -I -B gate/tests/run_parallel.py [--jobs N] [--timeout S]

Discovers exactly what `python3 -I -B -m unittest discover -s gate/tests -t gate` would, runs every
module in its own interpreter with its own TMPDIR, and fails if anything fails, hangs, cannot be
imported, or if the number of tests run differs from the number discovered.
Exit codes: 0 all passed, 1 test failure or count mismatch, 2 runner error.
"""

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = GATE_DIR.parent
DURATIONS = "gate-test-durations.json"
RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
# unittest with -I does not put the top directory on sys.path, so the child does it.
CHILD = (
    "import sys, unittest; sys.path.insert(0, sys.argv[1]); "
    "unittest.main(module=None, argv=['unittest', sys.argv[2]])"
)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def discover():
    """Return ({module: count}, [modules that failed to import])."""
    sys.path.insert(0, str(GATE_DIR))
    suite = unittest.defaultTestLoader.discover(
        str(GATE_DIR / "tests"), pattern="test*.py", top_level_dir=str(GATE_DIR))
    counts, broken = {}, []
    for test in flatten(suite):
        name = type(test).__module__
        if type(test).__name__ == "_FailedTest":
            name = test.id().rsplit("._FailedTest.", 1)[-1]
            broken.append(name)
        counts[name] = counts.get(name, 0) + 1
    return counts, broken


def load_durations(tmp):
    try:
        data = json.loads((Path(tmp) / DURATIONS).read_text())
        return {k: float(v) for k, v in data.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def module_size(module):
    path = GATE_DIR / (module.replace(".", "/") + ".py")
    try:
        return path.stat().st_size
    except OSError:
        return 0


def run_module(module, tmp, timeout):
    scratch = tempfile.mkdtemp(prefix=module + ".", dir=tmp)
    env = dict(os.environ, TMPDIR=scratch)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-c", CHILD, str(GATE_DIR), module],
            cwd=os.getcwd(), env=env, capture_output=True, text=True,
            errors="replace", timeout=timeout)
        out, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"") + (exc.stderr or b"")
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        out, code = partial + f"\nrun_parallel: killed after {timeout} s\n", None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    found = RAN.search(out)
    return module, code, int(found.group(1)) if found else None, time.monotonic() - start, out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", type=int, default=max(1, min(16, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args(argv)
    if args.jobs < 1 or args.timeout <= 0:
        print("run_parallel: --jobs and --timeout must be positive", file=sys.stderr)
        return 2
    tmp = os.environ.get("TMPDIR") or "/var/tmp"
    try:
        counts, broken = discover()
        os.makedirs(tmp, exist_ok=True)
    except Exception as exc:  # discovery itself broke
        print(f"run_parallel: discovery failed: {exc!r}", file=sys.stderr)
        return 2
    if not counts:
        print("run_parallel: no tests discovered", file=sys.stderr)
        return 2
    durations = load_durations(tmp)
    order = sorted(counts, key=lambda m: (-durations.get(m, 0), -module_size(m), m))
    started, failed, ran, results = time.monotonic(), [], 0, {}
    problems = [f"module could not be imported: {name}" for name in broken]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for module, code, n, secs, out in pool.map(
                lambda m: run_module(m, tmp, args.timeout), order):
            good = code == 0 and n is not None and n == counts[module]
            if n is None:
                problems.append(f"{module}: produced no test count")
            elif n != counts[module]:
                problems.append(f"{module}: ran {n} tests, discovered {counts[module]}")
            ran += n or 0
            results[module] = secs
            print(f"{'ok  ' if good else 'FAIL'} {module} {n if n is not None else '?'} {secs:.1f}",
                  flush=True)
            if not good:
                failed.append((module, out))
    total = time.monotonic() - started
    for module, out in failed:
        print(f"\n===== {module} =====\n{out}")
    expected = sum(counts.values())
    if ran != expected:
        problems.append(f"ran {ran} tests, discovered {expected}")
    try:
        (Path(tmp) / DURATIONS).write_text(json.dumps(results))
    except OSError:
        pass  # scheduling hint only
    print(f"\nRan {ran} tests in {total:.3f}s")
    for line in problems:
        print(f"run_parallel: {line}")
    if failed or problems:
        print("FAILED")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
