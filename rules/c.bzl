"""C17 rules for the gate. The only way a product builds C.

The macros take no flag arguments of any kind. Mode flags are chosen by the target
platform's mode constraint; the sealed warning profile is appended last.
"""



load("@gate//rules:android.bzl", "android_so", "android_version_script")
load("@gate//rules:apk.bzl", "apk", "apk_check")
load("@gate//rules:catalog.bzl", "c_catalog_gen")
load("@gate//rules:cov.bzl", "cov_report")
load("@gate//rules:embed.bzl", "c_embed_gen")
load("@gate//rules:ctest.bzl", "ctest_results", "fuzz_run")
load("@gate//rules:facts.bzl", "c_android_facts", "c_facts", "c_san_facts")
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

# One list for the optimised modes: the android mode IS the release list (not a copy of it), so a flag added to
# the release profile (a hardening profile, T139) reaches the Android objects in the same change.
_RELEASE_COMPILE = ["-O2"]
_RELEASE_LINK = []

_COMPILE_BY_MODE = {
    "toolchains//:release": _RELEASE_COMPILE,
    "toolchains//:san": ["-O1", "-g", _SAN, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:cov": ["-fprofile-instr-generate", "-fcoverage-mapping", "-fcoverage-mcdc"],
    "toolchains//:fuzz": ["-O1", "-g", _FUZZ, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:android": _RELEASE_COMPILE,
}

_LINK_BY_MODE = {
    "toolchains//:release": _RELEASE_LINK,
    "toolchains//:san": [_SAN],
    "toolchains//:cov": ["-fprofile-instr-generate"],
    "toolchains//:fuzz": [_FUZZ],
    "toolchains//:android": _RELEASE_LINK,
}

def _compile_flags():
    return select(_COMPILE_BY_MODE) + _SEALED

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

_RELEASE_OR_SAN = select({
    "toolchains//:release": [],
    "toolchains//:san": [],
    "DEFAULT": ["toolchains//:never"],
})

def _facts(name, kind, srcs, deps, unit = None, system_libs = [], generated = []):
    for suffix, mode, rule in (("_facts", _RELEASE_ONLY, c_facts), ("_facts_san", _SAN_ONLY, c_san_facts)):
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

# `<name>_results` is built in release and san only (cov and fuzz do not produce verdicts).

def c_test(name, srcs = [], deps = []):
    _check("c_test", srcs, [])
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

def c_apk(name, so, package, label, version_code, version_name, orientation = "landscape", permissions = [], assets = [], visibility = []):
    """A signed, 16 KB aligned APK `<name>.apk` of one `c_android_so` (android mode only), and its test `<name>_check`.

    `so` is `":<name>"` of a `c_android_so` of this package that exports exactly `ANativeActivity_onCreate`; only its checked
    output is used, never its `__lib`. The manifest is generated (rules/apk_manifest.py): `package`, `label`,
    `version_code`, `version_name`, `orientation` and `permissions` (names from `INTERNET`) are validated there; minSdk 28 and
    targetSdk 35 are fixed, `hasCode` is false (no Java: T-A6) and one NativeActivity loads the object. `assets` are plain
    file names of this package, packaged under `assets/`. There is no `res` (T-A6). The APK is signed with the checked-in
    test-only debug key and nothing else: no argument, environment variable or file of a product selects another key, and
    `<name>_check` (rules/apk_check.py: entries, 16 KB alignment, `apksigner verify`, the debug certificate, the manifest as
    declared, the object's LOAD alignment and exports) fails for an APK signed by any other.
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
    if type(permissions) != "list" or [p for p in permissions if p not in ["INTERNET"]] or len(set(permissions)) != len(permissions):
        fail("c_apk {}: `permissions` must be a list without repeats from [\"INTERNET\"], got {!r}".format(name, permissions))
    _plain_files("c_apk", "assets", assets, "")
    for asset in assets:
        if "/" in asset or asset.startswith("."):
            fail("c_apk {}: `assets` entries must be plain file names of this package, got {!r}".format(name, asset))
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
        target_compatible_with = _ANDROID_ONLY,
        visibility = visibility,
    )
    apk_check(
        name = name + "_check",
        apk = ":" + name,
        target_compatible_with = _ANDROID_ONLY,
        visibility = [],
    )

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
