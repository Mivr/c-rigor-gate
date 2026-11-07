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
  5. one report file with the raw facts. `rigor mutants` decides; nothing here says "killed".
"""

load("@prelude//cxx:cxx_toolchain_types.bzl", "CxxToolchainInfo")
load("@prelude//cxx:preprocessor.bzl", "CPreprocessorInfo")

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
            libs.append(outputs[0])
        elif not _own_headers(d):
            fail("{}: dep {} provides neither a library nor headers".format(label, d.label))
    return libs

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

def _link_run_batch(cfg, actions, batch, run_objs, test, ident):
    """One action links and runs every mutant of BATCH against TEST, each in its own process; returns
    {(rel, id): record}."""
    outs = {}
    items = []
    for item in batch:
        out = actions.declare_output("run/{}/{}.json".format(ident, item[1]))
        outs[item] = out
        items.append(cmd_args("--item", str(len(cfg.rels)), out.as_output(), [run_objs[item] if r == item[0] else cfg.base_obj[r] for r in cfg.rels]))
    actions.run(
        cmd_args(
            _python(cfg.tool),
            "linkrun-batch",
            items,
            "--",
            cfg.linker,
            cfg.link_flags,
            [o for _, o in cfg.test_objects[test]],
            "@MUTANT_OBJECTS@",
            cfg.libs,
        ),
        category = "mutant_run",
        identifier = ident,
    )
    return outs

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
        outputs = [outputs[cfg.report].as_output()],
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
        entry = {"info": info, "runs": {}}
        if extra != None:
            entry["o0"] = extra
        manifest_mutants.setdefault(rel, {})[mid] = entry
    for batch in _batches(_batch_order([i for i in ordered if i in run_objs], function_of), function_of, cfg.batch):
        for t in cfg.test_names:
            outs = _link_run_batch(cfg, actions, batch, run_objs, t, "mutant/{}/{}/{}".format(batch[0][0], batch[0][1], t))
            for item in batch:
                manifest_mutants[item[0]][item[1]]["runs"][t] = outs[item]
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
            compiled[rel][item[1]] = pair
    infos = [compiled[rel][mid][1] for rel, mid in ordered] + [cfg.base_info[r] for r in sorted(cfg.base_info.keys())]
    actions.dynamic_output(
        dynamic = infos,
        inputs = [],
        outputs = [outputs[cfg.report].as_output()],
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
    test_names = sorted(tests.keys())
    if len(real_objects) != len(srcs):
        fail("{}: the module compiled {} objects for {} sources".format(ctx.label, len(real_objects), len(srcs)))
    if ctx.attrs.batch < 1:
        fail("{}: batch must be at least 1".format(ctx.label))
    report = ctx.actions.declare_output("report.json")
    cfg_pieces = {
        "base_info": {},
        "base_info_o0": {},
        "base_obj": {},
        "batch": ctx.attrs.batch,
        "gens": {},
        "label": _label_text(ctx.label),
        "libs": _link_inputs(ctx.label, ctx.attrs.deps + [ctx.attrs._ctest]),
        "link_flags": ctx.attrs.link_flags,
        "linker": toolchain.linker_info.linker,
        "original": {},
        "prefix": _compile_prefix(ctx, sources, toolchain),
        "rels": rels,
        "report": report,
        "src_by_rel": {s.short_path: s for s in srcs},
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
        outputs = [report.as_output()],
        f = lambda d, a, o: _stage1(d, a, o, cfg),
    )
    return [DefaultInfo(default_output = report)]

c_mutants_rule = rule(
    impl = _mutants_impl,
    attrs = {
        "batch": attrs.int(default = _DEFAULT_BATCH),
        "deps": attrs.list(attrs.dep(), default = []),
        "link_flags": attrs.list(attrs.string(), default = []),
        "module": attrs.dep(),
        "module_src": attrs.dep(providers = [MutSources]),
        "test_targets": attrs.list(attrs.dep()),
        "_ctest": attrs.dep(default = "gate//ctest:ctest"),
        "_gen": attrs.source(default = "gate//mutate:gen.py"),
        "_toolchain": attrs.toolchain_dep(default = "toolchains//:cxx", providers = [CxxToolchainInfo]),
        "_roots": attrs.exec_dep(default = "toolchains//:system-roots", providers = [RunInfo]),
        "_tool": attrs.source(default = "gate//mutate:tool.py"),
    },
)
