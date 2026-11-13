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
# Android NDK (aarch64-linux-android, one API level). The tree is `fetched_zip_tree`; `ndk_dir` is the
# prebuilt llvm directory inside it. Like the Linux tools, every path is a projected sub-path, so an action's
# inputs are exactly the files named here.
# ---------------------------------------------------------------------------

def _ndk_triple(api: str) -> str:
    return "aarch64-linux-android" + api

def _ndk_cc_impl(ctx: AnalysisContext) -> list[Provider]:
    """NDK clang as a C compiler: no host include directory is searched (-nostdinc)."""
    ndk = _tree(ctx.attrs.ndk).project(ctx.attrs.ndk_dir.rstrip("/"))
    clang_headers = ndk.project("lib/clang/{}/include".format(ctx.attrs.llvm_major))
    sys_inc = ndk.project("sysroot/usr/include")
    args = cmd_args(
        ndk.project("bin/clang-" + ctx.attrs.llvm_major),
        "--target=" + _ndk_triple(ctx.attrs.api),
        "-nostdinc",
        "-fdebug-compilation-dir=.",
        "-fcoverage-compilation-dir=.",
        cmd_args(clang_headers, format = "-resource-dir={}", parent = 1),
        "-isystem",
        clang_headers,
        "-isystem",
        cmd_args(sys_inc, format = "{}/aarch64-linux-android"),
        "-isystem",
        sys_inc,
        "-fPIC",
        hidden = [clang_headers, sys_inc],
    )
    return [DefaultInfo(), RunInfo(args = args)]

ndk_cc = rule(
    impl = _ndk_cc_impl,
    attrs = {
        "api": attrs.string(),
        "llvm_major": attrs.string(),
        "ndk": attrs.dep(),
        "ndk_dir": attrs.string(),
    },
)

def _ndk_ld_impl(ctx: AnalysisContext) -> list[Provider]:
    """NDK clang as the link driver, lld as the linker, bionic stubs, compiler-rt builtins. 16 KB pages."""
    ndk = _tree(ctx.attrs.ndk).project(ctx.attrs.ndk_dir.rstrip("/"))
    major = ctx.attrs.llvm_major
    runtimes = [ndk.project(r) for r in ctx.attrs.runtimes]
    lld = ndk.project("bin/ld.lld")
    lld_real = ndk.project("bin/lld")
    sysroot = ndk.project("sysroot")
    args = cmd_args(
        ndk.project("bin/clang-" + major),
        "--target=" + _ndk_triple(ctx.attrs.api),
        cmd_args(ndk.project("lib/clang/" + major), format = "-resource-dir={}"),
        cmd_args(sysroot, format = "--sysroot={}"),
        "-fuse-ld=lld",
        cmd_args(lld, format = "--ld-path={}"),
        "-rtlib=compiler-rt",
        "-unwindlib=libunwind",
        "-Wl,-z,max-page-size=16384",
        "-Wl,-z,common-page-size=16384",
        hidden = [lld, lld_real, sysroot] + runtimes,
    )
    return [DefaultInfo(), RunInfo(args = args)]

ndk_ld = rule(
    impl = _ndk_ld_impl,
    attrs = {
        "api": attrs.string(),
        "llvm_major": attrs.string(),
        "ndk": attrs.dep(),
        "ndk_dir": attrs.string(),
        "runtimes": attrs.list(attrs.string()),
    },
)
