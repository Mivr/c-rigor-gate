"""`toolchains//:cxx`: the C/C++ toolchain of the target platform (wasm32, Android NDK or Linux)."""

def _cxx_select_impl(ctx: AnalysisContext) -> list[Provider]:
    if ctx.attrs.use_wasm:
        return ctx.attrs.wasm.providers
    chosen = ctx.attrs.android if ctx.attrs.use_android else ctx.attrs.host
    return chosen.providers

cxx_select = rule(
    impl = _cxx_select_impl,
    attrs = {
        "android": attrs.toolchain_dep(),
        "host": attrs.toolchain_dep(),
        "use_android": attrs.bool(),
        "use_wasm": attrs.bool(),
        "wasm": attrs.toolchain_dep(),
    },
    is_toolchain_rule = True,
)
