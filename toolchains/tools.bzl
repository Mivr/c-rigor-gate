"""RunInfo wrappers that pin each tool's flags and (minimal) inputs.

Every path the tools use is a projected sub-path of a fetched tree, so an action's inputs
are exactly the files named here and nothing else from the (multi-GB) release.
"""

_TRIPLE = "x86_64-unknown-linux-gnu"

def _tree(dep: Dependency) -> Artifact:
    return dep[DefaultInfo].default_outputs[0]

def _bin_impl(ctx: AnalysisContext) -> list[Provider]:
    """A single LLVM binary (ar, nm, objcopy, cov, ...); no flags, no other inputs."""
    llvm = _tree(ctx.attrs.llvm)
    return [DefaultInfo(), RunInfo(args = cmd_args(llvm.project(ctx.attrs.bin)))]

llvm_bin = rule(
    impl = _bin_impl,
    attrs = {
        "bin": attrs.string(),
        "llvm": attrs.dep(),
    },
)

def _common(ctx: AnalysisContext):
    llvm = _tree(ctx.attrs.llvm)
    sysroot = _tree(ctx.attrs.sysroot)
    return llvm, sysroot

def _cc_impl(ctx: AnalysisContext) -> list[Provider]:
    """clang as a C compiler: no host include directory is searched (-nostdinc)."""
    llvm, sysroot = _common(ctx)
    clang_headers = llvm.project("lib/clang/{}/include".format(ctx.attrs.llvm_major))
    sys_inc = sysroot.project("usr/include")
    args = cmd_args(
        llvm.project("bin/clang-" + ctx.attrs.llvm_major),
        "--target=" + _TRIPLE,
        "-nostdinc",
        "-fdebug-compilation-dir=.",
        "-fcoverage-compilation-dir=.",
        cmd_args(clang_headers, format = "-resource-dir={}", parent = 1),
        "-isystem",
        clang_headers,
        "-isystem",
        cmd_args(sys_inc, format = "{}/x86_64-linux-gnu"),
        "-isystem",
        sys_inc,
        hidden = [clang_headers, sys_inc],
    )
    return [DefaultInfo(), RunInfo(args = args)]

clang_cc = rule(
    impl = _cc_impl,
    attrs = {
        "llvm": attrs.dep(),
        "llvm_major": attrs.string(),
        "sysroot": attrs.dep(),
    },
)

def _ld_impl(ctx: AnalysisContext) -> list[Provider]:
    """clang as the link driver, lld as the linker, sysroot libraries, compiler-rt runtimes."""
    llvm, sysroot = _common(ctx)
    major = ctx.attrs.llvm_major
    rt_dir = "lib/clang/{}/lib/{}".format(major, _TRIPLE)
    runtimes = [llvm.project("{}/{}".format(rt_dir, f)) for f in ctx.attrs.runtimes]
    lld = llvm.project("bin/ld.lld")
    lld_real = llvm.project("bin/lld")
    gcc_dir = sysroot.project("usr/lib/gcc/x86_64-linux-gnu/10")
    sys_libs = [
        sysroot.project("lib"),
        sysroot.project("lib64"),
        sysroot.project("usr/lib/x86_64-linux-gnu"),
    ]
    args = cmd_args(
        llvm.project("bin/clang-" + major),
        "--target=" + _TRIPLE,
        cmd_args(runtimes[0], format = "-resource-dir={}", parent = 3),
        cmd_args(sysroot.project("lib64"), format = "--sysroot={}", parent = 1),
        cmd_args(gcc_dir, format = "--gcc-install-dir={}"),
        "-fuse-ld=lld",
        cmd_args(lld, format = "--ld-path={}"),
        "-rtlib=libgcc",
        "-unwindlib=libgcc",
        hidden = [lld, lld_real, gcc_dir] + sys_libs + runtimes,
    )
    return [DefaultInfo(), RunInfo(args = args)]

clang_ld = rule(
    impl = _ld_impl,
    attrs = {
        "llvm": attrs.dep(),
        "llvm_major": attrs.string(),
        "runtimes": attrs.list(attrs.string()),
        "sysroot": attrs.dep(),
    },
)

def _roots_impl(ctx: AnalysisContext) -> list[Provider]:
    """`--system-root <dir>` for the toolchain's own header directories (strings only: the
    trees are not inputs). Text from a file below one of them is not the product's."""
    llvm, sysroot = _common(ctx)
    args = cmd_args(
        "--system-root",
        llvm.project("lib/clang/{}/include".format(ctx.attrs.llvm_major)),
        "--system-root",
        sysroot.project("usr/include"),
        ignore_artifacts = True,
    )
    return [DefaultInfo(), RunInfo(args = args)]

system_roots = rule(
    impl = _roots_impl,
    attrs = {
        "llvm": attrs.dep(),
        "llvm_major": attrs.string(),
        "sysroot": attrs.dep(),
    },
)

def _libc_impl(ctx: AnalysisContext) -> list[Provider]:
    """Every symbol the pinned glibc's shared libraries export (what a product must not redefine)."""
    sysroot = _tree(ctx.attrs.sysroot)
    libs = [sysroot.project("lib/x86_64-linux-gnu/" + name) for name in ctx.attrs.libs]
    out = ctx.actions.declare_output("libc.symbols")
    script = ctx.actions.write(
        "run.sh",
        [
            "set -eu",
            'nm="$1"; out="$2"; shift 2',
            '{ for lib in "$@"; do "$nm" -D --defined-only --just-symbol-name "$lib"; done; } | sed -e "s/@.*//" -e "/^$/d" | LC_ALL=C sort -u > "$out"',
            '[ -s "$out" ] || { echo "libc_symbols: empty" >&2; exit 1; }',
        ],
        is_executable = True,
    )
    ctx.actions.run(cmd_args("/bin/sh", script, ctx.attrs._nm[RunInfo], out.as_output(), libs), category = "libc_symbols")
    return [DefaultInfo(default_output = out)]

libc_symbols = rule(
    impl = _libc_impl,
    attrs = {
        "libs": attrs.list(attrs.string()),
        "sysroot": attrs.dep(),
        "_nm": attrs.exec_dep(default = "toolchains//:llvm-nm", providers = [RunInfo]),
    },
)

# ---------------------------------------------------------------------------
# WebAssembly (wasm32-unknown-unknown, freestanding; docs/toolchain.md "WebAssembly (wasm32)"). The pinned LLVM's own
# clang (it has the WebAssembly backend) and its multi-call `lld` as `lld -flavor wasm`. No sysroot and no libc: the
# include path is clang's builtin headers and the gate's `toolchains/wasm/include` (only <string.h>).
# ---------------------------------------------------------------------------

_WASM_TRIPLE = "wasm32-unknown-unknown"

def _wasm_cc_impl(ctx: AnalysisContext) -> list[Provider]:
    """clang as a freestanding wasm32 C compiler: -nostdinc, then exactly the two header directories."""
    llvm = _tree(ctx.attrs.llvm)
    clang_headers = llvm.project("lib/clang/{}/include".format(ctx.attrs.llvm_major))
    gate_headers = cmd_args(ctx.attrs.string_h, parent = 1)
    args = cmd_args(
        llvm.project("bin/clang-" + ctx.attrs.llvm_major),
        "--target=" + _WASM_TRIPLE,
        "-nostdinc",
        "-ffreestanding",
        "-nostdlib",
        "-fdebug-compilation-dir=.",
        "-fcoverage-compilation-dir=.",
        cmd_args(clang_headers, format = "-resource-dir={}", parent = 1),
        "-isystem",
        clang_headers,
        "-isystem",
        gate_headers,
        hidden = [clang_headers, ctx.attrs.string_h],
    )
    return [DefaultInfo(), RunInfo(args = args)]

wasm_cc = rule(
    impl = _wasm_cc_impl,
    attrs = {
        "llvm": attrs.dep(),
        "llvm_major": attrs.string(),
        # The gate's freestanding <string.h>; its directory is the second (and last) -isystem directory.
        "string_h": attrs.source(),
    },
)

def _wasm_ld_impl(ctx: AnalysisContext) -> list[Provider]:
    """The pinned multi-call lld as the WebAssembly linker (`lld -flavor wasm`, i.e. wasm-ld)."""
    llvm = _tree(ctx.attrs.llvm)
    return [DefaultInfo(), RunInfo(args = cmd_args(llvm.project("bin/lld"), "-flavor", "wasm"))]

wasm_ld = rule(
    impl = _wasm_ld_impl,
    attrs = {
        "llvm": attrs.dep(),
    },
)
