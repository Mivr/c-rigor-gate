"""`toolchains//:cxx`: the C/C++ toolchain of the target platform (wasm32 or Linux).

A reduced form of the gate main's selector (which also chooses the Android NDK toolchain): this product line has no
Android mode, so only the wasm32 cpu switches the toolchain.
"""

def _cxx_select_impl(ctx: AnalysisContext) -> list[Provider]:
    chosen = ctx.attrs.wasm if ctx.attrs.use_wasm else ctx.attrs.host
    return chosen.providers

cxx_select = rule(
    impl = _cxx_select_impl,
    attrs = {
        "host": attrs.toolchain_dep(),
        "use_wasm": attrs.bool(),
        "wasm": attrs.toolchain_dep(),
    },
    is_toolchain_rule = True,
)
