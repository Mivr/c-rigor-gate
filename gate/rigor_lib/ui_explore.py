"""`rigor ui-explore` (U05, P004 4.1 to 4.5): drives a probe binary (`c_ui_probe`) along input paths, runs every path
twice, keys states by the owner-declared abstraction key of the event catalogue, applies the judges and writes one JSON
line per finding. Exit 0: no error finding; 1: at least one; 2: the gate could not decide (bad arguments or input files).
Schemas and the judge interface: docs/ui-explore.md.
"""

import os
import re

from rigor_lib import jsonio, ui_contract
from rigor_lib.errors import InternalError
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS
from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib import ui_explore_strategies as strategies
from rigor_lib.ui_explore_judges import CHECKS, PRIVATE, starvation_judge
from rigor_lib.ui_explore_run import Config, check_words

PATHS_SCHEMA = "ui-explore-paths/1"
SUMMARY_SCHEMA = "ui-explore-summary/1"
_UINT = re.compile(r"0|[1-9][0-9]{0,19}")
# strategy -> the arguments it needs; every other strategy argument is refused for it
_STRATEGY_ARGS = {"sweep": ("origin_ms", "seed"), "bfs": ("origin_ms", "seed", "depth", "max_states"),
                  "walk": ("origin_ms", "seed", "walk_seeds", "walk_length", "extra_origins"), "replay": ("paths",)}
_ALL_STRATEGY_ARGS = ("origin_ms", "seed", "depth", "max_states", "walk_seeds", "walk_length", "extra_origins", "paths")
_RANGES = {"origin_ms": (0, 1 << 48), "seed": (0, 2**64 - 1), "depth": (1, 64), "max_states": (1, 1000000),
           "walk_length": (1, 10000), "extra_origins": (0, 16), "deadline_ms": (1, 600000), "starvation_steps": (2, 10000)}


def _uint(text):
    if not _UINT.fullmatch(text):
        raise ValueError(text)
    return int(text)


def _seeds(text):
    parts = text.split(",")
    if any(not _UINT.fullmatch(p) for p in parts):
        raise ValueError(text)
    return [int(p) for p in parts]


def add_parser(subparsers):
    parser = subparsers.add_parser("ui-explore", allow_abbrev=False,
                                   help="drive a UI probe along input paths; findings of the ui-explore gate")
    parser.add_argument("--probe", required=True, help="the probe binary of a c_ui_probe target")
    parser.add_argument("--catalogue", required=True, help="the sealed event catalogue (ui-events/1)")
    parser.add_argument("--strategy", required=True, choices=strategies.STRATEGIES)
    parser.add_argument("--out", required=True, help="findings, one JSON line each")
    parser.add_argument("--contract", help="the UI contract (ui-contract/1) handed to the judges")
    parser.add_argument("--origin-ms", type=_uint)
    parser.add_argument("--seed", type=_uint, help="the seed of every `open`")
    parser.add_argument("--depth", type=_uint, help="bfs: the depth bound")
    parser.add_argument("--max-states", type=_uint, help="bfs: the abstract state bound")
    parser.add_argument("--walk-seeds", type=_seeds, help="walk: comma-separated seeds, one walk each")
    parser.add_argument("--walk-length", type=_uint, help="walk: events per walk")
    parser.add_argument("--extra-origins", type=_uint, help="walk: extra clock origins per walk")
    parser.add_argument("--paths", help="replay: a paths file (ui-explore-paths/1)")
    parser.add_argument("--deadline-ms", type=_uint, default=10000, help="deadline of every probe reply (10000)")
    parser.add_argument("--starvation-steps", type=_uint, default=32,
                        help="consecutive firings within a frame that make timer-starvation (32)")
    parser.add_argument("--evidence", help="a new or empty directory for the evidence files")
    parser.add_argument("--summary", help="write the run summary (ui-explore-summary/1) here")
    parser.set_defaults(handler=handle)


def _check_args(args):
    wanted = _STRATEGY_ARGS[args.strategy]
    for name in _ALL_STRATEGY_ARGS:
        given = getattr(args, name) is not None
        if given != (name in wanted):
            raise InternalError("--%s is %s for --strategy %s" % (name.replace("_", "-"),
                                                                  "required" if name in wanted else "not allowed",
                                                                  args.strategy))
    for name, (lo, hi) in _RANGES.items():
        value = getattr(args, name)
        if value is not None and not lo <= value <= hi:
            raise InternalError("--%s must be in %d..%d" % (name.replace("_", "-"), lo, hi))
    if args.walk_seeds is not None and (len(set(args.walk_seeds)) != len(args.walk_seeds)
                                        or any(s >= 2**64 for s in args.walk_seeds)):
        raise InternalError("--walk-seeds: duplicate or out of range")
    if not os.path.isfile(args.probe) or not os.access(args.probe, os.X_OK):
        raise InternalError("--probe %s is not an executable file" % args.probe)


def load_paths(path, catalogue):
    """(criteria, paths) of a paths file; strict."""
    try:
        document = jsonio.strict_loads(jsonio.read_bytes(path))
    except (OSError, ValueError) as error:
        raise InternalError("paths file %s: %s" % (path, error))
    if type(document) is not dict or sorted(document) != ["criteria", "paths", "schema"]:
        raise InternalError("paths file: wants exactly the keys criteria, paths, schema")
    if document["schema"] != PATHS_SCHEMA:
        raise InternalError("paths file: schema must be %r" % PATHS_SCHEMA)
    criteria = document["criteria"]
    if type(criteria) is not list or len(set(map(str, criteria))) != len(criteria) \
            or any(type(c) is not str or c not in strategies.CRITERIA for c in criteria):
        raise InternalError("paths file: criteria must be distinct names of %s" % ", ".join(strategies.CRITERIA))
    paths = document["paths"]
    if type(paths) is not list or not paths:
        raise InternalError("paths file: paths must be a non-empty list")
    for words in paths:
        check_words(words, catalogue)
    return tuple(c for c in strategies.CRITERIA if c in criteria), paths


def _dedupe(found):
    """One finding per id: the one with the shortest path, then the smallest canonical bytes. Sorted by id."""
    best = {}
    for item in found:
        public = {name: value for name, value in item.items() if name != PRIVATE}
        rank = (len(item["path"]), jsonio.canonical_dumps(public))
        if item["id"] not in best or rank < best[item["id"]][0]:
            best[item["id"]] = (rank, item)
    return [best[ident][1] for ident in sorted(best)]


def _evidence(found, directory, criteria):
    """Per finding `<id hex>/paths.json` (the paths that replay it, with the strategy's criteria) and its private
    evidence files; the finding's `evidence` lists them, relative to `directory`."""
    if os.path.exists(directory) and (not os.path.isdir(directory) or os.listdir(directory)):
        raise InternalError("--evidence %s must be a new or empty directory" % directory)
    os.makedirs(directory, exist_ok=True)
    for item in found:
        name = item["id"].rsplit("/", 1)[1]
        paths = ([item["observed"]["witness_path"]] if item["check"] == "key-too-coarse" else []) + [item["path"]]
        files = {"paths.json": {"schema": PATHS_SCHEMA, "criteria": list(criteria), "paths": paths}}
        files.update(item.get(PRIVATE, {}))
        os.makedirs(os.path.join(directory, name))
        for file_name in sorted(files):
            jsonio.write_atomic(os.path.join(directory, name, file_name), jsonio.canonical_dumps(files[file_name]))
        item["evidence"] = [name + "/" + file_name for file_name in sorted(files)]


def explore(args):
    """(findings, summary) of one ui-explore run."""
    _check_args(args)
    catalogue = catalogue_mod.load(args.catalogue)
    taps = [event.id for event in catalogue.events if event.cls in ("u2", "u3")]
    if taps:
        raise InternalError("catalogue taps %s need a tap command, which ui-probe/1 does not have" % ", ".join(taps))
    contract = ui_contract.load(args.contract) if args.contract else None
    config = Config(os.path.abspath(args.probe), args.deadline_ms / 1000.0, catalogue)
    explorer = strategies.Explorer(config, contract, [starvation_judge(args.starvation_steps)], args.starvation_steps)
    found = []
    if args.strategy == "replay":
        criteria, paths = load_paths(args.paths, catalogue)
        detail = strategies.replay(explorer, paths)
        word = paths[0][0]
    else:
        criteria = strategies.REQUIRED[args.strategy]
        word = strategies.open_word(args.origin_ms, args.seed)
        if args.strategy == "sweep":
            detail = strategies.sweep(explorer, word)
        elif args.strategy == "bfs":
            detail, found = strategies.bfs(explorer, word, args.depth, args.max_states)
        else:
            detail = strategies.walk(explorer, args.origin_ms, args.seed, args.walk_seeds, args.walk_length,
                                     args.extra_origins)
    found = _dedupe(explorer.all_findings() + found + explorer.coverage(criteria, word))
    if args.evidence:
        _evidence(found, args.evidence, criteria)
    for item in found:
        item.pop(PRIVATE, None)
    counts = {check: sum(1 for item in found if item["check"] == check) for check in CHECKS}
    summary = {"schema": SUMMARY_SCHEMA, "strategy": args.strategy, "criteria": list(criteria),
               "catalogue_sha256": catalogue.sha256, "probe_sha256": jsonio.sha256_hex(jsonio.read_bytes(args.probe)),
               "runs": explorer.runs, "abstract_states": len(explorer.reachable),
               "pairs_exercised": len(explorer.exercised), "domain_count": explorer.domain_count,
               "domain_visited": sorted(explorer.domain_visited), "findings": counts, "detail": detail}
    return found, summary


def findings_bytes(found):
    return b"".join(jsonio.canonical_dumps(item) for item in found)


def handle(args):
    found, summary = explore(args)
    jsonio.write_atomic(args.out, findings_bytes(found))
    if args.summary:
        jsonio.write_atomic(args.summary, jsonio.canonical_dumps(summary))
    errors = sum(1 for item in found if item["severity"] == "error")
    print("ui-explore %s: %d runs (each twice), %d abstract states, %d findings (%d errors)"
          % (args.strategy, summary["runs"], summary["abstract_states"], len(found), errors))
    for name in ("states_per_depth", "dropped_states", "domain_count", "domain_visited", "walks", "paths"):
        if name in summary["detail"]:
            print("  %s: %s" % (name, jsonio.canonical_dumps(summary["detail"][name]).decode("ascii").strip()))
    for item in found:
        print("  %s %s" % (item["severity"], item["id"]))
    return EXIT_FAIL if errors else EXIT_PASS
