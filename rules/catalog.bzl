"""`c_catalog_gen`: gettext `.pot`/`.po` files -> the C source and header of a const message catalog (T105).

One Buck2 action runs the gate-owned, stdlib-only `gate/rigor_lib/po2c.py` (`python3 -I -B`, like the fact
scanner). Its output is a pure function of the inputs. The generated files live in buck-out only; the macro
`c_catalog` (rules/c.bzl) compiles them as a `c_library`. Every bad translation is a build error of this action.
"""

def _catalog_impl(ctx: AnalysisContext) -> list[Provider]:
    header = ctx.actions.declare_output(ctx.attrs.stem + ".h")
    source = ctx.actions.declare_output(ctx.attrs.stem + ".c")
    cmd = cmd_args(
        "/usr/bin/env",
        "python3",
        "-I",
        "-B",
        ctx.attrs._po2c,
        "--symbol",
        ctx.attrs.symbol,
        "--langs",
        ",".join(ctx.attrs.langs),
        "--source-lang",
        ctx.attrs.source_lang,
        "--header",
        ctx.attrs.header,
        "--runtime-header",
        ctx.attrs.runtime_header,
    )
    for pot in ctx.attrs.pots:
        cmd.add("--pot", pot)
    for lang in sorted(ctx.attrs.po.keys()):
        for po in ctx.attrs.po[lang]:
            cmd.add("--po", lang, po)
    for msgid in sorted(ctx.attrs.names.keys()):
        cmd.add("--name", msgid, ctx.attrs.names[msgid])
    cmd.add("--out-h", header.as_output(), "--out-c", source.as_output())
    ctx.actions.run(cmd, category = "po2c")
    return [DefaultInfo(
        default_output = source,
        sub_targets = {
            "c": [DefaultInfo(default_output = source)],
            "h": [DefaultInfo(default_output = header)],
        },
    )]

c_catalog_gen = rule(
    impl = _catalog_impl,
    attrs = {
        "header": attrs.string(),
        "langs": attrs.list(attrs.string()),
        "names": attrs.dict(attrs.string(), attrs.string(), default = {}),
        "po": attrs.dict(attrs.string(), attrs.list(attrs.source())),
        "pots": attrs.list(attrs.source()),
        "runtime_header": attrs.string(),
        "source_lang": attrs.string(),
        "stem": attrs.string(),
        "symbol": attrs.string(),
        "_po2c": attrs.source(default = "gate//gate/rigor_lib:po2c.py"),
    },
)
