"""Shared fixtures of the ui-explore tests (no tests here): wrappers that start the stub probe in one of its modes,
paths files, and an independent recomputation of the abstraction key and the finding id (written from
docs/ui-explore.md with hashlib and json only, not with the explorer's code)."""

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STUB = HERE / "data" / "ui_explore" / "stub_probe.py"
TOY = REPO / "selftest" / "ui_product" / "toy.events.toml"
TOY_COARSE = REPO / "selftest" / "ui_product" / "toy_coarse.events.toml"
OPEN = "open 1000 7"
TOY_KEY_FIELDS = 13          # every semantic field but `key` (toy.events.toml)
# the stub's semantic records with the notice hidden and empty (the state after open)
STUB_OPEN_SEMANTIC = [
    "title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
    "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
    "notice\tlabel\t\t8\t90\t0\t16\t1\t-\thidden\tbody\tnormal\tnone\tnone"]


def stub(directory, mode):
    """An executable that runs the stub probe in `mode`."""
    path = Path(directory) / ("probe-" + mode)
    path.write_text("#!/bin/sh\nexec %s -I %s %s\n" % (sys.executable, STUB, mode))
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


def finding_id(check, identity):
    return "ui-explore.%s/%s" % (check, hashlib.sha256(canonical([check, identity])).hexdigest()[:12])


STUB_OPEN_KEY = toy_key(STUB_OPEN_SEMANTIC, "none", [[1, 0, ""]])
