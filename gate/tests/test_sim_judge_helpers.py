"""Builders for the `rigor sim` tests: facts, a results directory of synthetic runs, policy, spec and salt files."""

import json
from pathlib import Path

from rigor_lib import sim_policy
from tests import test_fuzz_gate_helpers as fh

SIM = "//p:sim"
LIB = "//p:wire"
WORLD = "ab" * 32
SALT = bytes([1, 2, 3])


def facts(directory, lib_deps=(), sims=(SIM,), extra=()):
    """Facts of one library, the c_sim targets `sims` (which depend on the library) and any `extra` (label, kind) pairs."""
    docs = [fh.facts_doc(LIB, "c_library", [fh.unit(defined=["wire_run"])], deps=lib_deps)]
    docs += [fh.facts_doc(label, "c_sim", [fh.unit(defined=["world_init"])], deps=[LIB]) for label in sims]
    docs += [fh.facts_doc(label, kind, [fh.unit()]) for label, kind in extra]
    return fh.write_facts(directory, docs)


def row(index, salt=SALT, world=WORLD, trace=None):
    seed = sim_policy.seed_of(salt, bytes.fromhex(world), index)
    return (seed, "%016x" % (0x1000 + index) if trace is None else trace, "%016x" % (0x2000 + index))


def hashes_text(rows):
    return "".join("%d %s %s %s\n" % ((i,) + rows[i]) for i in sorted(rows))


def stats_doc(count=12, seeds_run=None, failures=(), salt=SALT, world=WORLD, distinct=None, **extra):
    ran = count if seeds_run is None else seeds_run
    doc = {"count": count, "distinct_hashes": ran - len(failures) if distinct is None else distinct,
           "failures": list(failures), "run_ms": 600000, "salt_sha256": sim_policy.jsonio.sha256_hex(salt),
           "schema": "sim-stats/1", "seeds_run": ran, "shards": 2, "world_sha256": world}
    doc.update(extra)
    return doc


def failure(index, rule="sim-crash", salt=SALT, world=WORLD, **fields):
    item = {"detail": 11, "index": index, "rule": rule, "seed": sim_policy.seed_of(salt, bytes.fromhex(world), index)}
    item.update(fields)
    return item


def write_run(directory, ident="t000", label=SIM, count=12, failures=(), salt=SALT, world=WORLD, stats=None,
              verdict=None, san=None, release=None, trace=None, **extra):
    """One target's files. `failures` are failure rows (their seeds have no hashes line); `san` and `release` override
    the generated hashes rows ({index: (seed, trace, state)}); `stats` replaces the stats document."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    failed = {f["index"] for f in failures}
    rows = {i: row(i, salt, world, None if trace is None else trace) for i in range(count) if i not in failed}
    san = rows if san is None else san
    release = dict(rows) if release is None else release
    doc = stats_doc(count, failures=failures, salt=salt, world=world, **extra) if stats is None else stats
    if verdict is None:
        verdict = "pass" if not failures else "fail " + sorted(failures, key=lambda f: f["index"])[0]["rule"]
    (directory / (ident + ".stats.json")).write_text(json.dumps(doc))
    (directory / (ident + ".verdict")).write_text(verdict + "\n")
    (directory / (ident + ".report")).write_text("sim: report\n")
    (directory / (ident + ".hashes")).write_text(hashes_text(san))
    (directory / (ident + ".release.hashes")).write_text(hashes_text(release))
    path = directory / "index.json"
    current = json.loads(path.read_text()) if path.exists() else {}
    current[label] = ident
    path.write_text(json.dumps(current))
    return directory


def write_soak(directory, ident="t000", days=50, failures=(), checked=None, salt=SALT, world=WORLD, seed=None, **override):
    """`<id>.soak.json` of a run (T2G6, schema sim-soak/1); `override` replaces any top-level key."""
    doc = {"checked": {"I11": days, "I12": days, "I13": days} if checked is None else checked, "days": days,
           "failures": [{"assertion": a, "day": d} for a, d in failures], "salt_sha256": sim_policy.jsonio.sha256_hex(salt),
           "schema": "sim-soak/1",
           "seed": sim_policy.seed_of(salt, bytes.fromhex(world), sim_policy.SOAK_INDEX) if seed is None else seed,
           "state_hash": "%016x" % 7, "trace_hash": "%016x" % 9, "uploads": 2 * days, "world_sha256": world}
    doc.update(override)
    (Path(directory) / (ident + ".soak.json")).write_text(json.dumps(doc))


def policy_file(path, text=""):
    Path(path).write_text(text)
    return path


def rules(path):
    return fh.rules(path)


def findings(path, rule):
    return fh.findings(path, rule)
