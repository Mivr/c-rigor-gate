"""The test PKI of the TLS test peer as one generated C header (see embed_pki.py)."""

def _impl(ctx: AnalysisContext) -> list[Provider]:
    out = ctx.actions.declare_output("tls_peer_pki.h")
    cmd = cmd_args("/usr/bin/env", "python3", "-I", "-B", ctx.attrs._script, out.as_output())
    for src in ctx.attrs.pems:
        cmd.add(src)
    ctx.actions.run(cmd, category = "tls_peer_pki")
    return [DefaultInfo(default_output = out)]

tls_peer_pki = rule(
    impl = _impl,
    attrs = {
        "pems": attrs.list(attrs.source()),
        "_script": attrs.source(default = "gate//third_party/tls_peer:embed_pki.py"),
    },
)
