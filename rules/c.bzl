"""C17 rules for the gate. The only way a product builds C.

The macros take no flag arguments of any kind. Mode flags are chosen by the target
platform's mode constraint; the sealed warning profile is appended last.
"""

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

def c_library(name, srcs = [], headers = [], deps = [], visibility = []):
    native.cxx_library(
        name = name,
        srcs = srcs,
        exported_headers = headers,
        deps = deps,
        visibility = visibility,
        compiler_flags = _compile_flags(),
        link_style = "static",
    )

def c_binary(name, srcs = [], deps = []):
    native.cxx_binary(
        name = name,
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _NOT_IN_FUZZ,
    )

def c_test(name, srcs = [], deps = []):
    native.cxx_test(
        name = name,
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        target_compatible_with = _NOT_IN_FUZZ,
    )

def c_fuzz(name, srcs = [], deps = []):
    native.cxx_test(
        name = name,
        srcs = srcs,
        deps = deps,
        compiler_flags = _compile_flags(),
        linker_flags = _link_flags(),
        args = ["-seed=1", "-runs=200000", "-artifact_prefix=/tmp/"],
        target_compatible_with = _ONLY_FUZZ,
    )
