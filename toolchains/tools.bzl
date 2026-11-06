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
