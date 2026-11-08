"""`c_embed_gen`: one binary file -> the C source and header of a const byte array (T112).

One Buck2 action runs the gate-owned, stdlib-only `gate/rigor_lib/bin2c.py` (`python3 -I -B`, like the catalog
generator). Its output is a pure function of the inputs. The generated files live in buck-out only; the macro
`c_embed` (rules/c.bzl) compiles them as a `c_library`. Every bad input is a build error of this action.
"""

def _embed_impl(ctx: AnalysisContext) -> list[Provider]:
    header = ctx.actions.declare_output(ctx.attrs.stem + ".h")
    source = ctx.actions.declare_output(ctx.attrs.stem + ".c")
    cmd = cmd_args(
        "/usr/bin/env",
        "python3",
        "-I",
        "-B",
        ctx.attrs._bin2c,
        "--symbol",
        ctx.attrs.symbol,
        "--max-bytes",
        str(ctx.attrs.max_bytes),
        "--header",
        ctx.attrs.header,
        "--src",
        ctx.attrs.src,
        "--out-h",
        header.as_output(),
        "--out-c",
        source.as_output(),
    )
    if ctx.attrs.nul:
        cmd.add("--nul")
    ctx.actions.run(cmd, category = "bin2c")
    return [DefaultInfo(
        default_output = source,
        sub_targets = {
            "c": [DefaultInfo(default_output = source)],
            "h": [DefaultInfo(default_output = header)],
        },
    )]

c_embed_gen = rule(
    impl = _embed_impl,
    attrs = {
        "header": attrs.string(),
        "max_bytes": attrs.int(),
        "nul": attrs.bool(default = False),
        "src": attrs.source(),
        "stem": attrs.string(),
        "symbol": attrs.string(),
        "_bin2c": attrs.source(default = "gate//gate/rigor_lib:bin2c.py"),
    },
)
