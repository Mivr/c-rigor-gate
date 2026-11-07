"""C17 rules for the gate. The only way a product builds C.

The macros take no flag arguments of any kind. Mode flags are chosen by the target
platform's mode constraint; the sealed warning profile is appended last.
"""



load("@gate//rules:cov.bzl", "cov_report")
load("@gate//rules:ctest.bzl", "ctest_results", "fuzz_run")
load("@gate//rules:facts.bzl", "c_facts", "c_san_facts")
load("@gate//rules:mutate.bzl", "c_mutants_rule", "mutsrc")
load("@gate//rules:perf.bzl", "PERF_WRAPS", "perf_results")

_SEALED = [
    "-std=c17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-Wconversion",
    "-Wsign-conversion",
    "-Wshadow",
    "-Wcast-qual",
    "-Wvla",
    # clang has no -Wstack-usage (a GCC flag); -Wframe-larger-than is its equivalent.
    "-Wframe-larger-than=512",
    "-Wformat=2",
    "-Wnull-dereference",
    "-Wimplicit-fallthrough",
] + [
    # Belt and braces for the builtins the semantic gate never allows (T014): a call does not
    # compile ("use of undeclared identifier 'c_rigor_gate_bans_...'"). Function-like and
    # self-referential, so a toolchain header that only names them in a macro is unaffected and the
    # preprocessed text keeps the builtin's own name for the scan. `#undef` defeats it; the semantic
    # gate reports that (`reserved-macro`) and the use (`banned-builtin`/`forbidden-builtin`).
    "-D{0}(...)={0}(c_rigor_gate_bans_{0})".format(b)
    for b in [
        "__builtin_alloca",
        "__builtin_alloca_uninitialized",
        "__builtin_alloca_with_align",
        "__builtin_alloca_with_align_uninitialized",
        "__builtin_frame_address",
        "__builtin_return_address",
    ]
]

_SAN = "-fsanitize=address,undefined,leak"
_FUZZ = "-fsanitize=fuzzer,address,undefined"

_COMPILE_BY_MODE = {
    "toolchains//:release": ["-O2"],
    "toolchains//:san": ["-O1", "-g", _SAN, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:cov": ["-fprofile-instr-generate", "-fcoverage-mapping", "-fcoverage-mcdc"],
    "toolchains//:fuzz": ["-O1", "-g", _FUZZ, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
}

_LINK_BY_MODE = {
    "toolchains//:release": [],
    "toolchains//:san": [_SAN],
    "toolchains//:cov": ["-fprofile-instr-generate"],
    "toolchains//:fuzz": [_FUZZ],
}

def _compile_flags():
    return select(_COMPILE_BY_MODE) + _SEALED

def _link_flags():
    return select(_LINK_BY_MODE)

# Fuzz mode links libFuzzer's main(); ordinary binaries/tests are not built there, and
# fuzz targets are not built in the other modes.
_ONLY_FUZZ = ["toolchains//:fuzz"]
_NOT_IN_FUZZ = select({
    "toolchains//:fuzz": ["toolchains//:never"],
    "DEFAULT": [],
})

def _plain_files(macro, attr, items, suffix):
    # Plain file names only: a ("a.c", ["-Wno-error"]) tuple would carry per-file flags that
    # come after the sealed profile, and a dict or a target label could smuggle in more.
    if type(items) != "list":
        fail("{}: `{}` must be a list of plain file names, got {}".format(macro, attr, type(items)))
    for item in items:
        if type(item) != "string":
            fail("{}: `{}` entries must be plain strings, got {}: {}".format(macro, attr, type(item), item))
        if not item.endswith(suffix) or ":" in item or item.startswith("//") or item.startswith("@"):
            fail("{}: `{}` entries must be plain file names ending in {}, got {!r}".format(macro, attr, suffix, item))

def _check(macro, srcs, headers):
    _plain_files(macro, "srcs", srcs, ".c")
    _plain_files(macro, "headers", headers, ".h")

# `<name>_facts` is built in the release mode, `<name>_facts_san` in the san mode: the preprocessed
# text and the symbols of that mode's objects (see rules/facts.bzl). `unit` is the target whose compile
# actions are read. `rigor facts --modes` compares the two (T023).
_RELEASE_ONLY = ["toolchains//:release"]
_SAN_ONLY = ["toolchains//:san"]

_RELEASE_OR_SAN = select({
    "toolchains//:release": [],
    "toolchains//:san": [],
    "DEFAULT": ["toolchains//:never"],
})

def _facts(name, kind, srcs, deps, unit = None):
    for suffix, mode, rule in (("_facts", _RELEASE_ONLY, c_facts), ("_facts_san", _SAN_ONLY, c_san_facts)):
        rule(
            name = name + suffix,
            unit = unit if unit else ":" + name,
            facts_name = name,
            kind = kind,
            srcs = srcs,
            facts_deps = deps,
            target_compatible_with = mode,
        )

def c_library(name, srcs = [], headers = [], deps = [], visibility = []):
    _check("c_library", srcs, headers)
    native.cxx_library(
        name = name,
        srcs = srcs,
        exported_headers = headers,
        deps = deps,
        visibility = visibility,
        compiler_flags = _compile_flags(),
        link_style = "static",
    )
    _facts(name, "c_library", srcs, deps)

    # What `c_mutants` needs to know about this module: its source files.
    mutsrc(name = name + "_mutsrc", srcs = srcs, headers = headers, visibility = ["PUBLIC"])

def c_binary(name, srcs = [], deps = []):
    _check("c_binary", srcs, [])
    native.cxx_binary(
        name = name,
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _NOT_IN_FUZZ,
    )
    _facts(name, "c_binary", srcs, deps)

# `<name>_results` is built in release and san only (cov and fuzz do not produce verdicts).

def c_test(name, srcs = [], deps = []):
    _check("c_test", srcs, [])
    native.cxx_test(
        name = name,
        srcs = srcs,
        deps = deps + ["gate//ctest:ctest"],
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _NOT_IN_FUZZ,
    )

    _facts(name, "c_test", srcs, deps + ["gate//ctest:ctest"])

    # `<name>_results`: the ctest JSON Lines, produced on RE as a cacheable artifact.
    ctest_results(
        name = name + "_results",
        test = ":" + name,
        target_compatible_with = _RELEASE_OR_SAN,
    )

    # `<name>_coverage` renders the line/branch/MC-DC report; only built in the cov mode.
    cov_report(
        name = name + "_coverage",
        test = ":" + name,
        target_compatible_with = ["toolchains//:cov"],
    )

def c_perf(name, module, srcs = [], deps = [], sizes = [1000, 4000], seed = 1):
    """Cost counts of `module` at the given input sizes (release mode only): `<name>_perf` -> perf.jsonl.

    `srcs` are the gate-held generator and driver (perf_gen, perf_run; see ctest/perf.h). The sizes
    and the seed are attributes, never read from the environment.
    """
    _check("c_perf", srcs, [])
    if type(module) != "string" or ":" not in module:
        fail("c_perf: `module` must be a target label string, got {!r}".format(module))
    if type(sizes) != "list" or len(sizes) < 2 or len(sizes) > 8:
        fail("c_perf: `sizes` must be a list of 2 to 8 positive ints, got {!r}".format(sizes))
    for n in sizes:
        if type(n) != "int" or n < 1:
            fail("c_perf: `sizes` entries must be positive ints, got {!r}".format(n))
    if type(seed) != "int" or seed < 0:
        fail("c_perf: `seed` must be a non-negative int, got {!r}".format(seed))
    native.cxx_binary(
        name = name,
        srcs = srcs,
        deps = [module] + deps + ["gate//ctest:perf"],
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags() + ["-Wl,--wrap=" + f for f in PERF_WRAPS],
        target_compatible_with = _RELEASE_ONLY,
    )
    perf_results(
        name = name + "_perf",
        binary = ":" + name,
        perf_name = name,
        seed = seed,
        sizes = sizes,
        target_compatible_with = _RELEASE_ONLY,
    )

def c_fuzz(name, srcs = [], deps = []):
    _check("c_fuzz", srcs, [])

    # `<name>__bin` is the libFuzzer binary; `<name>` runs it (-seed=1 -runs=200000) as a cacheable
    # action with declared outputs and is the test: `<name>[crash]` is the reproducer, `<name>[report]`
    # the symbolized report.
    native.cxx_binary(
        name = name + "__bin",
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _ONLY_FUZZ,
    )
    fuzz_run(
        name = name,
        binary = ":" + name + "__bin",
        target_compatible_with = _ONLY_FUZZ,
    )

    # The fuzz target itself only builds in the fuzz mode; its facts are read from a release-mode
    # (and a san-mode) twin that compiles the same sources with the same deps and flags.
    native.cxx_library(
        name = name + "__facts_unit",
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        link_style = "static",
        target_compatible_with = _RELEASE_OR_SAN,
    )
    _facts(name, "c_fuzz", srcs, deps, unit = ":" + name + "__facts_unit")

def c_mutants(name, module, tests, deps = []):
    """Mutation testing of a `c_library` through the given `c_test` targets (release mode only).

    `deps` lists the other libraries the tests link besides the module and ctest.
    """
    if type(module) != "string" or not module.startswith(":") and ":" not in module:
        fail("c_mutants: `module` must be a target label string, got {!r}".format(module))
    c_mutants_rule(
        name = name,
        module = module,
        module_src = module + "_mutsrc",
        test_targets = tests,
        deps = deps,
        link_flags = _link_flags(),
        target_compatible_with = _RELEASE_ONLY,
    )
