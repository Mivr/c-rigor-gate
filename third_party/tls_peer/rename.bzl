"""A private, renamed copy of a library archive (see rename.py)."""

def _impl(ctx: AnalysisContext) -> list[Provider]:
    symbols = ctx.attrs.symbols[DefaultInfo].default_outputs[0]
    archive = ctx.attrs.lib[DefaultInfo].default_outputs[0]
    mapping = ctx.actions.declare_output("rename.map")
    header = ctx.actions.declare_output("srv_rename.h")
    ctx.actions.run(
        cmd_args("/usr/bin/env", "python3", "-I", "-B", ctx.attrs._script, symbols, mapping.as_output(), header.as_output()),
        category = "srv_rename_map",
    )
    out = ctx.actions.declare_output("libsrv.a")
    ctx.actions.run(
        cmd_args(ctx.attrs._objcopy[RunInfo], cmd_args(mapping, format = "--redefine-syms={}"), archive, out.as_output()),
        category = "srv_rename",
    )
    return [DefaultInfo(default_output = out, sub_targets = {"header": [DefaultInfo(default_output = header)]})]

srv_rename = rule(
    impl = _impl,
    attrs = {
        "lib": attrs.dep(),
        "symbols": attrs.dep(),
        "_objcopy": attrs.exec_dep(default = "toolchains//:llvm-objcopy", providers = [RunInfo]),
        "_script": attrs.source(default = "gate//third_party/tls_peer:rename.py"),
    },
)
