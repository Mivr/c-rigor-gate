"""`c_mutants_schema`: the schema mutation engine's run stage, a prototype beside `c_mutants` (T124, P003 section 5).

Steps 1 to 3b of `rules/mutate.bzl` are shared with v1 (the mutant lists, the standalone compile of every mutant at
`-O2`, the `-O0` compile of the candidates for equivalent/duplicate): they decide which mutants v1 would run. Then,
instead of relinking every test with every mutated object and running each in a fresh process:

  4a  per source with such mutants: ONE schema compile (`schema.py generate`): the module's exact command, every
      schema-eligible mutant switchable at run time, the offenders of a failing schema found by bisection;
  4b  per test: ONE link of the test against the schema objects and `mutate/schema/schema_rt.c`
      (`-Wl,--wrap=main`);
  4c  per test: ONE `reach` action: the unmutated run, which must reproduce the v1 baseline, and the sites it executed;
  4d  per test: ONE `kill` action over the mutants that test reached: fork, activate, run, wait under the adaptive
      limit of T122. A mutant no test reaches is `unreached` and not run. No cross-test stop at the first kill;
      the report says what it would have saved;
  5   one `report.json` ({"engine": "schema"}: `mutate/schema/schema_compare.py collect`).

Nothing here decides a verdict. Compare with the v1 report of the same module by `schema_compare.py compare`.
"""

load("@prelude//cxx:cxx_toolchain_types.bzl", "CxxToolchainInfo")
load("@gate//rules:mutate.bzl", "MutSources", "mutate_helpers")

_H = mutate_helpers

def _declared(cfg, outputs):
    return [outputs[cfg.report].as_output()]

def _s1(dctx, artifacts, outputs, cfg):
    """Compile every mutant standalone, as v1's `_stage1`."""
    actions = dctx.actions
    compiled = {}
    ordered = []
    specs = {}
    function_of = {}
    for rel in sorted(cfg.gens.keys()):
        compiled[rel] = {}
        for mutant in artifacts[cfg.gens[rel]].read_json()["mutants"]:
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
    for batch in _H.batches(_H.batch_order(ordered, function_of), function_of, cfg.batch):
        for item, pair in _H.compile_batch(cfg, actions, batch, specs, "mutant/{}/{}".format(batch[0][0], batch[0][1])).items():
            compiled[item[0]][item[1]] = pair
    infos = [compiled[rel][mid][1] for rel, mid in ordered] + [cfg.base_info[r] for r in sorted(cfg.base_info.keys())]
    actions.dynamic_output(
        dynamic = infos,
        inputs = [],
        outputs = _declared(cfg, outputs),
        f = lambda d, a, o: _s2(d, a, o, cfg, compiled, ordered, specs, function_of),
    )

def _s2(dctx, artifacts, outputs, cfg, compiled, ordered, specs, function_of):
    """The -O0 compile of the candidates for equivalent/duplicate, as v1's `_stage2`."""
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
    for batch in _H.batches(_H.batch_order(candidates, function_of), function_of, cfg.batch):
        o0.update(_H.compile_batch(cfg, actions, batch, specs, "o0/mutant/{}/{}".format(batch[0][0], batch[0][1]), ["-O0"]))
    watched = [info for _, info in o0.values()] + [cfg.base_info_o0[r] for r in sorted(cfg.base_info_o0.keys())]
    actions.dynamic_output(
        dynamic = watched,
        inputs = [],
        outputs = _declared(cfg, outputs),
        f = lambda d, a, o: _s3(d, a, o, cfg, ordered, results, baseline_hash, o0),
    )

def _live(artifacts, cfg, ordered, results, baseline_hash, o0):
    """The mutants v1 runs ({rel: [id, ...]} in list order): v1's `_stage3` decision, nothing else of it."""
    base_o0 = {r: artifacts[cfg.base_info_o0[r]].read_json()["hash"] for r in cfg.base_info_o0}
    seen = {}
    pairs = {(rel, baseline_hash[rel], base_o0[rel]): "baseline" for rel in cfg.base_info}
    live = {rel: [] for rel in cfg.rels}
    for rel, mid in ordered:
        result = results[(rel, mid)]
        runs = False
        if result["status"] == "ok":
            folded = result["hash"] == baseline_hash[rel] or (rel, result["hash"]) in seen
            if (rel, mid) in o0:
                low = artifacts[o0[(rel, mid)][1]].read_json()
                if low["status"] == "ok":
                    key = (rel, result["hash"], low["hash"])
                    if folded and key not in pairs:
                        runs = True
                    if key not in pairs:
                        pairs[key] = mid
            seen[(rel, result["hash"])] = mid
            runs = runs or not folded
        if runs:
            live[rel].append(mid)
    return live

def _s3(dctx, artifacts, outputs, cfg, ordered, results, baseline_hash, o0):
    """4a schema compiles, 4b links, 4c reach runs."""
    actions = dctx.actions
    live = _live(artifacts, cfg, ordered, results, baseline_hash, o0)
    tables = {}
    objs = {}
    first = 1
    for rel in cfg.rels:
        if len(live[rel]) == 0:
            objs[rel] = cfg.base_obj[rel]
            continue
        ids = actions.write_json("schema/live/{}.json".format(rel), live[rel])
        src = actions.declare_output("schema/src/{}".format(rel))
        obj = actions.declare_output("schema/obj/{}.o".format(rel))
        table = actions.declare_output("schema/table/{}.json".format(rel))
        actions.run(
            cmd_args(
                _H.python(cfg.schema_py),
                "generate",
                "--src",
                cfg.src_by_rel[rel],
                "--gen-json",
                cfg.gens[rel],
                "--live",
                ids,
                "--first-index",
                str(first),
                "--gen-py",
                cfg.gen_py,
                "--rt-include",
                cmd_args(cfg.rt_header, parent = 1),
                "--out-src",
                src.as_output(),
                "--out-obj",
                obj.as_output(),
                "--out-table",
                table.as_output(),
                cfg.roots,
                "--",
                cfg.prefix,
            ),
            category = "schema_gen",
            identifier = rel,
        )
        first += len(live[rel])
        tables[rel] = table
        objs[rel] = obj
    reach = {}
    for test in cfg.test_names:
        binary = actions.declare_output("schema/bin/{}".format(test))
        actions.run(
            cmd_args(
                cfg.linker,
                cfg.link_flags,
                [o for _, o in cfg.test_objects[test]],
                [objs[r] for r in cfg.rels],
                "-Wl,--wrap=main",
                cfg.libs,
                "-o",
                binary.as_output(),
            ),
            category = "schema_link",
            identifier = test,
        )
        out = actions.declare_output("schema/reach/{}.json".format(test))
        actions.run(
            cmd_args(_H.python(cfg.run_py), "reach", "--tool", cfg.tool, "--binary", binary, "--out", out.as_output()),
            category = "schema_reach",
            identifier = test,
        )
        reach[test] = (binary, out)
    watched = [out for _, out in reach.values()] + [tables[r] for r in sorted(tables.keys())]
    actions.dynamic_output(
        dynamic = watched,
        inputs = [],
        outputs = _declared(cfg, outputs),
        f = lambda d, a, o: _s4(d, a, o, cfg, live, tables, reach),
    )

def _s4(dctx, artifacts, outputs, cfg, live, tables, reach):
    """4d kill actions over what each test reached, then the report."""
    actions = dctx.actions
    by_index = {}
    for rel in sorted(tables.keys()):
        for entry in artifacts[tables[rel]].read_json()["entries"]:
            by_index[entry["index"]] = entry["id"]
    kills = {}
    for test in cfg.test_names:
        reached = artifacts[reach[test][1]].read_json()["reached"]
        wanted = [{"index": i, "id": by_index[i]} for i in sorted(reached) if i in by_index]
        size = cfg.kill_chunk if cfg.kill_chunk > 0 else max(len(wanted), 1)
        kills[test] = []
        for start in range(0, len(wanted), size):
            ident = "{}/{}".format(test, start)
            listing = actions.write_json("schema/kill/{}.in.json".format(ident), wanted[start:start + size])
            out = actions.declare_output("schema/kill/{}.json".format(ident))
            actions.run(
                cmd_args(_H.python(cfg.run_py), "kill", "--tool", cfg.tool, "--binary", reach[test][0], "--mutants", listing, "--out", out.as_output()),
                category = "schema_kill",
                identifier = ident,
            )
            kills[test].append(out)
    manifest = actions.write_json("schema/manifest.json", {
        "label": cfg.label,
        "tests": cfg.test_names,
        "sources": [
            {"rel": r, "gen": cfg.gens[r], "table": tables.get(r), "live": live[r]}
            for r in cfg.rels
        ],
        "baseline_runs": cfg.baseline_runs,
        "reach": {t: reach[t][1] for t in cfg.test_names},
        "kills": kills,
    }, with_inputs = True)
    actions.run(
        cmd_args(_H.python(cfg.compare_py), "collect", "--manifest", manifest, "--out", outputs[cfg.report].as_output()),
        category = "schema_report",
    )

def _schema_impl(ctx: AnalysisContext) -> list[Provider]:
    sources = ctx.attrs.module_src[MutSources]
    if len(sources.srcs) == 0:
        fail("{}: the module has no sources".format(ctx.label))
    srcs = sorted(sources.srcs, key = lambda s: s.short_path)
    rels = [s.short_path for s in srcs]
    toolchain = ctx.attrs._toolchain[CxxToolchainInfo]
    tests = {_H.test_key(t.label): t for t in ctx.attrs.test_targets}
    if len(tests) != len(ctx.attrs.test_targets) or len(tests) == 0:
        fail("{}: tests must be a non-empty list of distinct targets".format(ctx.label))
    test_names = _H.test_order(ctx.attrs.module.label, tests)
    if ctx.attrs.batch < 1 or ctx.attrs.kill_chunk < 0:
        fail("{}: batch must be at least 1 and kill_chunk not negative".format(ctx.label))
    report = ctx.actions.declare_output("report.json")
    base = {
        "base_info": {},
        "base_info_o0": {},
        "base_obj": {},
        "batch": ctx.attrs.batch,
        "compare_py": ctx.attrs._compare,
        "gen_py": ctx.attrs._gen,
        "gens": {},
        "kill_chunk": ctx.attrs.kill_chunk,
        "label": _H.label_text(ctx.label),
        "libs": _H.link_inputs(ctx.label, ctx.attrs.deps + [ctx.attrs._ctest, ctx.attrs._rt]) + _H.system_lib_flags(ctx.label, [ctx.attrs.module] + ctx.attrs.deps),
        "link_flags": ctx.attrs.link_flags,
        "linker": toolchain.linker_info.linker,
        "prefix": _H.compile_prefix(ctx, sources, toolchain),
        "rels": rels,
        "report": report,
        "roots": ctx.attrs._roots[RunInfo],
        "rt_header": ctx.attrs._rt_header,
        "run_py": ctx.attrs._run,
        "schema_py": ctx.attrs._schema,
        "src_by_rel": {s.short_path: s for s in srcs},
        "test_names": test_names,
        "test_objects": {n: sorted(_H.objects(tests[n]).items()) for n in test_names},
        "tool": ctx.attrs._tool,
    }
    cfg = struct(**base)
    for src in srcs:
        rel = src.short_path
        out = ctx.actions.declare_output("gen/{}.json".format(rel))
        ctx.actions.run(
            cmd_args(
                _H.python(ctx.attrs._gen),
                "--src",
                src,
                "--out",
                out.as_output(),
                cfg.roots,
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
        for low in (False, True):
            ident = ("o0/baseline/" if low else "baseline/") + rel
            spec, msrc, obj, info = _H.compile_variant(ctx.actions, {"begin": 0, "end": 0, "original": "", "replacement": ""}, src, ident)
            _H.run_compile(cfg, ctx.actions, spec, src, msrc, obj, info, ident, True, ["-O0"] if low else None)
            if low:
                cfg.base_info_o0[rel] = info
            else:
                cfg.base_obj[rel] = obj
                cfg.base_info[rel] = info
    baseline_objects = [cfg.base_obj[r] for r in rels]
    runs = {t: _H.link_run(cfg, ctx.actions, baseline_objects, t, "baseline/" + t) for t in test_names}
    cfg = struct(baseline_runs = runs, **base)
    ctx.actions.dynamic_output(
        dynamic = cfg.gens.values(),
        inputs = [],
        outputs = [report.as_output()],
        f = lambda d, a, o: _s1(d, a, o, cfg),
    )
    return [DefaultInfo(default_output = report)]

c_mutants_schema_rule = rule(
    impl = _schema_impl,
    attrs = {
        "batch": attrs.int(default = _H.DEFAULT_BATCH),
        "deps": attrs.list(attrs.dep(), default = []),
        "kill_chunk": attrs.int(default = 0),
        "link_flags": attrs.list(attrs.string(), default = []),
        "module": attrs.dep(),
        "module_src": attrs.dep(providers = [MutSources]),
        "test_targets": attrs.list(attrs.dep()),
        "_compare": attrs.source(default = "gate//mutate/schema:schema_compare.py"),
        "_ctest": attrs.dep(default = "gate//ctest:ctest"),
        "_gen": attrs.source(default = "gate//mutate:gen.py"),
        "_roots": attrs.exec_dep(default = "toolchains//:system-roots", providers = [RunInfo]),
        "_rt": attrs.dep(default = "gate//mutate/schema:schema_rt"),
        "_rt_header": attrs.source(default = "gate//mutate/schema:schema_rt.h"),
        "_run": attrs.source(default = "gate//mutate/schema:schema_run.py"),
        "_schema": attrs.source(default = "gate//mutate/schema:schema.py"),
        "_tool": attrs.source(default = "gate//mutate:tool.py"),
        "_toolchain": attrs.toolchain_dep(default = "toolchains//:cxx", providers = [CxxToolchainInfo]),
    },
)

def c_mutants_schema(name, module, tests, deps = [], kill_chunk = 0):
    """The schema engine's run stage for a `c_library` and its `c_test`s (release mode only), beside `c_mutants`.

    `kill_chunk`: at most this many mutants per kill action (0: one action per test, as the design says)."""
    c_mutants_schema_rule(
        name = name,
        module = module,
        module_src = module + "_mutsrc",
        test_targets = tests,
        deps = deps,
        kill_chunk = kill_chunk,
        link_flags = [],
        target_compatible_with = ["toolchains//:release"],
    )
