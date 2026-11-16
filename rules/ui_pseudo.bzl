"""`c_catalog_pseudo`: the pseudo-locale `.po` files of a catalogue (U17a, docs/ui-pseudo.md).

NOT BUILT BY ANY SELFTEST YET: it was built once by hand (U17a) and nothing automated covers it. Building a catalogue
that includes the pseudo language through `c_catalog`, and a check that the pseudo language never reaches a shipped
binary, belong to U17b.

One Buck2 action runs the gate-owned, stdlib-only `gate/rigor_lib/ui_pseudo.py` (`python3 -I -B`, with the package
`rigor_lib` beside it: it imports `po2c` and the UI contract loader). `contract` is the product's UI contract file;
the overall expansion floor is read from it (`thresholds.pseudo_expansion_overall_pct`), a pending or missing value
fails the action. The output is one `.po` per `.pot`, a pure function of the inputs, in buck-out only. Sub-targets:
`[<stem of the pot>]` is that pot's pseudo `.po`.
"""

def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]

_RUN = "import sys; sys.path.insert(0, sys.argv[1]); from rigor_lib import ui_pseudo; sys.exit(ui_pseudo.main(sys.argv[2:]))"

def _pseudo_impl(ctx: AnalysisContext) -> list[Provider]:
    lib = ctx.actions.symlinked_dir("lib", {"rigor_lib": ctx.attrs._rigor_lib})
    cmd = cmd_args(
        "/usr/bin/env",
        "python3",
        "-I",
        "-B",
        "-c",
        _RUN,
        lib,
        "--source-lang",
        ctx.attrs.source_lang,
        "--lang",
        ctx.attrs.lang,
        "--contract",
        ctx.attrs.contract,
    )
    outputs = {}
    for pot in ctx.attrs.pots:
        stem = _basename(pot.short_path).removesuffix(".pot")
        if stem in outputs:
            fail("c_catalog_pseudo: two pots are named {}.pot".format(stem))
        outputs[stem] = ctx.actions.declare_output(stem + "." + ctx.attrs.lang + ".po")
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
        "contract": attrs.source(),
        "lang": attrs.string(default = "xx"),
        "po": attrs.dict(attrs.string(), attrs.list(attrs.source())),
        "pots": attrs.list(attrs.source()),
        "source_lang": attrs.string(),
        "_rigor_lib": attrs.source(default = "gate//gate/rigor_lib:pkg"),
    },
)
