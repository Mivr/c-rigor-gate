"""`c_android_so` support: the version script and the checked shared object (see `c_android_so` in rules/c.bzl)."""

def _script_impl(ctx: AnalysisContext) -> list[Provider]:
    """A GNU version script: exactly `symbols` are global, every other symbol is local."""
    out = ctx.actions.declare_output("exports.map")
    lines = ["{", "  global:"] + ["    {};".format(s) for s in ctx.attrs.symbols] + ["  local:", "    *;", "};"]
    ctx.actions.write(out, lines)
    return [DefaultInfo(default_output = out)]

android_version_script = rule(
    impl = _script_impl,
    attrs = {"symbols": attrs.list(attrs.string())},
)

def _so_impl(ctx: AnalysisContext) -> list[Provider]:
    """`lib<name>.so`: the linked shared object, copied out only if elf_check.py accepts it."""
    lib = ctx.attrs.lib[DefaultInfo].sub_targets["shared"][DefaultInfo].default_outputs[0]
    out = ctx.actions.declare_output("lib{}.so".format(ctx.attrs.soname))
    cmd = cmd_args("/usr/bin/env", "python3", "-I", "-B", ctx.attrs._check, "--page-size", str(ctx.attrs.page_size))
    for symbol in ctx.attrs.exports:
        cmd.add("--export", symbol)
    cmd.add(lib, out.as_output())
    ctx.actions.run(cmd, category = "android_so_check", identifier = ctx.attrs.soname)
    return [DefaultInfo(default_output = out)]

android_so = rule(
    impl = _so_impl,
    attrs = {
        "exports": attrs.list(attrs.string()),
        "lib": attrs.dep(),
        "page_size": attrs.int(),
        "soname": attrs.string(),
        "_check": attrs.source(default = "gate//rules:elf_check.py"),
    },
)
