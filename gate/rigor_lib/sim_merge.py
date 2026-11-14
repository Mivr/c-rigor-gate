"""`c_sim` shard merge (T2G1, P330 §1.3, §1.7): the one verdict of a `c_sim` target from the outputs of its shards.

Runs inside a Buck2 action with `python3 -I -B` (stdlib only, no `rigor_lib` imports) and as a plain function for the
unit tests. Fail closed: a shard that is missing, short, inconsistent with the others or not `pass` makes the verdict
`fail <rule>`; a target that ran no seed at all is `fail sim-no-seeds`. Identity between release and san is compared
by `compare_modes`, from the two `hashes` files (seeds 0 to 9 of every build).

The merged `stats.json` is canonical JSON (sorted keys, no spaces, LF) with `schema` `sim-stats/1`.
"""

import argparse
import json
import sys

SCHEMA = "sim-stats/1"
IDENTITY_SEEDS = 10     # seeds 0..9 of every build are compared between release and san


def _canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"


def parse_hashes(text):
    """{index: (seed, trace, state)} from a `hashes` file (`<index> <seed> <trace> <state>` per line)."""
    rows = {}
    for line in text.splitlines():
        parts = line.split(" ")
        if len(parts) != 4 or not parts[0].isdigit() or int(parts[0]) in rows:
            raise ValueError("bad hashes line: %r" % line)
        rows[int(parts[0])] = tuple(parts[1:])
    return rows


def _first_rule(shards):
    for shard in shards:
        words = shard["verdict"].split()
        if words[:1] != ["pass"]:
            return words[1] if len(words) > 1 else "sim-crash"
    return None


def merge(shards, expect):
    """(verdict line, stats dict, hashes text). `shards`: dicts with `stats` (parsed), `verdict` and `hashes` (text)."""
    rows, failures, worlds = {}, [], set()
    for shard in shards:
        stats = shard["stats"]
        failures.extend(stats["failures"])
        worlds.add((stats["world_sha256"], stats["salt_sha256"], stats["run_ms"]))
        rows.update(parse_hashes(shard["hashes"]))
    ran = sum(shard["stats"]["seeds_run"] for shard in shards)
    asked = sum(shard["stats"]["count"] for shard in shards)
    distinct = len({row[1] for row in rows.values()})
    rule = _first_rule(shards)
    if expect == 0 or asked == 0 or ran == 0:
        rule = "sim-no-seeds"
    elif rule is None and (asked != expect or ran != expect or len(worlds) != 1):
        rule = "sim-no-seeds" if ran < expect else "sim-world-error"
    elif rule is None and ran >= 2 and distinct < ran:
        rule = "sim-vacuous"
    stats = {"count": expect, "distinct_hashes": distinct, "failures": sorted(failures, key=lambda f: f["index"]),
             "schema": SCHEMA, "seeds_run": ran, "shards": len(shards)}
    if len(worlds) == 1:
        world, salt, run_ms = next(iter(worlds))
        stats.update({"run_ms": run_ms, "salt_sha256": salt, "world_sha256": world})
    hashes = "".join("%d %s %s %s\n" % ((index,) + rows[index]) for index in sorted(rows))
    return ("pass\n" if rule is None else "fail %s\n" % rule), stats, hashes


def compare_modes(release, san):
    """Findings (dicts) when the hashes of seeds 0..9 differ between the release and the san build of one target.

    A seed present in one mode and not the other is a finding too (fail closed); `release` and `san` are the text of
    the two `hashes` files."""
    left, right = parse_hashes(release), parse_hashes(san)
    found = []
    for index in range(IDENTITY_SEEDS):
        if index not in left or index not in right:
            found.append({"index": index, "rule": "sim-nondeterministic", "why": "missing in one mode"})
        elif left[index] != right[index]:
            found.append({"index": index, "rule": "sim-nondeterministic", "why": "release and san differ",
                          "release": list(left[index]), "san": list(right[index])})
    return found


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def compare_main(argv):
    """`sim_merge.py compare RELEASE_HASHES SAN_HASHES`: one JSON finding per line; exit 1 if there is any, 2 if unreadable."""
    if len(argv) != 2:
        print("usage: sim_merge.py compare RELEASE_HASHES SAN_HASHES", file=sys.stderr)
        return 2
    try:
        found = compare_modes(_read(argv[0]), _read(argv[1]))
    except (OSError, ValueError) as exc:
        print("sim_merge: %s" % exc, file=sys.stderr)
        return 2
    for item in found:
        print(json.dumps(item, sort_keys=True, separators=(",", ":")))
    return 1 if found else 0


def main(argv):
    if argv[:1] == ["compare"]:
        return compare_main(argv[1:])
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--expect", type=int, required=True)
    parser.add_argument("--out-stats", required=True)
    parser.add_argument("--out-hashes", required=True)
    parser.add_argument("--out-verdict", required=True)
    parser.add_argument("--shard", nargs=3, action="append", metavar=("STATS", "HASHES", "VERDICT"), default=[])
    args = parser.parse_args(argv)
    shards = [{"stats": json.loads(_read(s)), "hashes": _read(h), "verdict": _read(v)} for s, h, v in args.shard]
    verdict, stats, hashes = merge(shards, args.expect)
    for path, text in ((args.out_stats, _canonical(stats)), (args.out_hashes, hashes), (args.out_verdict, verdict)):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
