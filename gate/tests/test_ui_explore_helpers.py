"""Shared fixtures of the ui-explore tests (no tests here): wrappers that start the stub probe in one of its modes,
paths files, and an independent recomputation of the abstraction key and the finding id (written from
docs/ui-explore.md with hashlib and json only, not with the explorer's code)."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from tests.helpers import TempDirTestCase, run_rigor

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STUB = HERE / "data" / "ui_explore" / "stub_probe.py"
# The stub's catalogue: byte for byte the toy catalogue as U05 sealed it (no taps). The selftest's toy catalogue has taps
# since U05a, which the stub only answers in its tap modes (those tests use edited copies).
TOY = HERE / "data" / "ui_explore" / "stub.events.toml"
SELFTEST_TOY = REPO / "selftest" / "ui_product" / "toy.events.toml"
TOY_COARSE = REPO / "selftest" / "ui_product" / "toy_coarse.events.toml"
FIXTURE = REPO / "selftest" / "ui_product" / "fixture.events.toml"
OPEN = "open 1000 7"
TOY_KEY_FIELDS = 13          # every semantic field but `key` (toy.events.toml)
# the stub's semantic records with the notice hidden and empty (the state after open)
STUB_OPEN_SEMANTIC = [
    "title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
    "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
    "notice\tlabel\t\t8\t90\t0\t16\t1\t-\thidden\tbody\tnormal\tnone\tnone"]


def stub(directory, mode, log=None):
    """An executable that runs the stub probe in `mode`; with `log`, the stub logs its commands and pid there."""
    path = Path(directory) / ("probe-" + mode + ("-log" if log else ""))
    env = "UI_STUB_OWNER=%d " % os.getpid() + ("UI_STUB_LOG=%s " % log if log else "")
    path.write_text("#!/bin/sh\n%sexec %s -I %s %s\n" % (env, sys.executable, STUB, mode))
    os.chmod(path, 0o755)
    return path


def paths_file(directory, paths, criteria=(), name="paths.json"):
    path = Path(directory) / name
    path.write_text(json.dumps({"schema": "ui-explore-paths/1", "criteria": list(criteria), "paths": paths}))
    return path


def findings(path):
    """The findings of a findings file, one JSON object per line."""
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def by_check(items, check):
    return [item for item in items if item["check"] == check]


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"


def toy_key(semantic_lines, deadline, env_inputs):
    """The abstraction key of the toy catalogue (all 13 fields, both facts), from docs/ui-explore.md."""
    nodes = [line.split("\t")[:1 + TOY_KEY_FIELDS] for line in semantic_lines]
    projection = {"nodes": nodes, "facts": {"deadline": deadline, "env-inputs": env_inputs}}
    return hashlib.sha256(canonical(projection)).hexdigest()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def alive(pid):
    """True while `pid` runs (a zombie counts as gone)."""
    try:
        with open("/proc/%d/stat" % pid) as stream:
            return stream.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def live_stubs():
    """Pids of live processes started by this test process's stubs (marked UI_STUB_OWNER=<our pid>), the stub's own
    children included (they inherit the mark)."""
    mark = ("UI_STUB_OWNER=%d" % os.getpid()).encode()
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/environ" % name, "rb") as stream:
                marked = mark in stream.read().split(b"\0")
        except OSError:
            continue
        if marked and alive(int(name)):
            found.append(int(name))
    return found


def assert_no_stubs():
    """For tearDownModule: every stub this module started is gone (waits up to 5 s for ones that are exiting)."""
    end = time.monotonic() + 5
    while live_stubs() and time.monotonic() < end:
        time.sleep(0.05)
    left = live_stubs()
    if left:
        raise AssertionError("stub probes still alive after the tests: %s" % left)


def finding_id(check, identity):
    return "ui-explore.%s/%s" % (check, hashlib.sha256(canonical([check, identity])).hexdigest()[:12])


STUB_OPEN_KEY = toy_key(STUB_OPEN_SEMANTIC, "none", [[1, 0, ""]])


class ExploreCase(TempDirTestCase):
    """Runs `rigor ui-explore` against the stub probe; no tests of its own."""

    def explore(self, mode, *args, catalogue=TOY, out="f.json", code=None, log=None):
        probe = stub(self.tmp, mode, log)
        argv = ["ui-explore", "--probe", probe, "--catalogue", catalogue, "--out", self.tmp / out] + list(args)
        outcome = run_rigor(argv)
        if code is not None:
            self.assertExit(outcome, code)
        return outcome, (findings(self.tmp / out) if (self.tmp / out).exists() else None)

    def bfs(self, mode, depth, *extra, **kw):
        return self.explore(mode, "--strategy", "bfs", "--origin-ms", "1000", "--seed", "7", "--depth", str(depth),
                            "--max-states", "100", *extra, **kw)

    def replay(self, mode, paths, *extra, criteria=(), **kw):
        path = paths_file(self.tmp, paths, criteria, name="p%d.json" % time.monotonic_ns())
        return self.explore(mode, "--strategy", "replay", "--paths", path, *extra, **kw)

    def catalogue(self, old, new, base=TOY):
        """An edited copy of a catalogue; `old` must occur in it."""
        text = Path(base).read_text()
        self.assertIn(old, text)
        path = self.tmp / ("cat%d.toml" % time.monotonic_ns())
        path.write_text(text.replace(old, new))
        return path
