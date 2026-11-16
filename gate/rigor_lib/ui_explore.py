"""`rigor ui-explore` (U05, P004 4.1 to 4.5): drives a probe binary (`c_ui_probe`) along input paths, runs every path
twice, keys states by the owner-declared abstraction key of the event catalogue, applies the judges and writes one JSON
line per finding. Exit 0: no error finding; 1: at least one; 2: the gate could not decide (bad arguments or input files,
a probe that cannot be executed). Schemas and the judge interface: docs/ui-explore.md.
"""

import datetime
import os
import re
import signal

from rigor_lib import jsonio, ui_contract
from rigor_lib.errors import InternalError
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS
from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib import ui_explore_strategies as strategies
from rigor_lib.ui_explore_coverage import CRITERIA, not_evaluated
from rigor_lib.ui_explore_judges import CHECKS, PRIVATE, SCENE_CHECKS, make
from rigor_lib.ui_explore_scene import Scene
from rigor_lib.ui_explore_probe import CAPABILITIES, TAP_CAPS, Budget, BudgetSpent, ProbeError, Session, kill_all
from rigor_lib.ui_explore_judges import probe_error_judge
from rigor_lib.ui_explore_run import Config, Run, Step, check_words
from rigor_lib.ui_judge_findings import JudgeSet

PATHS_SCHEMA = "ui-explore-paths/1"
SUMMARY_SCHEMA = "ui-explore-summary/1"
_UINT = re.compile(r"0|[1-9][0-9]{0,19}")
_STRATEGY_ARGS = {"sweep": ("origin_ms", "seed"), "bfs": ("origin_ms", "seed", "depth", "max_states"),
                  "walk": ("origin_ms", "seed", "walk_seeds", "walk_length", "extra_origins"), "replay": ("paths",)}
_ALL_STRATEGY_ARGS = ("origin_ms", "seed", "depth", "max_states", "walk_seeds", "walk_length", "extra_origins", "paths")
_RANGES = {"origin_ms": (0, 1 << 48), "seed": (0, 2**64 - 1), "depth": (1, 64), "max_states": (1, 1000000),
           "walk_length": (1, 10000), "extra_origins": (0, 16), "deadline_ms": (1, 600000),
           "budget_s": (1, 86400)}
_EVIDENCE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.json")
_IMAGE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.png")      # an evidence image: PNG bytes (ui_explore_png)


def _uint(text):
    if not _UINT.fullmatch(text):
        raise ValueError(text)
    return int(text)


def _date(text):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise ValueError(text)
    return datetime.date.fromisoformat(text)


def _list(pattern):
    def parse(text):
        parts = text.split(",")
        if any(not re.fullmatch(pattern, p) for p in parts):
            raise ValueError(text)
        return parts
    return parse


def add_parser(subparsers):
    parser = subparsers.add_parser("ui-explore", allow_abbrev=False,
                                   help="drive a UI probe along input paths; findings of the ui-explore gate")
    parser.add_argument("--probe", required=True, help="the probe binary of a c_ui_probe target")
    parser.add_argument("--catalogue", required=True, help="the sealed event catalogue (ui-events/1)")
    parser.add_argument("--strategy", required=True, choices=strategies.STRATEGIES)
    parser.add_argument("--out", required=True, help="findings, one JSON line each")
    parser.add_argument("--contract", help="the UI contract (ui-contract/1) handed to the judges")
    parser.add_argument("--judges", type=_list(r"[a-z][a-z-]{0,31}"),
                        help="judges to run besides the explorer's own: ui-scene,ui-fit,ui-render (they need "
                             "--contract and --today; ui-render also a probe with ink; ui-scene reads identity when "
                             "the probe announces it)")
    parser.add_argument("--today", type=_date, help="the date (YYYY-MM-DD) the contract's exceptions expire against")
    parser.add_argument("--origin-ms", type=_uint)
    parser.add_argument("--seed", type=_uint, help="the seed of every `open`")
    parser.add_argument("--depth", type=_uint, help="bfs: the depth bound")
    parser.add_argument("--max-states", type=_uint, help="bfs: the abstract state bound")
    parser.add_argument("--walk-seeds", type=_list(r"0|[1-9][0-9]{0,19}"), help="walk: comma-separated seeds")
    parser.add_argument("--walk-length", type=_uint, help="walk: events per walk")
    parser.add_argument("--extra-origins", type=_uint, help="walk: extra clock origins per walk")
    parser.add_argument("--paths", help="replay: a paths file (ui-explore-paths/1)")
    parser.add_argument("--boot-seeds", choices=("catalogue",),
                        help="sweep, bfs, walk: run once per seed of the catalogue's [boot] instead of --seed (U05e)")
    parser.add_argument("--prefix", help="bfs: start after the words of the catalogue's [[prefix]] row of this name")
    parser.add_argument("--deadline-ms", type=_uint, default=10000, help="deadline of every probe reply (10000)")
    parser.add_argument("--budget-s", type=_uint, default=1800, help="wall-clock budget of the whole run (1800)")
    parser.add_argument("--require", type=_list(r"C[0-9]{1,2}"), help="criteria that must be evaluated, e.g. C1,C8")
    parser.add_argument("--evidence", help="a new or empty directory for the evidence files")
    parser.add_argument("--summary", help="write the run summary (ui-explore-summary/1) here")
    parser.set_defaults(handler=handle)


def _check_args(args):
    wanted = _STRATEGY_ARGS[args.strategy]
    if args.boot_seeds is not None:                     # U05e: the catalogue's seeds replace --seed
        if args.strategy == "replay":
            raise InternalError("--boot-seeds is not allowed for --strategy replay")
        wanted = tuple(name for name in wanted if name != "seed")
        if args.seed is not None:
            raise InternalError("--seed is not allowed with --boot-seeds")
    if args.prefix is not None and args.strategy != "bfs":
        raise InternalError("--prefix is only for --strategy bfs")
    for name in _ALL_STRATEGY_ARGS:
        if (getattr(args, name) is not None) != (name in wanted):
            raise InternalError("--%s is %s for --strategy %s" % (
                name.replace("_", "-"), "required" if name in wanted else "not allowed", args.strategy))
    for name, (lo, hi) in _RANGES.items():
        value = getattr(args, name)
        if value is not None and not lo <= value <= hi:
            raise InternalError("--%s must be in %d..%d" % (name.replace("_", "-"), lo, hi))
    if args.walk_seeds is not None:
        args.walk_seeds = [int(s) for s in args.walk_seeds]
        if len(set(args.walk_seeds)) != len(args.walk_seeds) or any(s >= 2**64 for s in args.walk_seeds):
            raise InternalError("--walk-seeds: duplicate or out of range")
    if args.require is not None and (len(set(args.require)) != len(args.require)
                                     or any(c not in CRITERIA for c in args.require)):
        raise InternalError("--require: distinct criteria of %s" % ", ".join(sorted(CRITERIA)))
    if not os.path.isfile(args.probe) or not os.access(args.probe, os.X_OK):
        raise InternalError("--probe %s is not an executable file" % args.probe)


def load_paths(path, catalogue, caps):
    """(criteria, paths) of a paths file; strict."""
    try:
        document = jsonio.strict_loads(jsonio.read_bytes(path))
    except (OSError, ValueError) as error:
        raise InternalError("paths file %s: %s" % (path, error))
    except RecursionError:
        raise InternalError("paths file %s: nested too deeply" % path)
    if type(document) is not dict or sorted(document) != ["criteria", "paths", "schema"]:
        raise InternalError("paths file: wants exactly the keys criteria, paths, schema")
    if document["schema"] != PATHS_SCHEMA:
        raise InternalError("paths file: schema must be %r" % PATHS_SCHEMA)
    criteria = document["criteria"]
    if type(criteria) is not list or any(type(c) is not str or c not in CRITERIA for c in criteria) \
            or len(set(criteria)) != len(criteria):
        raise InternalError("paths file: criteria must be distinct names of %s" % ", ".join(sorted(CRITERIA)))
    paths = document["paths"]
    if type(paths) is not list or not paths:
        raise InternalError("paths file: paths must be a non-empty list")
    for words in paths:
        check_words(words, catalogue, caps)
    return tuple(c for c in sorted(CRITERIA) if c in criteria), paths


def _dedupe(found):
    """One finding per id: the shortest path, then the smallest canonical bytes. Sorted by id."""
    best = {}
    for item in found:
        public = {name: value for name, value in item.items() if name != PRIVATE}
        rank = (len(item["path"]), jsonio.canonical_dumps(public))
        if item["id"] not in best or rank < best[item["id"]][0]:
            best[item["id"]] = (rank, item)
    return [best[ident][1] for ident in sorted(best)]


def _evidence(found, directory, criteria):
    if os.path.exists(directory) and (not os.path.isdir(directory) or os.listdir(directory)):
        raise InternalError("--evidence %s must be a new or empty directory" % directory)
    os.makedirs(directory, exist_ok=True)
    for item in found:
        name = item["id"].rsplit("/", 1)[1]
        paths = ([item["observed"]["witness_path"]] if item["check"] == "key-too-coarse" else []) + [item["path"]]
        files = {"paths.json": {"schema": PATHS_SCHEMA, "criteria": list(criteria), "paths": paths}}
        for file_name, data in item.get(PRIVATE, {}).items():
            image = _IMAGE_NAME.fullmatch(file_name) is not None and isinstance(data, bytes)
            document = _EVIDENCE_NAME.fullmatch(file_name) is not None and file_name != "paths.json" \
                and not isinstance(data, bytes)
            if not (image or document):
                raise InternalError("a judge's evidence file name %r is not allowed" % (file_name,))
            files[file_name] = data
        os.makedirs(os.path.join(directory, name))
        for file_name in sorted(files):
            data = files[file_name]
            jsonio.write_atomic(os.path.join(directory, name, file_name),
                                data if isinstance(data, bytes) else jsonio.canonical_dumps(data))
        item["evidence"] = [name + "/" + file_name for file_name in sorted(files)]


def _greet(config, word):
    """The first launch: (capabilities, None), or (None, the finding of a probe that could not greet)."""
    try:
        session = Session([config.probe], config.deadline_s, config.budget)
    except ProbeError as error:
        run = Run([word], [Step(0, word, error=error)], (0, error))
        return None, probe_error_judge(config.catalogue.key)(run, run, None)[0]
    caps = session.caps
    session.close()
    return caps, None


def _load(args):
    catalogue = catalogue_mod.load(args.catalogue)
    try:
        contract = ui_contract.load(args.contract) if args.contract else None
    except RecursionError:
        raise InternalError("UI contract %s: nested too deeply" % args.contract)
    return catalogue, contract


def _strategy(args, explorer, paths, seed=None, prefix=()):
    if args.strategy == "replay":
        return strategies.replay(explorer, paths), []
    seed = args.seed if seed is None else seed
    word = strategies.open_word(args.origin_ms, seed)
    if args.strategy == "sweep":
        return strategies.sweep(explorer, word), []
    if args.strategy == "bfs":
        return strategies.bfs(explorer, word, args.depth, args.max_states, prefix)
    return strategies.walk(explorer, args.origin_ms, seed, args.walk_seeds, args.walk_length,
                           args.extra_origins), []


def _seeds(args, explorer, paths, catalogue, prefix):
    """The strategy once per boot seed of the catalogue (U05e, --boot-seeds catalogue), one Explorer for all: the
    findings merge by id. The detail lists each seed's; a bfs the budget cut ends the loop."""
    if args.boot_seeds is None:
        return _strategy(args, explorer, paths, prefix=prefix)
    details, extra = [], []
    for seed in catalogue.boot_seeds:
        detail, found = _strategy(args, explorer, paths, seed, prefix)
        details.append(dict(detail, seed=seed))
        extra.extend(found)
        if detail.get("budget_cut"):
            return {"boot_seeds": details, "budget_cut": True}, extra
    return {"boot_seeds": details}, extra


def _prefix(args, catalogue, caps):
    """The words of `--prefix NAME` (a `[[prefix]]` row), checked as path words, or ()."""
    if args.prefix is None:
        return ()
    words = catalogue.prefix(args.prefix)
    if words is None:
        raise InternalError("--prefix %s: the catalogue has no [[prefix]] row of that name" % args.prefix)
    if any(word.startswith("open ") for word in words):
        raise InternalError("--prefix %s: a prefix cannot open a session" % args.prefix)
    check_words(["open 0 0"] + list(words), catalogue, caps)
    return words


def _budget_finding(args, catalogue, word, runs):
    return make("ui-explore-timeout", ["budget", catalogue.sha256, args.strategy], None, [word],
                {"kind": "budget", "budget_s": args.budget_s, "runs": runs})


def _start(args, catalogue):
    """(paths or None, the criteria, the first open word) of a run; the first boot seed's with --boot-seeds."""
    paths = load_paths(args.paths, catalogue, CAPABILITIES) if args.strategy == "replay" else None
    if args.boot_seeds is not None and not catalogue.boot_seeds:
        raise InternalError("--boot-seeds catalogue: the catalogue has no [boot] seeds")
    seed = catalogue.boot_seeds[0] if args.boot_seeds is not None else args.seed
    criteria, word = (paths[0], paths[1][0][0]) if paths else \
        (strategies.REQUIRED[args.strategy], strategies.open_word(args.origin_ms, seed))
    return (paths[1] if paths else None), criteria, word


def _launch(args, config, contract, judges, paths, word):
    """The first launch and what it decides: (config with the capabilities and the scene, caps or None, the greeting
    finding or None, the prefix words)."""
    catalogue = config.catalogue
    try:
        caps, greeting = _greet(config, word)
    except BudgetSpent:
        caps, greeting = None, _budget_finding(args, catalogue, word, 0)
    prefix = ()
    if caps is not None:
        _check_requires(catalogue, caps)
        _check_taps(catalogue, caps, paths)
        prefix = _prefix(args, catalogue, caps)
        strategies.check_cost(catalogue, args, paths, caps, prefix)
        config = _config(config.probe, config.deadline_s, catalogue, config.budget, caps, _identity(judges, caps),
                         _scene(catalogue, contract))
    return config, caps, greeting, prefix


def explore(args):
    """(findings, summary) of one ui-explore run."""
    _check_args(args)
    catalogue, contract = _load(args)
    if args.today is not None and args.judges is None:
        raise InternalError("--today is only for --judges")
    judges = JudgeSet(args.judges, contract, catalogue.key, args.today) if args.judges is not None else None
    config = _config(args.probe, args.deadline_ms / 1000.0, catalogue, Budget(args.budget_s))
    paths, criteria, word = _start(args, catalogue)
    config, caps, greeting, prefix = _launch(args, config, contract, judges, paths, word)
    _check_judges(judges, caps)
    explorer = strategies.Explorer(config, contract, word, caps or (),
                                   step_judges=[judges.step_judge] if judges else (),
                                   ink=judges is not None and judges.needs_ink)
    evaluated, extra, spent = [], [], greeting is not None
    detail = {}
    if greeting is not None:
        extra = [greeting]
    else:
        try:
            detail, extra = _seeds(args, explorer, paths, catalogue, prefix)
        except BudgetSpent:
            spent, extra = True, [_budget_finding(args, catalogue, word, explorer.runs)]
        spent = spent or bool(detail.get("budget_cut"))   # a bfs the budget cut is never reported as complete
    if not spent:
        for criterion in criteria:
            done, found = CRITERIA[criterion](explorer.exploration, contract)
            extra.extend(found)
            if done:
                evaluated.append(criterion)
        if judges is not None:
            extra.extend(judges.finish(word, explorer.ink.capped if explorer.ink else ()))
    extra.extend(not_evaluated(c, explorer.exploration) for c in (args.require or ()) if c not in evaluated)
    if explorer.taps == "indev" and "pointer" not in (caps or ()):
        extra.append(make("taps-injected", ["taps-injected", catalogue.sha256], None, [word],
                          {"taps": "indev", "pointer": False}))
    found = _dedupe(explorer.all_findings() + extra)
    if args.evidence:
        _evidence(found, args.evidence, criteria)
    for item in found:
        item.pop(PRIVATE, None)
    return found, _summary(args, catalogue, explorer, criteria, evaluated, spent, detail, found)


def _scene(catalogue, contract):
    """The scene taps and the layer policy of a run (U05e), or None for a run with neither a `taps` table nor a
    contract, which then runs exactly as before."""
    if catalogue.taps is None and contract is None:
        return None
    scene = Scene(catalogue, contract)
    if scene.scoped and scene.grid is None:
        raise InternalError("taps scope \"scene\" needs the catalogue's grid_pct or a --contract with probe_grid_pct")
    return scene


def _config(probe, deadline_s, catalogue, budget, caps=None, identity=False, scene=None):
    """The run's Config, by keyword (a field added to Config cannot silently swap another)."""
    return Config(probe=os.path.abspath(probe), deadline_s=deadline_s, catalogue=catalogue, budget=budget, caps=caps,
                  identity=identity, scene=scene)


def _identity(judges, caps):
    """U24: whether the explorer reads `identity` after every step: a selected judge needs it (ui-scene) and the probe
    announces it. Without the capability the judge set reports ui-scene's identity checks as `check-blocked`."""
    return judges is not None and judges.wants_identity(caps)


def _check_judges(judges, caps):
    """--judges need a probe with frame-facts; ui-render also one with ink (U07)."""
    if judges is None or caps is None:
        return
    if "frame-facts" not in caps:
        raise InternalError("--judges need a probe that announces frame-facts")
    if judges.needs_ink and "ink" not in caps:
        raise InternalError("--judges ui-render needs a probe that announces ink")


def _check_requires(catalogue, caps):
    missing = [cap for cap in catalogue.requires if cap not in caps]
    if missing:
        raise InternalError("the catalogue requires the probe capabilities %s, which the probe does not announce"
                            % ", ".join(missing))


def _check_taps(catalogue, caps, paths):
    taps = [event.id for event in catalogue.events if event.cls in ("u2", "u3")]
    if taps and not all(cap in caps for cap in TAP_CAPS):
        raise InternalError("catalogue taps %s need a probe that announces the tap capability and hit-test"
                            % ", ".join(taps))
    for words in paths or ():
        check_words(words, catalogue, caps)


def _summary(args, catalogue, explorer, criteria, evaluated, spent, detail, found):
    exploration = explorer.exploration
    events = {event.id: {"accepted_states": len(exploration.events[event.id].accepted),
                         "refused_states": len(exploration.events[event.id].refused),
                         "missed_states": len(exploration.events[event.id].missed)}
              for event in catalogue.events if event.id in exploration.events}
    return {"schema": SUMMARY_SCHEMA, "strategy": args.strategy, "criteria": list(criteria), "evaluated": evaluated,
            "budget_spent": spent, "catalogue_sha256": catalogue.sha256,
            "probe_sha256": jsonio.sha256_hex(jsonio.read_bytes(args.probe)), "runs": explorer.runs,
            "abstract_states": len(exploration.reachable), "pairs_exercised": len(exploration.exercised()),
            "domain_count": exploration.domain_count, "domain_visited": sorted(exploration.domain_visited),
            "events": events, "outcomes": exploration.outcomes, "taps": explorer.taps,
            "cost": {"probe_commands": explorer.commands, "virtual_ms": explorer.virtual_ms},
            "findings": _counts(found, explorer.config.scene is not None),
            "detail": detail}


def _counts(found, scene=False):
    """Findings per check: the explorer's own checks by name (all of them, 0 included; the U05e checks only in a run
    with scene taps or a contract), a judge's as `<gate>.<check>`."""
    counts = {check: sum(1 for f in found if f["check"] == check)
              for check in CHECKS + (SCENE_CHECKS if scene else ())}
    for item in found:
        if item["gate"] != "ui-explore":
            name = "%s.%s" % (item["gate"], item["check"])
            counts[name] = counts.get(name, 0) + 1
    return counts


def _remove(path):
    if path and os.path.lexists(path):
        os.unlink(path)


def _stop(signum, frame):
    """SIGTERM, SIGINT, SIGHUP: SIGKILL every live probe's group WITHOUT waiting (the interrupted code may hold
    Popen's wait lock), then exit 128 + the signal; `handle`'s finally reaps them."""
    del frame
    kill_all(reap=False)
    raise SystemExit(128 + signum)


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b) or (os.path.exists(a) and os.path.exists(b)
                                                          and os.path.samefile(a, b))


def _check_outputs(args):
    """An output that is an input (or the other output) is refused before anything is deleted. `args.out` is cleared
    first, so the CLI's error path does not remove it either."""
    inputs = [name for name in (args.catalogue, args.paths, args.probe, args.contract) if name]
    outputs = [name for name in (args.out, args.summary) if name]
    clash = [o for o in outputs if any(_same(o, i) for i in inputs)]
    if clash or (len(outputs) == 2 and _same(*outputs)):
        args.out = None
        raise InternalError("an output is the same file as an input or as the other output: %s"
                            % ", ".join(clash or outputs))


def handle(args):
    _check_outputs(args)
    _remove(args.out)              # a stale result never survives this run
    _remove(args.summary)
    previous = {sig: signal.signal(sig, _stop) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        found, summary = explore(args)
    finally:
        kill_all()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    jsonio.write_atomic(args.out, b"".join(jsonio.canonical_dumps(item) for item in found))
    if args.summary:
        jsonio.write_atomic(args.summary, jsonio.canonical_dumps(summary))
    errors = sum(1 for item in found if item["severity"] == "error")
    print("ui-explore %s: %d runs (each twice), %d abstract states, %d findings (%d errors); evaluated: %s"
          % (args.strategy, summary["runs"], summary["abstract_states"], len(found), errors,
             ",".join(summary["evaluated"]) or "none"))
    for name in ("states_per_depth", "dropped_states", "domain_count", "domain_visited", "walks", "paths",
                 "boot_seeds"):
        if name in summary["detail"]:
            print("  %s: %s" % (name, jsonio.canonical_dumps(summary["detail"][name]).decode("ascii").strip()))
    for item in found:
        print("  %s %s" % (item["severity"], item["id"]))
    return EXIT_FAIL if errors else EXIT_PASS
