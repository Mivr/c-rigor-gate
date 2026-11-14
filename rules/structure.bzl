"""`c_structure`: the structure facts of one C module (T011), one cacheable Buck2 action per source.

For every source of the module, `structure_scan.py unit` runs the pinned clang with the module's exact compile
command (the argsfile Buck2 itself uses) and `-Xclang -ast-dump=json -fsyntax-only -H`, and reduces the JSON
AST to facts: functions with their extents, parameters, nesting, cyclomatic count and calls; files with their
line counts. One more action joins the units into `structure.json`. The file is data; `rigor structure` decides.

Headers of the gate's own third-party libraries (`buck-out/<version>/art/<gate cell>/third_party/`, T133) and of the toolchain are not the
product's: neither their files nor their functions are reported.

Only the source being scanned and the module's headers are inputs of its action, as in the real compile, so an
`#include` of another `.c` file fails here exactly as it fails in the real build.

    c_structure(name = "core_structure", module = ":core", srcs = ["core.c"], headers = ["core.h"],
                deps = [":json"], kind = "c_library")

`srcs` and `headers` must be the module's own lists; `srcs` is checked against the objects the module
compiles (a missing or extra source fails the build). The macros of rules/c.bzl do not define this target yet:
the grading driver writes it in a gate-owned package, as it does for `c_mutants`.
"""

load("@prelude//cxx:cxx_toolchain_types.bzl", "CxxToolchainInfo")

def _label_text(label: Label, name: str = "") -> str:
    cell = "" if label.cell == "root" else label.cell
    return "{}//{}:{}".format(cell, label.package, name if name else label.name)

def _objects(dep: Dependency, pic: bool = False) -> dict[str, Artifact]:
    """The plain objects of a library; a shared object (`pic`) only has the position-independent ones, named as plain."""
    subs = dep[DefaultInfo].sub_targets
    if "objects" not in subs:
        fail("{}: no [objects] sub-target".format(dep.label))
    every = subs["objects"][DefaultInfo].sub_targets
    if pic:
        return {name[:-len(".pic.o")] + ".o": unit[DefaultInfo].default_outputs[0] for name, unit in every.items() if name.endswith(".pic.o")}
    return {name: unit[DefaultInfo].default_outputs[0] for name, unit in every.items() if not name.endswith(".pic.o")}

def _compile_prefix(ctx, headers, toolchain):
    info = ctx.attrs.module[DefaultInfo].sub_targets["argsfiles"][DefaultInfo]
    argsfile = None
    for item in info.other_outputs:
        if type(item) == "Artifact" and item.basename.endswith(".cxx_compile_argsfile") and (ctx.attrs.pic or ".pic." not in item.basename):
            argsfile = item
    if argsfile == None:
        fail("{}: no compile argsfile found".format(ctx.attrs.module.label))
    return cmd_args(
        toolchain.c_compiler_info.compiler,
        cmd_args(argsfile, format = "@{}"),
        [cmd_args("-iquote", cmd_args(f, parent = 1)) for f in headers],
        hidden = info.other_outputs + headers,
    )

def _python(script):
    return cmd_args("/usr/bin/env", "python3", "-I", "-B", script)

def _structure_impl(ctx: AnalysisContext) -> list[Provider]:
    srcs = sorted(ctx.attrs.srcs, key = lambda s: s.short_path)
    if len(srcs) == 0:
        fail("{}: the module has no sources".format(ctx.label))
    objects = _objects(ctx.attrs.module, ctx.attrs.pic)
    wanted = sorted([s.short_path + ".o" for s in srcs])
    if sorted(objects.keys()) != wanted:
        fail("{}: srcs {} do not match the objects the module compiles {}".format(ctx.label, wanted, sorted(objects.keys())))
    toolchain = ctx.attrs._toolchain[CxxToolchainInfo]
    prefix = _compile_prefix(ctx, ctx.attrs.headers, toolchain)
    label = _label_text(ctx.attrs.module.label, ctx.attrs.facts_name)
    package = ctx.attrs.module.label.package
    units = []
    for src in srcs:
        out = ctx.actions.declare_output("unit/{}.json".format(src.short_path))
        ctx.actions.run(
            cmd_args(
                _python(ctx.attrs._scanner),
                "unit",
                "--label",
                label,
                "--src",
                src,
                "--out",
                out.as_output(),
                ctx.attrs._roots[RunInfo],
                "--vendor-marker",
                "/art/{}/third_party/".format(ctx.attrs._ctest.label.cell),
                "--",
                prefix,
            ),
            category = "c_structure_unit",
            identifier = src.short_path,
        )
        units.append(out)
    result = ctx.actions.declare_output("structure.json")
    join = cmd_args(
        _python(ctx.attrs._scanner),
        "combine",
        "--label",
        label,
        "--kind",
        ctx.attrs.kind,
        "--out",
        result.as_output(),
    )
    for dep in ctx.attrs.deps:
        join.add("--dep", _label_text(dep.label))
    for src in srcs:
        join.add("--src", package + "/" + src.short_path)
    join.add(units)
    ctx.actions.run(join, category = "c_structure")
    return [DefaultInfo(default_output = result)]

_ATTRS = {
    "deps": attrs.list(attrs.dep(), default = []),
    "facts_name": attrs.string(default = ""),
    "headers": attrs.list(attrs.source(), default = []),
    "kind": attrs.string(),
    "module": attrs.dep(),
    "pic": attrs.bool(default = False),
    "srcs": attrs.list(attrs.source()),
    "_ctest": attrs.dep(default = "gate//ctest:ctest"),
    "_roots": attrs.exec_dep(default = "toolchains//:system-roots", providers = [RunInfo]),
    "_scanner": attrs.source(default = "gate//gate/rigor_lib:structure_scan.py"),
    "_toolchain": attrs.toolchain_dep(default = "toolchains//:cxx", providers = [CxxToolchainInfo]),
}

c_structure_rule = rule(impl = _structure_impl, attrs = _ATTRS)

# The Android twin (a `c_android_so`): the NDK's clang (the `cxx` toolchain of the android mode), the NDK's header
# directories as the system roots, and the position-independent objects a shared object has.
_ANDROID_ATTRS = dict(_ATTRS)
_ANDROID_ATTRS["pic"] = attrs.bool(default = True)
_ANDROID_ATTRS["_roots"] = attrs.exec_dep(default = "toolchains//:ndk-system-roots", providers = [RunInfo])

c_android_structure_rule = rule(impl = _structure_impl, attrs = _ANDROID_ATTRS)

def c_structure(name, module, srcs, headers = [], deps = [], kind = "c_library", facts_name = ""):
    """Structure facts of `module` (a c_library, c_binary, c_test, c_fuzz or c_sim target); release mode only.

    `module`, `srcs` and `headers` may live in another package than the target (the grading driver's
    generated package); `facts_name` is the name the module is known by when it is not the target's
    (a `c_fuzz` reads a `<name>__facts_unit` library but is `<name>`)."""
    if kind not in ["c_library", "c_binary", "c_test", "c_fuzz", "c_sim"]:
        fail("c_structure: bad kind {!r}".format(kind))
    c_structure_rule(
        name = name,
        module = module,
        srcs = srcs,
        headers = headers,
        deps = deps,
        kind = kind,
        facts_name = facts_name,
        target_compatible_with = ["toolchains//:release"],
    )

def c_android_structure(name, module, srcs, headers = [], deps = [], facts_name = ""):
    """Structure facts of a `c_android_so` (its `<name>__lib` unit); android mode only."""
    c_android_structure_rule(
        name = name,
        module = module,
        srcs = srcs,
        headers = headers,
        deps = deps,
        kind = "c_android_so",
        facts_name = facts_name,
        target_compatible_with = ["toolchains//:android"],
    )
