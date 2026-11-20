"""`c_wasm` support (P008, docs/toolchain.md "WebAssembly (wasm32)"): a freestanding wasm32 module from `c_library` targets.

The deps are configured to `toolchains//:wasm32_release` by the `to_wasm32` transition, so the prelude compiles and
archives them with the wasm32 toolchain (`toolchains//:cxx` selects it on the wasm32 cpu) and the release flags. This
rule then compiles the gate's freestanding string library (toolchains/wasm/rt/fsl.c) with the same flags and links
everything with `lld -flavor wasm`. The `.wasm` is an artifact: no facts, no tests, no grade of its own.
"""

load("@prelude//linking:link_info.bzl", "LinkStrategy", "MergedLinkInfo")

def _to_wasm32_impl(platform: PlatformInfo, refs: struct) -> PlatformInfo:
    # Whatever the incoming `platform` (linux_release, or wasm32_release itself), the deps are built for wasm32.
    return refs.wasm32[PlatformInfo]

to_wasm32 = transition(
    impl = _to_wasm32_impl,
    refs = {"wasm32": "toolchains//:wasm32_release"},
)

def _archives(label: Label, deps: list[Dependency]) -> list:
    """The static archives (and loose objects) of the deps' whole link closure, each once, as link-line arguments.

    A dep must be a static C library; one that exports linker flags (`system_libs`, e.g. `-lpthread`) cannot be part
    of a wasm module, which links no system library, and fails the analysis."""
    args = []
    seen = []
    for d in deps:
        info = d.get(MergedLinkInfo)
        if info == None:
            fail("{}: dep {} is not a c_library (no link info)".format(label, d.label))
        for infos in info._infos[LinkStrategy("static")].traverse():
            link = infos.default
            if link.pre_flags or link.post_flags:
                fail("{}: dep {} links system libraries or flags ({}); a wasm32 module links none".format(
                    label,
                    d.label,
                    [str(f) for f in link.pre_flags + link.post_flags],
                ))
            for linkable in link.linkables:
                args.extend(_linkable_args(label, d, linkable, seen))
    return args

def _linkable_args(label: Label, dep: Dependency, linkable, seen: list) -> list:
    if hasattr(linkable, "archive"):
        files = [linkable.archive.artifact]
    elif hasattr(linkable, "objects"):
        files = linkable.objects or []
    else:
        fail("{}: dep {} brings a linkable that is not a static archive or object: {}".format(label, dep.label, linkable))
    files = [f for f in files if f not in seen]
    seen.extend(files)
    if files and linkable.link_whole:
        return ["--whole-archive"] + files + ["--no-whole-archive"]
    return files

def _wasm_module_impl(ctx: AnalysisContext) -> list[Provider]:
    """`<name>.wasm`: the deps' archives and the compiled fsl.c, linked by `lld -flavor wasm` with exactly `exports`."""
    rt_obj = ctx.actions.declare_output("rt/fsl.o")
    ctx.actions.run(
        cmd_args(ctx.attrs._cc[RunInfo], ctx.attrs.compile_flags, "-c", ctx.attrs._rt, "-o", rt_obj.as_output()),
        category = "wasm_compile",
        identifier = "fsl.c",
    )
    out = ctx.actions.declare_output(ctx.attrs.out)
    link = cmd_args(
        ctx.attrs._ld[RunInfo],
        "--no-entry",
        ["--export=" + symbol for symbol in ctx.attrs.exports],
        "-z",
        "stack-size={}".format(ctx.attrs.stack_bytes),
        "--initial-memory={}".format(ctx.attrs.memory_bytes),
        "--max-memory={}".format(ctx.attrs.memory_bytes),
        "--strip-debug",
        "-o",
        out.as_output(),
        rt_obj,
        _archives(ctx.label, ctx.attrs.deps),
    )
    ctx.actions.run(link, category = "wasm_link", identifier = ctx.attrs.out)
    return [DefaultInfo(default_output = out)]

wasm_module = rule(
    impl = _wasm_module_impl,
    attrs = {
        "compile_flags": attrs.list(attrs.string()),
        "deps": attrs.list(attrs.transition_dep(cfg = to_wasm32)),
        "exports": attrs.list(attrs.string()),
        "memory_bytes": attrs.int(),
        "out": attrs.string(),
        "stack_bytes": attrs.int(),
        "_cc": attrs.exec_dep(default = "toolchains//:wasm_cc", providers = [RunInfo]),
        "_ld": attrs.exec_dep(default = "toolchains//:wasm_ld", providers = [RunInfo]),
        "_rt": attrs.source(default = "toolchains//:wasm_fsl.c"),
    },
)
