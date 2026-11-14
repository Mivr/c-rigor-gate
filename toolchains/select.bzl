"""`toolchains//:cxx`: the C/C++ toolchain of the target platform's mode (Android NDK or Linux)."""

def _cxx_select_impl(ctx: AnalysisContext) -> list[Provider]:
    chosen = ctx.attrs.android if ctx.attrs.use_android else ctx.attrs.host
    return chosen.providers

cxx_select = rule(
    impl = _cxx_select_impl,
    attrs = {
        "android": attrs.toolchain_dep(),
        "host": attrs.toolchain_dep(),
        "use_android": attrs.bool(),
    },
    is_toolchain_rule = True,
)
