"""`c_catalog_pseudo`: the pseudo-locale `.po` files of a catalogue (U17a, docs/ui-pseudo.md).

One Buck2 action runs the gate-owned, stdlib-only `gate/rigor_lib/ui_pseudo.py` (`python3 -I -B`, with `po2c.py`
next to it: the generator refuses what `po2c` refuses). The output is one `.po` per `.pot`, a pure function of the
inputs, in buck-out only. Sub-targets: `[<stem of the pot>]` is that pot's pseudo `.po` (a source of `c_catalog_gen`).

The pseudo language is for the probe only. It is kept out of the shipped binary by construction: the shipped
`c_catalog` lists `langs = [source, ...real]` and never names this target; the probe's catalogue is a second
`c_catalog_gen` over the same pots whose `langs` also hold `xx`, and only the probe links it.
"""

def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]

def _pseudo_impl(ctx: AnalysisContext) -> list[Provider]:
    tools = ctx.actions.symlinked_dir("tools", {
        "po2c.py": ctx.attrs._po2c,
        "ui_pseudo.py": ctx.attrs._ui_pseudo,
    })
    cmd = cmd_args(
        "/usr/bin/env",
        "python3",
        "-I",
        "-B",
        cmd_args(tools, format = "{}/ui_pseudo.py"),
        "--source-lang",
        ctx.attrs.source_lang,
        "--lang",
        ctx.attrs.lang,
        hidden = [tools],
    )
    if ctx.attrs.overall_pct >= 0:
        cmd.add("--overall-pct", str(ctx.attrs.overall_pct))
    if ctx.attrs.extended:
        cmd.add("--extended")
    outputs = {}
    for pot in ctx.attrs.pots:
        stem = _basename(pot.short_path).removesuffix(".pot")
        if stem in outputs:
            fail("c_catalog_pseudo: two pots are named {}.pot".format(stem))
        out = ctx.actions.declare_output(stem + "." + ctx.attrs.lang + ".po")
        outputs[stem] = out
        cmd.add("--pot", pot)
    for lang in sorted(ctx.attrs.po.keys()):
        for po in ctx.attrs.po[lang]:
            cmd.add("--po", lang, po)
    for out in outputs.values():
        cmd.add("--out", out.as_output())
    ctx.actions.run(cmd, category = "ui_pseudo")
    return [DefaultInfo(
        default_outputs = list(outputs.values()),
        sub_targets = {stem: [DefaultInfo(default_output = out)] for stem, out in outputs.items()},
    )]

c_catalog_pseudo = rule(
    impl = _pseudo_impl,
    attrs = {
        "extended": attrs.bool(default = False),
        "lang": attrs.string(default = "xx"),
        "overall_pct": attrs.int(default = -1),
        "po": attrs.dict(attrs.string(), attrs.list(attrs.source())),
        "pots": attrs.list(attrs.source()),
        "source_lang": attrs.string(),
        "_po2c": attrs.source(default = "gate//gate/rigor_lib:po2c.py"),
        "_ui_pseudo": attrs.source(default = "gate//gate/rigor_lib:ui_pseudo.py"),
    },
)
