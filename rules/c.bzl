"""C17 rules for the gate. The only way a product builds C.

The macros take no flag arguments of any kind. Mode flags are chosen by the target
platform's mode constraint; the sealed warning profile is appended last.
"""



load("@gate//rules:android.bzl", "android_so", "android_version_script")
load("@gate//rules:apk.bzl", "apk", "apk_check")
load("@gate//rules:catalog.bzl", "c_catalog_gen")
load("@gate//rules:cov.bzl", "cov_report")
load("@gate//rules:embed.bzl", "c_embed_gen")
load("@gate//rules:ctest.bzl", "MSAN_ENV_LINES", "TSAN_ENV_LINES", "ctest_results")
load("@gate//rules:facts.bzl", "c_android_facts", "c_facts", "c_msan_facts", "c_san_facts", "c_tsan_facts")
load("@gate//rules:fuzz.bzl", "fuzz_corpus", "fuzz_run", "fuzz_runs")
load("@gate//rules:mutate.bzl", "c_mutants_rule", "mutsrc")
load("@gate//rules:perf.bzl", "PERF_WRAPS", "perf_results")
load("@gate//rules:sim.bzl", "sim_merge", "sim_params", "sim_run", "sim_salt")

_SEALED_HEAD = [
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
]

# clang has no -Wstack-usage (a GCC flag); -Wframe-larger-than is its equivalent. The msan mode alone leaves it out:
# origin tracking inflates the frames of instrumented code, which is never shipped (docs/toolchain.md).
_FRAME_LIMIT = select({
    "toolchains//:msan": [],
    "DEFAULT": ["-Wframe-larger-than=512"],
})

_SEALED_TAIL = [
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
_MSAN = ["-fsanitize=memory", "-fsanitize-memory-track-origins=2"]
_TSAN = "-fsanitize=thread"

# The hardened release profile (T139, P003 §6, D5; docs/toolchain.md): the flags of the shipped build that stay under 3%
# instructions on every declared c_perf target AND that the other gates accept today. Left out because they move a
# target by more: `-fsanitize=bounds -fsanitize-trap=bounds` (+21% to +35%) and `-D_FORTIFY_SOURCE=3` (+5.4%, and it
# hides libc calls from `libc_bytes`). Left out for now although under 3%: `-fstack-protector-strong`, whose
# `__stack_chk_fail` import the `symbols` gate reports as `undeclared-symbol` (docs/toolchain.md). Release only: the
# other modes are not shipped, and the sanitizer modes would conflict with some of these flags.
_HARDENED_RELEASE = ["-ftrivial-auto-var-init=zero", "-fstrict-flex-arrays=3"]

# One list for the optimised modes: the android mode IS the release list (not a copy of it), so a flag added to
# the release profile (a hardening profile, T139) reaches the Android objects in the same change.
_RELEASE_COMPILE = ["-O2"] + _HARDENED_RELEASE
_RELEASE_LINK = []

_COMPILE_BY_MODE = {
    "toolchains//:release": _RELEASE_COMPILE,
    "toolchains//:san": ["-O1", "-g", _SAN, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:cov": ["-fprofile-instr-generate", "-fcoverage-mapping", "-fcoverage-mcdc"],
    "toolchains//:fuzz": ["-O1", "-g", _FUZZ, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:msan": ["-O1", "-g"] + _MSAN + ["-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:tsan": ["-O1", "-g", _TSAN, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:android": _RELEASE_COMPILE,
}

_LINK_BY_MODE = {
    "toolchains//:release": _RELEASE_LINK,
    "toolchains//:san": [_SAN],
    "toolchains//:cov": ["-fprofile-instr-generate"],
    "toolchains//:fuzz": [_FUZZ],
    "toolchains//:msan": _MSAN,
    "toolchains//:tsan": [_TSAN],
    "toolchains//:android": _RELEASE_LINK,
}

def _compile_flags():
    return select(_COMPILE_BY_MODE) + _SEALED_HEAD + _FRAME_LIMIT + _SEALED_TAIL

def _link_flags():
    return select(_LINK_BY_MODE)

# Fuzz mode links libFuzzer's main(); ordinary binaries/tests are not built there, and
# fuzz targets are not built in the other modes.
_ONLY_FUZZ = ["toolchains//:fuzz"]
# Binaries and tests run on the build farm's Linux x86_64 workers: never built for the android mode, whose only
# products are libraries and `c_android_so` (a `//...` build under the android platform skips them as incompatible).
_HOST_ONLY = select({
    "toolchains//:fuzz": ["toolchains//:never"],
    "toolchains//:android": ["toolchains//:never"],
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
_MSAN_ONLY = ["toolchains//:msan"]
_TSAN_ONLY = ["toolchains//:tsan"]

_RELEASE_OR_SAN = select({
    "toolchains//:release": [],
    "toolchains//:san": [],
    "toolchains//:msan": [],
    "toolchains//:tsan": [],
    "DEFAULT": ["toolchains//:never"],
})

# A `c_sim` runs in release and in san only (P330 §1.3: the identity check compares those two).
_RELEASE_OR_SAN_ONLY = select({
    "toolchains//:release": [],
    "toolchains//:san": [],
    "DEFAULT": ["toolchains//:never"],
})

# MemorySanitizer needs every object of the program instrumented, and the pinned sysroot has no instrumented system
# library. A `c_library` that links a sysroot library other than libc and pthread (today: X11) is therefore
# incompatible with the msan mode, and so is everything that depends on it: its tests have no msan `_results`.
_NOT_IN_MSAN = select({
    "toolchains//:msan": ["toolchains//:never"],
    "DEFAULT": [],
})

# `<name>_results` of a `c_test`: release, san and msan (a test with an uninstrumented dependency is already
# incompatible with msan through that dependency), tsan only for `threads = True`.
_RESULTS_EVERY_MODE = select({
    "toolchains//:release": [],
    "toolchains//:san": [],
    "toolchains//:msan": [],
    "DEFAULT": ["toolchains//:never"],
})

_RESULTS_THREADED = select({
    "toolchains//:release": [],
    "toolchains//:san": [],
    "toolchains//:msan": [],
    "toolchains//:tsan": [],
    "DEFAULT": ["toolchains//:never"],
})

def _facts(name, kind, srcs, deps, unit = None, system_libs = [], generated = []):
    # A twin per mode the gate compares with release (T138): san, msan and tsan. A module with a sysroot library beyond
    # libc and pthread in its closure has no msan twin (its unit is incompatible with the msan mode).
    for suffix, mode, rule in (
        ("_facts", _RELEASE_ONLY, c_facts),
        ("_facts_san", _SAN_ONLY, c_san_facts),
        ("_facts_msan", _MSAN_ONLY, c_msan_facts),
        ("_facts_tsan", _TSAN_ONLY, c_tsan_facts),
    ):
        rule(
            name = name + suffix,
            unit = unit if unit else ":" + name,
            facts_name = name,
            kind = kind,
            srcs = srcs,
            facts_deps = deps,
            system_libs = system_libs,
            generated = generated,
            target_compatible_with = mode,
        )

# The sysroot libraries a `c_library` may name (T095). `pthread`: glibc 2.31 keeps pthread_create and friends in
# libpthread; bionic has them in libc, so it links nothing in the android mode. `X11` (T117): libX11 for a Linux X11
# shell. `android` and `log` (T-G1): the NDK's libandroid.so (ANativeWindow_*, AInput*, ALooper_*, ANativeActivity_*)
# and liblog.so (__android_log_write), linked in the android mode only. A new entry needs a product that needs it, and
# `facts_data.SYSTEM_LIBS` (the same list, checked against this one by a test) so the policy gate knows it.
_SYSTEM_LIBS = ["pthread", "X11", "android", "log"]

# What a name links, in link order. libX11 is a shared object whose own dependencies (libxcb, then libXau and
# libXdmcp) must follow it on the line; all of them are members of the pinned sysroot (toolchains/BUCK).
# The Android names exist in that one mode, `pthread` in every mode but it.
_SYSTEM_LIB_FLAGS = {
    "X11": ["-lX11", "-lxcb", "-lXau", "-lXdmcp"],
    "pthread": select({"toolchains//:android": [], "DEFAULT": ["-lpthread"]}),
    "android": select({"toolchains//:android": ["-landroid"], "DEFAULT": []}),
    "log": select({"toolchains//:android": ["-llog"], "DEFAULT": []}),
}

def _system_libs(macro, libs):
    if type(libs) != "list":
        fail("{}: `system_libs` must be a list of sysroot library names, got {}".format(macro, type(libs)))
    for lib in libs:
        if type(lib) != "string" or lib not in _SYSTEM_LIBS:
            fail("{}: `system_libs` entries must be one of {}, got {!r}".format(macro, _SYSTEM_LIBS, lib))
    if len(set(libs)) != len(libs):
        fail("{}: `system_libs` has duplicates: {}".format(macro, libs))
    flags = []
    for lib in libs:
        flags += _SYSTEM_LIB_FLAGS.get(lib, ["-l" + lib])
    return flags

def _exported_deps(deps, exported_deps):
    if type(exported_deps) != "list":
        fail("c_library: `exported_deps` must be a list of labels, got {}".format(type(exported_deps)))
    for label in exported_deps:
        if label in deps:
            fail("c_library: {!r} is in both `deps` and `exported_deps`; list it once, in `exported_deps` if a public header includes it".format(label))
    if len(set(exported_deps)) != len(exported_deps):
        fail("c_library: `exported_deps` has duplicates: {}".format(exported_deps))

def c_library(name, srcs = [], headers = [], deps = [], visibility = [], system_libs = [], exported_deps = []):
    """A C17 library. `exported_deps`: the libraries whose headers this library's PUBLIC headers include.

    Their headers and link inputs reach every dependent, and each is an edge FROM this library for every gate check
    (facts, layering, fan-out, mutants). A dependent gains no edge to them: its own sources that use them still
    need a direct dep. Export exactly what the public headers include, never for convenience.
    """
    _check("c_library", srcs, headers)
    _exported_deps(deps, exported_deps)

    # Exported as post-link flags (after every object and archive), resolved in the pinned sysroot by the
    # toolchain's own link line: every binary, test and mutant binary that links this library gets them.
    link_flags = _system_libs("c_library", system_libs)
    native.cxx_library(
        name = name,
        srcs = srcs,
        exported_headers = headers,
        deps = deps,
        exported_deps = exported_deps,
        visibility = visibility,
        compiler_flags = _compile_flags(),
        exported_post_linker_flags = link_flags,
        link_style = "static",
        target_compatible_with = _NOT_IN_MSAN if [l for l in system_libs if l != "pthread"] else [],
    )
    _facts(name, "c_library", srcs, deps + exported_deps, system_libs = system_libs)

    # What `c_mutants` needs to know about this module: its source files.
    mutsrc(name = name + "_mutsrc", srcs = srcs, headers = headers, visibility = ["PUBLIC"])

def _catalog_label(macro, attr, label):
    if type(label) != "string" or not label.startswith("//") or label.count(":") != 1:
        fail("{}: `{}` must be a `//package:name` label string, got {!r}".format(macro, attr, label))

def _catalog_files(macro, attr, items, suffix):
    if type(items) != "list" or len(items) == 0:
        fail("{}: `{}` must be a non-empty list of plain file names, got {!r}".format(macro, attr, items))
    _plain_files(macro, attr, items, suffix)

def c_catalog(name, pots, po, langs, source_lang, symbol, runtime, deps = [], names = {}, visibility = []):
    """A const message catalog from gettext files (T105): a `c_library` `name` with the header `<package>/<name>.h`.

    `pots`: ordered `.pot` files of the package. `po`: {lang: [`.po` files, one per pot, same order]} for every
    language of `langs` but `source_lang`. `langs`: ordered language codes (the index is the runtime `lang`).
    `source_lang`: the language whose text is the msgid itself. `symbol`: the C identifier of the generated
    `const i18n_catalog_t`; the msgid enum is `<SYMBOL>_<WORDS>`. `runtime`: the i18n library (`//package:name`); its
    header is `<package>/<name>.h`, a dep of the library. `deps`: the libraries the runtime header includes from (the generated
    header includes it, and `deps` of a library are not exported), e.g. the core and fmt of the business-apps i18n.
    `names`: {msgid: WORDS} overrides of the enum name, each only to resolve a real collision (po2c checks).
    `gate/rigor_lib/po2c.py` fails the build on a bad translation.
    The sources are generated in buck-out and are not mutated: a catalog is an L1 module.
    """
    _catalog_files("c_catalog", "pots", pots, ".pot")
    _catalog_label("c_catalog", "runtime", runtime)
    if type(po) != "dict":
        fail("c_catalog: `po` must be a dict of language -> list of .po files, got {}".format(type(po)))
    for lang in po:
        _catalog_files("c_catalog", "po[{}]".format(lang), po[lang], ".po")
    package = native.package_name()
    header = (package + "/" if package else "") + name + ".h"
    runtime_package, _, runtime_name = runtime[2:].partition(":")
    runtime_header = (runtime_package + "/" if runtime_package else "") + runtime_name + ".h"
    if type(names) != "dict":
        fail("c_catalog: `names` must be a dict of msgid -> enum words, got {}".format(type(names)))
    c_catalog_gen(
        name = name + "__gen",
        names = names,
        stem = name,
        pots = pots,
        po = po,
        langs = langs,
        source_lang = source_lang,
        symbol = symbol,
        header = header,
        runtime_header = runtime_header,
    )
    native.cxx_library(
        name = name,
        srcs = [":" + name + "__gen[c]"],
        # A dict keeps the key under the package: the header is `<package>/<name>.h`, as a list of files would be.
        exported_headers = {name + ".h": ":" + name + "__gen[h]"},
        deps = [runtime] + deps,
        visibility = visibility,
        compiler_flags = _compile_flags(),
        link_style = "static",
    )
    _facts(name, "c_library", [], [runtime] + deps, generated = [name + ".c"])
    mutsrc(name = name + "_mutsrc", srcs = [], headers = [], visibility = ["PUBLIC"])

_EMBED_MAX = 16 * 1024 * 1024
_EMBED_SYMBOL_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"

def _embed_check(src, symbol, max_bytes):
    if type(symbol) != "string" or symbol == "" or symbol[0] == "_" or symbol[0].isdigit() or any([c not in _EMBED_SYMBOL_CHARS for c in symbol.elems()]):
        fail("c_embed: `symbol` must be a C identifier ([A-Za-z][A-Za-z0-9_]*), got {!r}".format(symbol))
    if type(src) != "string":
        fail("c_embed: `src` must be one file name of the package, got {}: {!r}".format(type(src), src))
    if src == "" or src.startswith("/") or src.startswith("@") or ":" in src or src.endswith("/") or ".." in src.split("/") or "*" in src:
        fail("c_embed: `src` must be one plain file of the package (no label, glob, `..` or absolute path), got {!r}".format(src))
    if type(max_bytes) != "int" or max_bytes < 1 or max_bytes > _EMBED_MAX:
        fail("c_embed: `max_bytes` must be an int from 1 to {} (16 MiB), got {!r}".format(_EMBED_MAX, max_bytes))

def c_embed(name, src, symbol, max_bytes = 1048576, nul = False, visibility = []):
    """A binary file as a const byte array (T112): a `c_library` `name` with the header `<package>/<name>.h`.

    The header declares `extern const unsigned char <symbol>[];` and `extern const size_t <symbol>_len;`. The bytes are
    exactly the file and `<symbol>_len` is its size. By default there is no terminator; with `nul = True` one 0x00 byte
    follows the data inside the array (`<symbol>[<symbol>_len] == 0`, so it is a C string) and `<symbol>_len` still does
    NOT count it. `src`: one checked-in file of the package, 1 to
    `max_bytes` bytes (at most 16 MiB). The C text is generated at build time by `gate/rigor_lib/bin2c.py`; nothing
    generated is checked in. A bad `symbol`, `src` or `max_bytes` is an analysis error, an empty or oversized file a
    build error. Licensing: an embedded asset needs its license file next to it in the package.
    """
    _embed_check(src, symbol, max_bytes)
    if type(nul) != "bool":
        fail("c_embed: `nul` must be True or False, got {!r}".format(nul))
    package = native.package_name()
    header = (package + "/" if package else "") + name + ".h"
    c_embed_gen(
        name = name + "__gen",
        stem = name,
        src = src,
        symbol = symbol,
        max_bytes = max_bytes,
        nul = nul,
        header = header,
    )
    native.cxx_library(
        name = name,
        srcs = [":" + name + "__gen[c]"],
        exported_headers = {name + ".h": ":" + name + "__gen[h]"},
        visibility = visibility,
        compiler_flags = _compile_flags(),
        link_style = "static",
    )
    _facts(name, "c_library", [], [], generated = [name + ".c"])
    mutsrc(name = name + "_mutsrc", srcs = [], headers = [], visibility = ["PUBLIC"])

def c_binary(name, srcs = [], deps = []):
    _check("c_binary", srcs, [])
    native.cxx_binary(
        name = name,
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _HOST_ONLY,
    )
    _facts(name, "c_binary", srcs, deps)

# `<name>_results` is built in release and san (cov and fuzz do not produce verdicts), and in msan unless the link
# closure has a system library beyond libc and pthread, and in tsan only for `threads = True`.

def c_test(name, srcs = [], deps = [], threads = False):
    """A ctest binary and its `<name>_results`. `threads = True`: the test starts threads, so it also has a tsan result."""
    _check("c_test", srcs, [])
    if type(threads) != "bool":
        fail("c_test: `threads` must be True or False, got {!r}".format(threads))
    native.cxx_test(
        name = name,
        srcs = srcs,
        deps = deps + ["gate//ctest:ctest"],
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _HOST_ONLY,
    )

    _facts(name, "c_test", srcs, deps + ["gate//ctest:ctest"])

    # `<name>_results`: the ctest JSON Lines, produced on RE as a cacheable artifact.
    ctest_results(
        name = name + "_results",
        test = ":" + name,
        threads = threads,
        target_compatible_with = _RESULTS_THREADED if threads else _RESULTS_EVERY_MODE,
        env_lines = select({
            "toolchains//:msan": MSAN_ENV_LINES,
            "toolchains//:tsan": TSAN_ENV_LINES,
            "DEFAULT": [],
        }),
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

def c_fuzz(name, srcs = [], deps = [], corpus = [], runs = None):
    """A libFuzzer target. `corpus`: files of the product (a `glob`) replayed first; `runs`: the budget (docs/fuzz.md)."""
    _check("c_fuzz", srcs, [])
    corpus = fuzz_corpus("c_fuzz", corpus)
    runs = fuzz_runs("c_fuzz", runs)

    # `<name>__bin` is the libFuzzer binary; `<name>` replays the corpus, then runs it (-seed=1 -runs=N) as a
    # cacheable action with declared outputs and is the test: `<name>[crash]` is the reproducer, `<name>[report]`
    # the symbolized report, `<name>[stats]` the numbers `rigor fuzz` judges.
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
        corpus = corpus,
        runs = runs,
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

# Android shared objects are linked with 16 KB LOAD segments (Android 15+ devices map with 16 KB pages); the NDK
# toolchain links with `-z max-page-size=16384` and rules/elf_check.py refuses an object that is not.
_ANDROID_PAGE = 16384
_ANDROID_ONLY = ["toolchains//:android"]

def _symbol_names(macro, attr, names):
    if type(names) != "list" or len(names) == 0:
        fail("{}: `{}` must be a non-empty list of C identifiers, got {!r}".format(macro, attr, names))
    for symbol in names:
        if type(symbol) != "string" or symbol == "" or symbol[0].isdigit() or any([c not in _EMBED_SYMBOL_CHARS for c in symbol.elems()]):
            fail("{}: `{}` entries must be C identifiers ([A-Za-z_][A-Za-z0-9_]*), got {!r}".format(macro, attr, symbol))
    if len(set(names)) != len(names):
        fail("{}: `{}` has duplicates: {}".format(macro, attr, names))

def c_android_so(name, exports, srcs = [], deps = [], system_libs = [], visibility = []):
    """A shared object `lib<name>.so` for Android (android mode only), exporting exactly the symbols of `exports`.

    `srcs` and `deps` as for `c_library`; the dependencies are linked in statically. A GNU version script makes
    the `exports` global and everything else local, and the build fails (rules/elf_check.py) if the linked object
    defines any other dynamic symbol, lacks one of `exports`, or has a PT_LOAD segment aligned to less than 16 KB.
    `<name>` is the checked `lib<name>.so`; `<name>_facts` (the android mode's objects of this target, like
    `c_library`'s release facts) feeds the symbols gate, with kind c_android_so.
    The link is `-Wl,--no-undefined -Wl,-z,relro,-z,now -Wl,--gc-sections`; `system_libs` as for `c_library`.
    """
    _check("c_android_so", srcs, [])
    _symbol_names("c_android_so", "exports", exports)
    link_flags = _system_libs("c_android_so", system_libs)
    android_version_script(name = name + "__map", symbols = exports, visibility = [])
    native.cxx_library(
        name = name + "__lib",
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        linker_flags = [
            "-Wl,--version-script=$(location :{}__map)".format(name),
            "-Wl,--no-undefined",
            "-Wl,-z,relro,-z,now",
            "-Wl,--gc-sections",
        ],
        post_linker_flags = link_flags,
        preferred_linkage = "shared",
        link_style = "static",
        target_compatible_with = _ANDROID_ONLY,
        visibility = [],    # the unchecked object is the macro's own: only `<name>` (the checked one) is a product output
    )
    android_so(
        name = name,
        lib = ":" + name + "__lib",
        soname = name,
        exports = exports,
        page_size = _ANDROID_PAGE,
        target_compatible_with = _ANDROID_ONLY,
        visibility = visibility,
    )
    c_android_facts(
        name = name + "_facts",
        unit = ":" + name + "__lib",
        facts_name = name,
        kind = "c_android_so",
        srcs = srcs,
        facts_deps = deps,
        system_libs = system_libs,
        target_compatible_with = _ANDROID_ONLY,
    )

_APK_PACKAGE = "abcdefghijklmnopqrstuvwxyz0123456789_."

def _apk_text(name, what, value, allowed, first, limit):
    if type(value) != "string" or len(value) == 0 or len(value) > limit or value[0] not in first:
        fail("c_apk {}: `{}` must be a string of 1 to {} characters starting with one of {!r}, got {!r}".format(name, what, limit, first, value))
    for char in value.elems():
        if char not in allowed:
            fail("c_apk {}: `{}` has the character {!r}; allowed: {}".format(name, what, char, allowed))

_APK_CLASS_FIRST = "abcdefghijklmnopqrstuvwxyz"
_APK_CLASS_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.$"
_APK_RECEIVER_KEYS = ["actions", "exported", "meta_data", "name", "permission"]
_APK_ACTIVITY_CHOICES = {
    "launch_mode": ["", "standard", "singleTop", "singleTask", "singleInstance"],
    "lock_task_mode": ["", "if_whitelisted"],
    "soft_input_mode": ["", "stateHidden", "stateAlwaysHidden", "adjustResize", "adjustPan", "adjustNothing"],
}

def _apk_closed(name, what, value, allowed):
    if type(value) != "string" or value not in allowed:
        fail("c_apk {}: `{}` must be one of {}, got {!r}".format(name, what, allowed, value))

_APK_FORBIDDEN_PACKAGES = ["java", "javax", "android", "androidx", "dalvik", "kotlin", "com.android"]

def _apk_packages(name, java_packages, package):
    """The listed Java packages (default: the app package): explicit, valid, never a platform or runtime package."""
    if type(java_packages) != "list" or len(set(java_packages)) != len(java_packages):
        fail("c_apk {}: `java_packages` must be a list without repeats, got {!r}".format(name, java_packages))
    if not java_packages:
        return [package]
    for entry in java_packages:
        _apk_text(name, "java_packages", entry, _APK_PACKAGE, "abcdefghijklmnopqrstuvwxyz", 120)
        for forbidden in _APK_FORBIDDEN_PACKAGES:
            if entry == forbidden or entry.startswith(forbidden + "."):
                fail("c_apk {}: `java_packages` entry {!r} is a platform or runtime package ({})".format(name, entry, ", ".join(_APK_FORBIDDEN_PACKAGES)))
        parts = entry.split(".")
        if len(parts) < 2 or [p for p in parts if not p or p[0] not in "abcdefghijklmnopqrstuvwxyz"]:
            fail("c_apk {}: `java_packages` entry {!r} must be a dotted lower-case package name with at least two parts".format(name, entry))
    return java_packages

def _apk_class(name, what, value, packages):
    ok = type(value) == "string" and len(value) <= 200 and "." in value and value.rpartition(".")[0] in packages and len(value.rpartition(".")[2]) > 0
    if ok:
        for char in value.elems():
            ok = ok and char in _APK_CLASS_CHARS
    if not ok:
        fail("c_apk {}: `{}` must be a class directly in one of the `java_packages` {} ([A-Za-z0-9_.$] only), got {!r}".format(name, what, packages, value))

def _apk_receivers(name, receivers, package, classes, res_names):
    """The receivers as complete dicts (every key present), each checked against the closed vocabularies."""
    if type(receivers) != "list" or len(receivers) > 8:
        fail("c_apk {}: `receivers` must be a list of at most 8 dicts, got {!r}".format(name, receivers))
    full = []
    for receiver in receivers:
        if type(receiver) != "dict" or [k for k in receiver if k not in _APK_RECEIVER_KEYS] or "name" not in receiver:
            fail("c_apk {}: a receiver is a dict with `name` and optionally permission, exported, actions, meta_data; got {!r}".format(name, receiver))
        full_one = {"actions": [], "exported": False, "meta_data": {}, "permission": ""}
        full_one.update(receiver)
        if full_one["name"] not in classes:
            fail("c_apk {}: the receiver {!r} must be one of `java_classes`".format(name, full_one["name"]))
        _apk_closed(name, "receivers permission", full_one["permission"], ["", "BIND_DEVICE_ADMIN"])
        if type(full_one["exported"]) != "bool":
            fail("c_apk {}: a receiver's `exported` must be True or False, got {!r}".format(name, full_one["exported"]))
        if type(full_one["actions"]) != "list" or [a for a in full_one["actions"] if a not in ["DEVICE_ADMIN_ENABLED", "BOOT_COMPLETED"]] or len(set(full_one["actions"])) != len(full_one["actions"]):
            fail("c_apk {}: a receiver's `actions` must be a list without repeats from [\"DEVICE_ADMIN_ENABLED\", \"BOOT_COMPLETED\"], got {!r}".format(name, full_one["actions"]))
        meta = full_one["meta_data"]
        if type(meta) != "dict" or [k for k in meta if k != "android.app.device_admin"] or [v for v in meta.values() if type(v) != "string" or v + ".xml" not in res_names]:
            fail("c_apk {}: a receiver's `meta_data` must map \"android.app.device_admin\" to a name of `res_xml` (without .xml), got {!r}".format(name, meta))
        full.append(full_one)
    if len(set([r["name"] for r in full])) != len(full):
        fail("c_apk {}: `receivers` must not repeat a class".format(name))
    return full

def c_apk(
        name,
        so,
        package,
        label,
        version_code,
        version_name,
        orientation = "landscape",
        permissions = [],
        assets = [],
        java_srcs = [],
        java_classes = [],
        java_packages = [],
        res_xml = [],
        application_class = "",
        receivers = [],
        launch_mode = "",
        lock_task_mode = "",
        exclude_from_recents = False,
        soft_input_mode = "",
        categories = [],
        visibility = []):
    """A signed, 16 KB aligned APK `<name>.apk` of one `c_android_so` (android mode only), and its test `<name>_check`.

    `so` is `":<name>"` of a `c_android_so` of this package that exports exactly `ANativeActivity_onCreate`; only its checked
    output is used, never its `__lib`. The manifest is generated (rules/apk_manifest.py): `package`, `label`,
    `version_code`, `version_name`, `orientation` and `permissions` (names from `INTERNET`, `RECEIVE_BOOT_COMPLETED`) are
    validated there; minSdk 28 and targetSdk 35 are fixed and one NativeActivity loads the object. `assets` are plain
    file names of this package, packaged under `assets/`. The APK is signed with the checked-in
    test-only debug key and nothing else: no argument, environment variable or file of a product selects another key, and
    `<name>_check` (rules/apk_check.py: entries, dex, 16 KB alignment, `apksigner verify`, the debug certificate, the manifest as
    declared, the object's LOAD alignment and exports) fails for an APK signed by any other.

    Java (T-G3b), all plain data: `java_srcs` are `.java` files of this package (no path), compiled with the pinned javac
    against android.jar (-Werror, no processors) and dexed by the pinned d8 into classes.dex (`hasCode="true"`); `java_classes`
    lists every class the dex must define (binary names, nested ones as `A$B`), no more, no fewer. `java_packages` lists the
    Java packages those classes (and the `package` line of every `java_srcs` file, the receivers and `application_class`) may lie
    in: explicit names, default `[package]`, never `java`, `javax`, `android`, `androidx`, `dalvik`, `kotlin`, `com.android`.
    `res_xml` are `.xml` files of this package compiled by aapt2 into `res/xml/`. `application_class` and the `receivers`
    (dicts: `name` from `java_classes`, `permission` BIND_DEVICE_ADMIN, `exported`, `actions` from DEVICE_ADMIN_ENABLED and
    BOOT_COMPLETED, `meta_data` {"android.app.device_admin": <res_xml name without .xml>}) are manifest declarations, as are
    the activity's `launch_mode`, `lock_task_mode` (if_whitelisted), `exclude_from_recents`, `soft_input_mode` and the extra
    intent-filter `categories` (HOME, DEFAULT). There is no way to hand over manifest XML.
    """
    if type(so) != "string" or not so.startswith(":") or "__" in so or "/" in so:
        fail("c_apk {}: `so` must be the label \":name\" of a c_android_so of this package, got {!r}".format(name, so))
    _apk_text(name, "package", package, _APK_PACKAGE, "abcdefghijklmnopqrstuvwxyz", 120)
    _apk_text(name, "label", label, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ._-", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", 40)
    _apk_text(name, "version_name", version_name, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", 32)
    if type(version_code) != "int" or version_code < 1 or version_code > 2100000000:
        fail("c_apk {}: `version_code` must be an int from 1 to 2100000000, got {!r}".format(name, version_code))
    if orientation not in ["landscape", "portrait", "sensorLandscape", "unspecified"]:
        fail("c_apk {}: `orientation` must be landscape, portrait, sensorLandscape or unspecified, got {!r}".format(name, orientation))
    if type(permissions) != "list" or [p for p in permissions if p not in ["INTERNET", "RECEIVE_BOOT_COMPLETED"]] or len(set(permissions)) != len(permissions):
        fail("c_apk {}: `permissions` must be a list without repeats from [\"INTERNET\", \"RECEIVE_BOOT_COMPLETED\"], got {!r}".format(name, permissions))
    _plain_files("c_apk", "assets", assets, "")
    for asset in assets:
        if "/" in asset or asset.startswith("."):
            fail("c_apk {}: `assets` entries must be plain file names of this package, got {!r}".format(name, asset))
    _plain_files("c_apk", "java_srcs", java_srcs, ".java")
    _plain_files("c_apk", "res_xml", res_xml, ".xml")
    for item in java_srcs + res_xml:
        if "/" in item or item.startswith(".") or "\\" in item:
            fail("c_apk {}: `java_srcs` and `res_xml` entries must be plain file names of this package (no path), got {!r}".format(name, item))
    if len(set(java_srcs)) != len(java_srcs) or len(set(res_xml)) != len(res_xml):
        fail("c_apk {}: `java_srcs` and `res_xml` must not repeat a file".format(name))
    if type(java_classes) != "list" or bool(java_classes) != bool(java_srcs) or len(set(java_classes)) != len(java_classes):
        fail("c_apk {}: `java_classes` must list the classes of `java_srcs` without repeats, and be empty exactly when `java_srcs` is, got {!r}".format(name, java_classes))
    packages = _apk_packages(name, java_packages, package)
    for cls in java_classes:
        _apk_class(name, "java_classes", cls, packages)
    if application_class != "":
        _apk_class(name, "application_class", application_class, packages)
        if application_class not in java_classes:
            fail("c_apk {}: `application_class` {!r} must be one of `java_classes`".format(name, application_class))
    if type(res_xml) == "list" and [r for r in res_xml if len(r) > 44 or not r[0] in _APK_CLASS_FIRST or [c for c in r[:-4].elems() if c not in "abcdefghijklmnopqrstuvwxyz0123456789_"]]:
        fail("c_apk {}: `res_xml` names must be lower-case [a-z][a-z0-9_]* plus .xml (at most 40 characters before it), got {!r}".format(name, res_xml))
    res_names = res_xml
    full_receivers = _apk_receivers(name, receivers, package, java_classes, res_names)
    for key, value in [("launch_mode", launch_mode), ("lock_task_mode", lock_task_mode), ("soft_input_mode", soft_input_mode)]:
        _apk_closed(name, key, value, _APK_ACTIVITY_CHOICES[key])
    if type(exclude_from_recents) != "bool":
        fail("c_apk {}: `exclude_from_recents` must be True or False, got {!r}".format(name, exclude_from_recents))
    if type(categories) != "list" or [c for c in categories if c not in ["HOME", "DEFAULT"]] or len(set(categories)) != len(categories):
        fail("c_apk {}: `categories` must be a list without repeats from [\"HOME\", \"DEFAULT\"], got {!r}".format(name, categories))
    apk(
        name = name,
        apk_name = name + ".apk",
        so = so,
        package = package,
        label = label,
        version_code = version_code,
        version_name = version_name,
        orientation = orientation,
        permissions = permissions,
        assets = assets,
        asset_names = assets,
        java_srcs = java_srcs,
        java_classes = java_classes,
        java_packages = packages,
        res_xml = res_xml,
        res_xml_names = res_xml,
        application_class = application_class,
        receivers = full_receivers,
        launch_mode = launch_mode,
        lock_task_mode = lock_task_mode,
        exclude_from_recents = exclude_from_recents,
        soft_input_mode = soft_input_mode,
        categories = categories,
        target_compatible_with = _ANDROID_ONLY,
        visibility = visibility,
    )
    apk_check(
        name = name + "_check",
        apk = ":" + name,
        target_compatible_with = _ANDROID_ONLY,
        visibility = [],
    )

def c_sim(name, srcs = [], deps = [], seeds = None, run_ms = None, shards = None):
    """A whole-app simulation target (P330 §1, docs/sim.md): `srcs` is the product's WORLD (it implements `sim/world.h`),
    linked with the gate's runner (`gate//sim:runner`) that owns `main`, the seeds, the workload and the identity check.

    `seeds`, `run_ms` and `shards` are optional budgets (defaults and maxima in rules/sim.bzl; the judge demands the
    tier's minimum). `<name>` is the test: it runs every shard and merges them; `<name>[stats]`, `[hashes]`,
    `[verdict]` and `[report]` are its outputs. The world's sources get facts like those of a `c_library`, so every
    other gate sees them (the kind is `c_sim`, a product kind).
    """
    _check("c_sim", srcs, [])
    if len(srcs) == 0:
        fail("c_sim: `srcs` must name the world's source files, got none")
    seeds, run_ms, shards = sim_params("c_sim", seeds, run_ms, shards)
    native.cxx_binary(
        name = name + "__bin",
        srcs = srcs,
        deps = deps + ["gate//sim:runner", "gate//sim:world"],
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _RELEASE_OR_SAN_ONLY,
    )
    per = (seeds + shards - 1) // shards
    parts = []
    for k in range(shards):
        first = k * per
        count = min(per, seeds - first)
        if count > 0:
            part = "{}__shard{}".format(name, k)
            sim_run(
                name = part,
                binary = ":" + name + "__bin",
                world_srcs = srcs,
                first = first,
                count = count,
                run_ms = run_ms,
                salt = sim_salt(),
                target_compatible_with = _RELEASE_OR_SAN_ONLY,
            )
            parts.append(":" + part)
    sim_merge(
        name = name,
        shards = parts,
        seeds = seeds,
        target_compatible_with = _RELEASE_OR_SAN_ONLY,
    )

    # The facts of the world are read from a release-mode (and san, msan, tsan) twin that compiles the same sources with
    # the same deps and flags, like a `c_fuzz`; the runner is the gate's code and is no dep of the facts.
    native.cxx_library(
        name = name + "__facts_unit",
        srcs = srcs,
        deps = deps + ["gate//sim:world"],
        compiler_flags = _compile_flags(),
        link_style = "static",
        target_compatible_with = _RELEASE_OR_SAN,
    )
    _facts(name, "c_sim", srcs, deps, unit = ":" + name + "__facts_unit")

def c_mutants(name, module, tests, deps = [], perf = []):
    """Mutation testing of a `c_library` through the given `c_test` targets (release mode only).

    `deps` lists the other libraries the tests link besides the module and ctest. `perf` lists the module's
    `c_perf` targets (`:x_perf`), run for the mutants that survive every test (docs/mutate.md, "Perf kills").
    """
    if type(module) != "string" or not module.startswith(":") and ":" not in module:
        fail("c_mutants: `module` must be a target label string, got {!r}".format(module))
    c_mutants_rule(
        name = name,
        module = module,
        module_src = module + "_mutsrc",
        test_targets = tests,
        perf = perf,
        deps = deps,
        link_flags = _link_flags(),
        target_compatible_with = _RELEASE_ONLY,
    )
