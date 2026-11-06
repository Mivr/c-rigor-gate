"""`c_mutants`: mutation testing of one C module, one cached Buck2 action per mutant and test.

Pipeline (all on RE, release mode):
  1. per source: `gen.py` runs the pinned clang with the module's exact compile command and
     `-ast-dump=json`, and lists mutants as byte-exact text replacements;
  2. baseline: every source is recompiled unmodified through the same path, every test is relinked
     from those objects and run (it must pass), and the objects are compared with the ones Buck2's
     own compile produced (the harness must reproduce the real build);
  3. `dynamic_output` over the mutant lists: one compile action per mutant (same command, the
     mutated copy of the source), keyed on the spec and the source;
  4. `dynamic_output` over the compile results: an object whose hash equals the baseline object is
     equivalent (TCE), one equal to an earlier mutant's is a duplicate, a compile error is
     unviable; every other mutant is relinked into each test and run (one action per test);
  5. one report file with the raw facts. `rigor mutants` decides; nothing here says "killed".
"""

load("@prelude//cxx:cxx_toolchain_types.bzl", "CxxToolchainInfo")

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

def _objects(dep: Dependency) -> dict[str, Artifact]:
    """Plain (non-PIC) object files of a target, by the name Buck2 gave them (`<src>.o`)."""
    subs = dep[DefaultInfo].sub_targets
    if "objects" not in subs:
        fail("{}: no [objects] sub-target".format(dep.label))
    every = subs["objects"][DefaultInfo].sub_targets
    return {name: unit[DefaultInfo].default_outputs[0] for name, unit in every.items() if not name.endswith(".pic.o")}

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

def _python(script):
    return cmd_args("/usr/bin/env", "python3", "-I", "-B", script)

def _compile_variant(actions, spec_value, src, ident):
    spec = actions.write_json("spec/{}.json".format(ident), spec_value)
    msrc = actions.declare_output("mutated/{}/{}".format(ident, src.basename))
    obj = actions.declare_output("obj/{}.o".format(ident))
    info = actions.declare_output("obj/{}.json".format(ident))
    return spec, msrc, obj, info

def _run_compile(cfg, actions, spec, src, msrc, obj, info, ident, strict):
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
        ),
        category = "mutant_compile",
        identifier = ident,
    )

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

def _stage2(dctx, artifacts, outputs, cfg, compiled, ordered):
    actions = dctx.actions
    seen = {}
    baseline_hash = {r: artifacts[cfg.base_info[r]].read_json()["hash"] for r in cfg.base_info}
    manifest_mutants = {}
    for rel, mid in ordered:
        obj, info = compiled[rel][mid]
        result = artifacts[info].read_json()
        runs = {}
        live = result["status"] == "ok" and result["hash"] != baseline_hash[rel] and (rel, result["hash"]) not in seen
        if result["status"] == "ok":
            seen.setdefault((rel, result["hash"]), mid)
        if live:
            objects = [obj if r == rel else cfg.base_obj[r] for r in cfg.rels]
            for t in cfg.test_names:
                runs[t] = _link_run(cfg, actions, objects, t, "mutant/{}/{}/{}".format(rel, mid, t))
        manifest_mutants.setdefault(rel, {})[mid] = {"info": info, "runs": runs}
    manifest = actions.write_json("manifest.json", {
        "label": cfg.label,
        "tests": cfg.test_names,
        "sources": [
            {"rel": r, "gen": cfg.gens[r], "baseline": cfg.base_info[r], "original": cfg.original[r]}
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
    for rel in sorted(cfg.gens.keys()):
        data = artifacts[cfg.gens[rel]].read_json()
        compiled[rel] = {}
        for mutant in data["mutants"]:
            mid = mutant["id"]
            if mid in compiled[rel]:
                fail("duplicate mutant id {} in {}".format(mid, rel))
            ident = "mutant/{}/{}".format(rel, mid)
            spec_value = {
                "begin": mutant["begin_offset"],
                "end": mutant["end_offset"],
                "original": mutant["original"],
                "replacement": mutant["replacement"],
            }
            src = cfg.src_by_rel[rel]
            spec, msrc, obj, info = _compile_variant(actions, spec_value, src, ident)
            _run_compile(cfg, actions, spec, src, msrc, obj, info, ident, False)
            compiled[rel][mid] = (obj, info)
            ordered.append((rel, mid))
    infos = [compiled[rel][mid][1] for rel, mid in ordered] + [cfg.base_info[r] for r in sorted(cfg.base_info.keys())]
    actions.dynamic_output(
        dynamic = infos,
        inputs = [],
        outputs = [outputs[cfg.report].as_output()],
        f = lambda d, a, o: _stage2(d, a, o, cfg, compiled, ordered),
    )

def _mutants_impl(ctx: AnalysisContext) -> list[Provider]:
    sources = ctx.attrs.module_src[MutSources]
    if len(sources.srcs) == 0:
        fail("{}: the module has no sources".format(ctx.label))
    srcs = sorted(sources.srcs, key = lambda s: s.short_path)
    rels = [s.short_path for s in srcs]
    toolchain = ctx.attrs._toolchain[CxxToolchainInfo]
    real_objects = _objects(ctx.attrs.module)
    tests = {t.label.name: t for t in ctx.attrs.test_targets}
    if len(tests) != len(ctx.attrs.test_targets) or len(tests) == 0:
        fail("{}: tests must be a non-empty list of distinct targets".format(ctx.label))
    test_names = sorted(tests.keys())
    if len(real_objects) != len(srcs):
        fail("{}: the module compiled {} objects for {} sources".format(ctx.label, len(real_objects), len(srcs)))
    report = ctx.actions.declare_output("report.json")
    cfg_pieces = {
        "base_info": {},
        "base_obj": {},
        "gens": {},
        "label": _label_text(ctx.label),
        "libs": [d[DefaultInfo].default_outputs[0] for d in ctx.attrs.deps + [ctx.attrs._ctest]],
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
