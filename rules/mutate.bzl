"""`c_mutants`: mutation testing of one C module, one cached Buck2 action per mutant and test.

Pipeline (all on RE, release mode):
  1. per source: `gen.py` runs the pinned clang with the module's exact compile command and
     `-ast-dump=json`, and lists mutants as byte-exact text replacements;
  2. baseline: every source is recompiled unmodified through the same path, every test is relinked
     from those objects and run (it must pass), and the objects are compared with the ones Buck2's
     own compile produced (the harness must reproduce the real build);
  3. `dynamic_output` over the mutant lists: one compile action per batch of at most `batch` mutants of
     one source (T064; same command, the mutated copy of the source, one object and one record per
     mutant), keyed on the specs of the batch and the source. The batches are formed by `_batches`;
  4. `dynamic_output` over the compile results: an object whose hash equals the baseline object or an
     earlier mutant's is a candidate for equivalent (TCE) or duplicate, a compile error is unviable;
     every other mutant is relinked into each test and run (one action per batch and test, each mutant in
     its own process and scratch directory, one record per mutant). The optimiser can
     fold a behaviour-changing mutation to the baseline object (R001 R2, B15), so every candidate is
     compiled again at -O0 (the same command with `-O0` appended) and so is the baseline;
  4b. `dynamic_output` over those -O0 compiles: a candidate stays equivalent (or duplicate) only if
     its -O0 object is identical too; otherwise it is live and its -O0 object is relinked into each
     test and run. Mutants that already differ at -O2 cost nothing extra;
  4c. (`perf = [...]`, T090) for every mutant that survived all tests: the perf binary of each listed `c_perf`
     target is relinked with the mutated object and run (one action per survivor and target; the unmutated
     module is run once per target as the baseline); the counts go to the `[perf]` sub-target. Functional killers
     cost nothing extra;
  5. one report file with the raw facts. `rigor mutants` decides; nothing here says "killed".
"""

load("@prelude//cxx:cxx_toolchain_types.bzl", "CxxToolchainInfo")
load("@prelude//cxx:preprocessor.bzl", "CPreprocessorInfo")
load("@prelude//linking:link_info.bzl", "LinkStrategy", "MergedLinkInfo")
load("@gate//rules:perf.bzl", "PERF_WRAPS", "PerfInfo")

MutSources = provider(fields = ["srcs", "headers"])

def _mutsrc_impl(ctx: AnalysisContext) -> list[Provider]:
    return [DefaultInfo(), MutSources(srcs = ctx.attrs.srcs, headers = ctx.attrs.headers)]

mutsrc = rule(
    impl = _mutsrc_impl,
    attrs = {
        "headers": attrs.list(attrs.source(), default = []),
        "srcs": attrs.list(attrs.source(), default = []),
    },
)

def _label_text(label: Label) -> str:
    cell = "" if label.cell == "root" else label.cell
    return "{}//{}:{}".format(cell, label.package, label.name)

_TEST_KEY_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_"

def _test_key(label: Label) -> str:
    """Unique name of a test in the report and in action identifiers: `<package>__<name>` with every
    character outside [a-z0-9_] turned into `_`. (Two packages may each have a test called `arena_test`.)"""
    return "".join([c if c in _TEST_KEY_CHARS else "_" for c in (label.package + "__" + label.name).elems()])

def _test_order(module: Label, tests: dict) -> list:
    """The order in which a mutant's tests run: the tests of the module's own package first, then the others, each
    sorted by their key (`<package>__<name>`). Fixed by the labels alone, so the same on every grade."""
    own = sorted([k for k in tests if tests[k].label.package == module.package and tests[k].label.cell == module.cell])
    return own + sorted([k for k in tests if k not in own])

def _test_groups(module: Label, tests: dict) -> list:
    """`_test_order` cut into the groups that become one action each: the module's own tests together, the rest
    in groups of `_GROUP_TESTS`."""
    order = _test_order(module, tests)
    own = [k for k in order if tests[k].label.package == module.package and tests[k].label.cell == module.cell]
    rest = order[len(own):]
    groups = [own] if own else []
    for start in range(0, len(rest), _GROUP_TESTS):
        groups.append(rest[start:start + _GROUP_TESTS])
    return groups

def _objects(dep: Dependency) -> dict[str, Artifact]:
    """Plain (non-PIC) object files of a target, by the name Buck2 gave them (`<src>.o`)."""
    subs = dep[DefaultInfo].sub_targets
    if "objects" not in subs:
        fail("{}: no [objects] sub-target".format(dep.label))
    every = subs["objects"][DefaultInfo].sub_targets
    return {name: unit[DefaultInfo].default_outputs[0] for name, unit in every.items() if not name.endswith(".pic.o")}

def _own_headers(dep: Dependency) -> bool:
    """Does this target export header files of its own?"""
    info = dep.get(CPreprocessorInfo)
    if info == None or info.set == None or info.set.value == None:
        return False
    return any([len(p.headers) > 0 or len(p.raw_headers) > 0 for p in info.set.value])

def _link_inputs(label: Label, deps: list[Dependency]) -> list[Artifact]:
    """The archives the tests link besides their own objects. A header-only kit (a `c_library` without
    sources) has no archive: the tests were compiled against its headers by Buck2 and it adds nothing to
    the link line. A dep that provides neither a library nor headers is a mistake, never dropped."""
    libs = []
    for d in deps:
        outputs = d[DefaultInfo].default_outputs
        if len(outputs) > 0:
            if outputs[0] not in libs:  # a library named twice (e.g. ctest, which every c_test links) is linked once
                libs.append(outputs[0])
        elif not _own_headers(d):
            fail("{}: dep {} provides neither a library nor headers".format(label, d.label))
    return libs

def _system_lib_flags(label: Label, deps: list[Dependency]) -> list:
    """The post-link flags the libraries export (`system_libs` of `c_library`, T095), each once, in link order.

    The mutant links are raw linker commands, not Buck2 link actions, so the flags Buck2 would add for the
    library are read from its link info. Only `-l<name>` flags are accepted: anything else is a mistake."""
    flags = []
    seen = []
    for d in deps:
        info = d.get(MergedLinkInfo)
        if info == None:
            continue
        for infos in info._infos[LinkStrategy("static")].traverse():
            for flag in infos.default.post_flags:
                # Buck2 hands the flag over as a resolved string whose text is quoted, not as a plain string.
                text = str(flag).strip("\"")
                if not text.startswith("-l"):
                    fail("{}: unexpected post-link flag {} from {}".format(label, text, d.label))
                if text not in seen:
                    seen.append(text)
                    flags.append(flag)
    return flags

def _compile_prefix(ctx, headers, toolchain):
    """The module's exact compile command up to the source: toolchain clang, then its argsfile."""
    info = ctx.attrs.module[DefaultInfo].sub_targets["argsfiles"][DefaultInfo]
    argsfile = None
    for item in info.other_outputs:
        if type(item) == "Artifact" and item.basename.endswith(".cxx_compile_argsfile") and ".pic." not in item.basename:
            argsfile = item
    if argsfile == None:
        fail("{}: no compile argsfile found".format(ctx.attrs.module.label))
    return cmd_args(
        toolchain.c_compiler_info.compiler,
        cmd_args(argsfile, format = "@{}"),
        [cmd_args("-iquote", cmd_args(f, parent = 1)) for f in headers.srcs + headers.headers],
        hidden = info.other_outputs + headers.srcs + headers.headers,
    )

_DEFAULT_BATCH = 16

# Stop at the first kill (T121). A mutant's tests run in a fixed order (`_test_order`), in groups of at most
# `_GROUP_TESTS` tests; the runs of a mutant stop at the first one that fails a check ("assert"): its later runs are
# skipped and say which test killed it. A crash does not stop the runs, because the verdict is killed-assert when ANY
# test fails a check (crash only when none does): stopping at a crash could change the verdict. "never" runs
# everything (the old behaviour).
_STOP_ON = "assert"
_GROUP_TESTS = 16

def _batch_order(items, function_of):
    """The order in which mutants are packed into batches: by source, function, id. (`ordered`, the order of the
    mutant lists, stays the order of every decision: which of two mutants with one object is the duplicate.)"""
    return sorted(items, key = lambda i: (i[0], function_of[i], i[1]))

def _batches(items, function_of, size):
    """Deterministic batches of at most SIZE items. ITEMS are (rel, id) pairs of one module in `_batch_order`.
    A batch holds whole functions where it can: a function that fits is never split, so editing one function
    changes the mutants of few batches. A batch may span sources (one action compiles or runs mutants of several).
    Every item is in exactly one batch."""
    out = []
    current = []
    groups = []
    for item in items:  # runs of the same (rel, function)
        key = (item[0], function_of[item])
        if groups and groups[-1][0] == key:
            groups[-1][1].append(item)
        else:
            groups.append((key, [item]))
    for _, group in groups:
        if current and len(current) + len(group) > size:
            out.append(current)
            current = []
        for item in group:
            if len(current) == size:
                out.append(current)
                current = []
            current.append(item)
    if current:
        out.append(current)
    return out

def _python(script):
    return cmd_args("/usr/bin/env", "python3", "-I", "-B", script)

def _compile_variant(actions, spec_value, src, ident):
    spec = actions.write_json("spec/{}.json".format(ident), spec_value)
    msrc = actions.declare_output("mutated/{}/{}".format(ident, src.basename))
    obj = actions.declare_output("obj/{}.o".format(ident))
    info = actions.declare_output("obj/{}.json".format(ident))
    return spec, msrc, obj, info

def _run_compile(cfg, actions, spec, src, msrc, obj, info, ident, strict, extra = None):
    actions.run(
        cmd_args(
            _python(cfg.tool),
            "compile",
            "--spec",
            spec,
            "--src",
            src,
            "--src-out",
            msrc.as_output(),
            "--obj",
            obj.as_output(),
            "--info",
            info.as_output(),
            "--strict" if strict else "--lenient",
            "--",
            cfg.prefix,
            extra if extra else [],
        ),
        category = "mutant_compile_o0" if extra else "mutant_compile",
        identifier = ident,
    )

def _compile_batch(cfg, actions, batch, specs, ident, extra = None):
    """One action compiles every mutant of BATCH (of any sources); returns {(rel, id): (obj, info)}."""
    spec = actions.write_json("spec/{}.json".format(ident), {"mutants": [dict(specs[item], id = item[1]) for item in batch]})
    outputs = {}
    items = []
    for item in batch:
        obj = actions.declare_output("obj/{}/{}.o".format(ident, item[1]))
        info = actions.declare_output("obj/{}/{}.json".format(ident, item[1]))
        outputs[item] = (obj, info)
        items.append(cmd_args("--item", cfg.src_by_rel[item[0]], item[1], obj.as_output(), info.as_output()))
    actions.run(
        cmd_args(
            _python(cfg.tool),
            "compile-batch",
            "--specs",
            spec,
            items,
            "--lenient",
            "--",
            cfg.prefix,
            extra if extra else [],
        ),
        category = "mutant_compile_o0" if extra else "mutant_compile",
        identifier = ident,
    )
    return outputs

def _link_run(cfg, actions, objects, test, ident):
    out = actions.declare_output("run/{}.json".format(ident))
    actions.run(
        cmd_args(
            _python(cfg.tool),
            "linkrun",
            "--out",
            out.as_output(),
            "--",
            cfg.linker,
            cfg.link_flags,
            [o for _, o in cfg.test_objects[test]],
            objects,
            cfg.libs,
        ),
        category = "mutant_run",
        identifier = ident,
    )
    return out

def _link_run_batch(cfg, actions, batch, run_objs, group, priors, ident):
    """One action links and runs every mutant of BATCH against the tests of GROUP, in that order, each run in its
    own process; returns {(rel, id): record file}. A record holds {"runs": {test: run}}. `priors` (item -> the record
    of the group before, or None) lets the tool skip a mutant that an earlier group already killed (T121); inside the
    action it stops at the first run that fails a check. The skipped runs say which test killed the mutant. The
    baseline objects let the tool derive each binary's kill limit from its unmutated run (T122)."""
    outs = {}
    items = []
    for item in batch:
        out = actions.declare_output("run/{}/{}.json".format(ident, item[1]))
        outs[item] = out
        items.append(cmd_args(
            "--item",
            str(len(cfg.rels)),
            out.as_output(),
            [run_objs[item] if r == item[0] else cfg.base_obj[r] for r in cfg.rels],
            cmd_args("--prior", priors[item]) if priors[item] != None else [],
        ))
    tests = [cmd_args("--test", t, str(len(cfg.test_objects[t])), [o for _, o in cfg.test_objects[t]]) for t in group]
    actions.run(
        cmd_args(
            _python(cfg.tool),
            "linkrun-batch",
            "--stop-on",
            _STOP_ON,
            cmd_args("--baseline", str(len(cfg.rels)), [cfg.base_obj[r] for r in cfg.rels]),
            tests,
            items,
            "--",
            cfg.linker,
            cfg.link_flags,
            "@TEST_OBJECTS@",
            "@MUTANT_OBJECTS@",
            cfg.libs,
        ),
        category = "mutant_run",
        identifier = ident,
    )
    return outs

def _declared(cfg, outputs):
    """The outputs every dynamic step of the chain declares: the report, and the perf records if there are any."""
    return [outputs[o].as_output() for o in cfg.outs]

def _stage2(dctx, artifacts, outputs, cfg, compiled, ordered, specs, function_of):
    """Decide from the -O2 objects; every mutant that would be equivalent or a duplicate is compiled
    again at -O0 (and only those), then `_stage3` decides with both."""
    actions = dctx.actions
    baseline_hash = {r: artifacts[cfg.base_info[r]].read_json()["hash"] for r in cfg.base_info}
    results = {}
    count = {}
    for rel, mid in ordered:
        result = artifacts[compiled[rel][mid][1]].read_json()
        results[(rel, mid)] = result
        if result["status"] == "ok":
            count[(rel, result["hash"])] = count.get((rel, result["hash"]), 0) + 1
    o0 = {}
    candidates = [
        (rel, mid)
        for rel, mid in ordered
        if results[(rel, mid)]["status"] == "ok" and (results[(rel, mid)]["hash"] == baseline_hash[rel] or count[(rel, results[(rel, mid)]["hash"])] > 1)
    ]
    for batch in _batches(_batch_order(candidates, function_of), function_of, cfg.batch):
        o0.update(_compile_batch(cfg, actions, batch, specs, "o0/mutant/{}/{}".format(batch[0][0], batch[0][1]), ["-O0"]))
    watched = [info for _, info in o0.values()] + [cfg.base_info_o0[r] for r in sorted(cfg.base_info_o0.keys())]
    actions.dynamic_output(
        dynamic = watched,
        inputs = [],
        outputs = _declared(cfg, outputs),
        f = lambda d, a, o: _stage3(d, a, o, cfg, compiled, ordered, results, baseline_hash, o0, function_of),
    )

def _stage3(dctx, artifacts, outputs, cfg, compiled, ordered, results, baseline_hash, o0, function_of):
    """The verdict-relevant runs. A candidate (same -O2 object as the baseline or as an earlier mutant)
    is equivalent / a duplicate only if its -O0 object matches too (the baseline's, or that of the
    earlier mutant with the same -O2 object); otherwise it is live and its -O0 object is run.
    `mutants_verdict.derive` makes the same decisions from the report: keep the two in step."""
    actions = dctx.actions
    base_o0 = {r: artifacts[cfg.base_info_o0[r]].read_json()["hash"] for r in cfg.base_info_o0}
    seen = {}
    pairs = {(rel, baseline_hash[rel], base_o0[rel]): "baseline" for rel in cfg.base_info}
    manifest_mutants = {}
    run_objs = {}
    for rel, mid in ordered:
        obj, info = compiled[rel][mid]
        result = results[(rel, mid)]
        extra = None
        live = False
        run_obj = obj
        if result["status"] == "ok":
            folded = result["hash"] == baseline_hash[rel] or (rel, result["hash"]) in seen
            if (rel, mid) in o0:
                extra = o0[(rel, mid)][1]
                low = artifacts[extra].read_json()
                if low["status"] == "ok":
                    key = (rel, result["hash"], low["hash"])
                    if folded and key not in pairs:
                        live = True
                        run_obj = o0[(rel, mid)][0]
                    if key not in pairs:
                        pairs[key] = mid
            seen[(rel, result["hash"])] = mid
            live = live or not folded
        if live:
            run_objs[(rel, mid)] = run_obj
        entry = {"info": info, "runs": []}
        if extra != None:
            entry["o0"] = extra
        manifest_mutants.setdefault(rel, {})[mid] = entry
    for batch in _batches(_batch_order([i for i in ordered if i in run_objs], function_of), function_of, cfg.batch):
        priors = {item: None for item in batch}
        for number, group in enumerate(cfg.test_groups):
            outs = _link_run_batch(cfg, actions, batch, run_objs, group, priors, "mutant/{}/{}/g{}".format(batch[0][0], batch[0][1], number))
            for item in batch:
                manifest_mutants[item[0]][item[1]]["runs"].append(outs[item])
                priors[item] = outs[item]
    manifest = actions.write_json("manifest.json", {
        "label": cfg.label,
        "tests": cfg.test_names,
        "sources": [
            {"rel": r, "gen": cfg.gens[r], "baseline": cfg.base_info[r], "baseline_o0": cfg.base_info_o0[r],
             "original": cfg.original[r]}
            for r in sorted(cfg.gens.keys())
        ],
        "baseline_runs": cfg.baseline_runs,
        "mutants": manifest_mutants,
    }, with_inputs = True)
    actions.run(
        cmd_args(_python(cfg.tool), "collect", "--manifest", manifest, "--out", outputs[cfg.report].as_output()),
        category = "mutant_report",
    )
    if cfg.perf_out != None:
        runs = {item: manifest_mutants[item[0]][item[1]]["runs"] for item in run_objs}
        watched = [out for item in run_objs for out in runs[item]]
        actions.dynamic_output(
            dynamic = watched,
            inputs = [],
            outputs = [outputs[cfg.perf_out].as_output()],
            f = lambda d, a, o: _stage4(d, a, o, cfg, run_objs, runs),
        )

def _perf_run(cfg, actions, script, target, objects, ident):
    """Relink one perf binary with OBJECTS (the driver's, then the module's), run it, return the output file:
    the harness records (JSON Lines), or one marker line when linking or the harness failed."""
    out = actions.declare_output("perf/{}.jsonl".format(ident))
    actions.run(
        cmd_args(
            "/bin/sh",
            script,
            out.as_output(),
            target.name,
            str(target.seed),
            ",".join([str(n) for n in target.sizes]),
            "--",
            cfg.linker,
            cfg.link_flags,
            ["-Wl,--wrap=" + f for f in PERF_WRAPS],
            target.objects,
            objects,
            cfg.perf_libs,
        ),
        category = "mutant_perf",
        identifier = ident,
    )
    return out

_PERF_SCRIPT = [
    "set -u",
    'out="$1"; name="$2"; seed="$3"; sizes="$4"; shift 5',
    'scratch="$(mktemp -d)" || exit 1',
    'trap \'rm -rf "$scratch"\' EXIT',
    'if ! "$@" -o "$scratch/bin" 2> "$scratch/link.err"; then printf \'{"marker":"link-failed"}\\n\' > "$out"; exit 0; fi',
    'rc=0',
    '"$scratch/bin" --name "$name" --seed "$seed" --sizes "$sizes" --out "$out" > /dev/null 2>&1 || rc=$?',
    'if [ "$rc" -ne 0 ] || [ ! -s "$out" ]; then printf \'{"marker":"harness-failed","rc":%s}\\n\' "$rc" > "$out"; fi',
    "exit 0",
]

_PERF_COLLECT = """
import json, sys
manifest = json.load(open(sys.argv[1]))
targets = {}
def records(path):
    found = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            found.append(json.loads(line))
    return found
for label, entry in manifest["targets"].items():
    targets[label] = {"baseline": records(entry["baseline"]),
                      "mutants": {key: records(path) for key, path in entry["mutants"].items()}}
with open(sys.argv[2], "w", encoding="utf-8") as out:
    json.dump({"schema": 1, "label": manifest["label"], "targets": targets}, out, sort_keys=True, separators=(",", ":"))
    out.write("\\n")
"""

def _stage4(dctx, artifacts, outputs, cfg, run_objs, runs):
    """The perf runs. A mutant is a candidate when every test passed with it (a superset of the survivors that
    `mutants_verdict` derives: it also needs the results to parse); the baseline is run once per target through
    the same link, so a mutant is only judged against a baseline that was measured the same way."""
    actions = dctx.actions
    candidates = []
    for item in sorted(run_objs.keys()):
        passed = True
        for out in runs[item]:
            for record in artifacts[out].read_json()["runs"].values():
                if "killed_by" in record or record["rc"] != 0 or record["timed_out"]:   # a skipped run follows a kill
                    passed = False
        if passed:
            candidates.append(item)
    script = actions.write("perf/run.sh", _PERF_SCRIPT, is_executable = True)
    entries = {}
    for index, target in enumerate(cfg.perf):
        baseline = _perf_run(cfg, actions, script, target, [cfg.base_obj[r] for r in cfg.rels], "{}/baseline".format(index))
        mutants = {}
        for item in candidates:
            objs = [run_objs[item] if r == item[0] else cfg.base_obj[r] for r in cfg.rels]
            mutants[item[1]] = _perf_run(cfg, actions, script, target, objs, "{}/{}/{}".format(index, item[0], item[1]))
        entries[target.label] = {"baseline": baseline, "mutants": mutants}
    manifest = actions.write_json("perf/manifest.json", {"label": cfg.label, "targets": entries}, with_inputs = True)
    collect = actions.write("perf/collect.py", _PERF_COLLECT)
    actions.run(
        cmd_args(_python(collect), manifest, outputs[cfg.perf_out].as_output()),
        category = "mutant_perf_report",
    )

def _stage1(dctx, artifacts, outputs, cfg):
    actions = dctx.actions
    compiled = {}
    ordered = []
    specs = {}
    function_of = {}
    for rel in sorted(cfg.gens.keys()):
        data = artifacts[cfg.gens[rel]].read_json()
        compiled[rel] = {}
        for mutant in data["mutants"]:
            mid = mutant["id"]
            if mid in compiled[rel]:
                fail("duplicate mutant id {} in {}".format(mid, rel))
            compiled[rel][mid] = None
            specs[(rel, mid)] = {
                "begin": mutant["begin_offset"],
                "end": mutant["end_offset"],
                "original": mutant["original"],
                "replacement": mutant["replacement"],
            }
            function_of[(rel, mid)] = mutant["function"]
            ordered.append((rel, mid))
    for batch in _batches(_batch_order(ordered, function_of), function_of, cfg.batch):
        for item, pair in _compile_batch(cfg, actions, batch, specs, "mutant/{}/{}".format(batch[0][0], batch[0][1])).items():
            compiled[item[0]][item[1]] = pair
    infos = [compiled[rel][mid][1] for rel, mid in ordered] + [cfg.base_info[r] for r in sorted(cfg.base_info.keys())]
    actions.dynamic_output(
        dynamic = infos,
        inputs = [],
        outputs = _declared(cfg, outputs),
        f = lambda d, a, o: _stage2(d, a, o, cfg, compiled, ordered, specs, function_of),
    )

def _mutants_impl(ctx: AnalysisContext) -> list[Provider]:
    sources = ctx.attrs.module_src[MutSources]
    if len(sources.srcs) == 0:
        fail("{}: the module has no sources".format(ctx.label))
    srcs = sorted(sources.srcs, key = lambda s: s.short_path)
    rels = [s.short_path for s in srcs]
    toolchain = ctx.attrs._toolchain[CxxToolchainInfo]
    real_objects = _objects(ctx.attrs.module)
    tests = {_test_key(t.label): t for t in ctx.attrs.test_targets}
    if len(tests) != len(ctx.attrs.test_targets) or len(tests) == 0:
        fail("{}: tests must be a non-empty list of distinct targets".format(ctx.label))
    test_names = _test_order(ctx.attrs.module.label, tests)
    if len(real_objects) != len(srcs):
        fail("{}: the module compiled {} objects for {} sources".format(ctx.label, len(real_objects), len(srcs)))
    if ctx.attrs.batch < 1:
        fail("{}: batch must be at least 1".format(ctx.label))
    report = ctx.actions.declare_output("report.json")
    perf_out = ctx.actions.declare_output("perf.json") if len(ctx.attrs.perf) > 0 else None
    perf = [
        struct(
            label = _label_text(p.label),
            name = p[PerfInfo].name,
            seed = p[PerfInfo].seed,
            sizes = p[PerfInfo].sizes,
            objects = p[PerfInfo].objects,
        )
        for p in ctx.attrs.perf
    ]
    if len(set([t.label for t in perf])) != len(perf):
        fail("{}: perf targets must be distinct".format(ctx.label))
    # The perf binary links the driver, the module and the libraries of its own deps, never ctest (which has a main of its own).
    perf_libs = _link_inputs(ctx.label, ctx.attrs.deps) + [ctx.attrs._perfkit[DefaultInfo].default_outputs[0]] + _system_lib_flags(ctx.label, [ctx.attrs.module] + ctx.attrs.deps) if perf else []
    cfg_pieces = {
        "base_info": {},
        "base_info_o0": {},
        "base_obj": {},
        "batch": ctx.attrs.batch,
        "gens": {},
        "label": _label_text(ctx.label),
        "libs": _link_inputs(ctx.label, ctx.attrs.deps + [ctx.attrs._ctest]) + _system_lib_flags(ctx.label, [ctx.attrs.module] + ctx.attrs.deps),
        "link_flags": ctx.attrs.link_flags,
        "linker": toolchain.linker_info.linker,
        "original": {},
        "outs": [report] + ([perf_out] if perf_out != None else []),
        "perf": perf,
        "perf_libs": perf_libs,
        "perf_out": perf_out,
        "prefix": _compile_prefix(ctx, sources, toolchain),
        "rels": rels,
        "report": report,
        "src_by_rel": {s.short_path: s for s in srcs},
        "test_groups": _test_groups(ctx.attrs.module.label, tests),
        "test_names": test_names,
        "test_objects": {n: sorted(_objects(tests[n]).items()) for n in test_names},
        "tool": ctx.attrs._tool,
    }
    cfg = struct(**cfg_pieces)

    # 1. mutant lists, 2. baseline objects and their comparison with Buck2's own objects
    for src in srcs:
        rel = src.short_path
        out = ctx.actions.declare_output("gen/{}.json".format(rel))
        ctx.actions.run(
            cmd_args(
                _python(ctx.attrs._gen),
                "--src",
                src,
                "--out",
                out.as_output(),
                ctx.attrs._roots[RunInfo],
                "--",
                cfg.prefix,
                "-Xclang",
                "-ast-dump=json",
                "-fsyntax-only",
                src,
            ),
            category = "mutant_list",
            identifier = rel,
        )
        cfg.gens[rel] = out
        ident = "baseline/" + rel
        spec, msrc, obj, info = _compile_variant(
            ctx.actions,
            {"begin": 0, "end": 0, "original": "", "replacement": ""},
            src,
            ident,
        )
        _run_compile(cfg, ctx.actions, spec, src, msrc, obj, info, ident, True)
        cfg.base_obj[rel] = obj
        cfg.base_info[rel] = info

        # the same unmodified source at -O0: what a mutant that the optimiser folded is compared with (B15)
        ident0 = "o0/baseline/" + rel
        spec0, msrc0, obj0, info0 = _compile_variant(
            ctx.actions,
            {"begin": 0, "end": 0, "original": "", "replacement": ""},
            src,
            ident0,
        )
        _run_compile(cfg, ctx.actions, spec0, src, msrc0, obj0, info0, ident0, True, ["-O0"])
        cfg.base_info_o0[rel] = info0
        real = real_objects.get(rel + ".o")
        if real == None:
            fail("{}: no Buck2 object for {}".format(ctx.label, rel))
        hashed = ctx.actions.declare_output("original/{}.json".format(rel))
        ctx.actions.run(
            cmd_args(_python(ctx.attrs._tool), "hash", "--obj", real, "--out", hashed.as_output()),
            category = "original_hash",
            identifier = rel,
        )
        cfg.original[rel] = hashed
    baseline_objects = [cfg.base_obj[r] for r in rels]
    cfg_runs = {t: _link_run(cfg, ctx.actions, baseline_objects, t, "baseline/" + t) for t in test_names}
    cfg = struct(baseline_runs = cfg_runs, **cfg_pieces)

    ctx.actions.dynamic_output(
        dynamic = cfg.gens.values(),
        inputs = [],
        outputs = [o.as_output() for o in cfg.outs],
        f = lambda d, a, o: _stage1(d, a, o, cfg),
    )
    subs = {"perf": [DefaultInfo(default_output = perf_out)]} if perf_out != None else {}
    return [DefaultInfo(default_output = report, sub_targets = subs)]

c_mutants_rule = rule(
    impl = _mutants_impl,
    attrs = {
        "batch": attrs.int(default = _DEFAULT_BATCH),
        "deps": attrs.list(attrs.dep(), default = []),
        "link_flags": attrs.list(attrs.string(), default = []),
        "module": attrs.dep(),
        "module_src": attrs.dep(providers = [MutSources]),
        "perf": attrs.list(attrs.dep(providers = [PerfInfo]), default = []),
        "test_targets": attrs.list(attrs.dep()),
        "_ctest": attrs.dep(default = "gate//ctest:ctest"),
        "_perfkit": attrs.dep(default = "gate//ctest:perf"),
        "_gen": attrs.source(default = "gate//mutate:gen.py"),
        "_toolchain": attrs.toolchain_dep(default = "toolchains//:cxx", providers = [CxxToolchainInfo]),
        "_roots": attrs.exec_dep(default = "toolchains//:system-roots", providers = [RunInfo]),
        "_tool": attrs.source(default = "gate//mutate:tool.py"),
    },
)
