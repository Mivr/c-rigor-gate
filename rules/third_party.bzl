"""Gate-owned third-party C libraries (`third_party/`), built hermetically and trusted without a scan.

Only `third_party/*/BUCK` files (gate-owned) load this; product build files may only load
`@gate//rules:c.bzl` (checked by `rigor buckfiles`). A library is
  * unpacked from a release tarball pinned by sha256, whose C/H file set must equal a committed
    manifest exactly (`<name>_src`, third_party/extract.py);
  * compiled with its own flag set (mode flags + C17, vendored warnings are not errors), with the
    gate-owned configuration header forced on every user through exported preprocessor flags;
  * described by `<name>_symbols`: the facts file (kind `c_third_party`) whose symbol lists are
    computed by the pinned `llvm-nm` from the objects. Nobody declares an export by hand.
"""

def _label_text(label: Label, name: str | None = None) -> str:
    cell = "" if label.cell == "root" else label.cell
    return "{}//{}:{}".format(cell, label.package, name if name else label.name)

def _tree_impl(ctx: AnalysisContext) -> list[Provider]:
    archive = ctx.actions.declare_output("archive.tar")
    ctx.actions.download_file(archive.as_output(), ctx.attrs.url, sha256 = ctx.attrs.sha256, size_bytes = ctx.attrs.size_bytes)
    manifest = ctx.actions.write("manifest.txt", "\n".join(sorted(ctx.attrs.files)) + "\n")
    out = ctx.actions.declare_output("tree", dir = True)
    ctx.actions.run(
        cmd_args(
            "/usr/bin/env",
            "python3",
            "-I",
            "-B",
            ctx.attrs._extract,
            "--archive",
            archive,
            "--top",
            ctx.attrs.top,
            "--dirs",
            ",".join(ctx.attrs.dirs),
            "--manifest",
            manifest,
            "--out",
            out.as_output(),
        ),
        category = "third_party_tree",
        identifier = ctx.label.name,
    )

    # One sub-target per manifest entry: an action that names `[library/aes.c]` has exactly that file
    # as input, never the whole release.
    subs = {path: [DefaultInfo(default_output = out.project(path))] for path in ctx.attrs.files}
    return [DefaultInfo(default_output = out, sub_targets = subs)]

third_party_tree = rule(
    impl = _tree_impl,
    attrs = {
        "dirs": attrs.list(attrs.string()),
        "files": attrs.list(attrs.string()),
        "sha256": attrs.string(),
        "size_bytes": attrs.int(),
        "top": attrs.string(),
        "url": attrs.string(),
        "_extract": attrs.source(default = "gate//third_party:extract.py"),
    },
)

def _symbols_impl(ctx: AnalysisContext) -> list[Provider]:
    subs = ctx.attrs.unit[DefaultInfo].sub_targets
    every = subs["objects"][DefaultInfo].sub_targets if "objects" in subs else {}
    objects = {name: unit for name, unit in every.items() if not name.endswith(".pic.o")}
    if len(objects) != ctx.attrs.expected_units:
        fail("{}: expected {} compiled units, the compiler produced {}".format(
            ctx.label, ctx.attrs.expected_units, len(objects),
        ))
    facts = ctx.actions.declare_output("symbols.json")
    cmd = cmd_args(
        "/usr/bin/env",
        "python3",
        "-I",
        "-B",
        ctx.attrs._script,
        "--label",
        _label_text(ctx.label, ctx.attrs.lib_name),
        "--nm",
        ctx.attrs._nm[RunInfo],
        "--cscan",
        ctx.attrs._cscan,
        "--out",
        facts.as_output(),
    )
    for name in sorted(objects.keys()):
        cmd.add("--unit", name, objects[name][DefaultInfo].default_outputs[0])
    ctx.actions.run(cmd, category = "third_party_symbols", identifier = ctx.label.name)
    return [DefaultInfo(default_output = facts)]

third_party_symbols = rule(
    impl = _symbols_impl,
    attrs = {
        "expected_units": attrs.int(),
        "lib_name": attrs.string(),
        "unit": attrs.dep(),
        "_nm": attrs.exec_dep(default = "toolchains//:llvm-nm", providers = [RunInfo]),
        "_cscan": attrs.source(default = "gate//gate/rigor_lib:cscan.py"),
        "_script": attrs.source(default = "gate//third_party:tp_facts.py"),
    },
)

_SAN = "-fsanitize=address,undefined,leak"
_FUZZ = "-fsanitize=fuzzer-no-link,address,undefined"
_MSAN = ["-fsanitize=memory", "-fsanitize-memory-track-origins=2"]

# The vendored code's own flags. No warning is an error here; nothing of the sealed product
# profile applies. The sanitizer modes instrument it, cov does not (vendor lines are not ours).
_MODE_FLAGS = {
    "toolchains//:release": ["-O2"],
    "toolchains//:san": ["-O1", "-g", _SAN, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:cov": ["-O2"],
    "toolchains//:fuzz": ["-O1", "-g", _FUZZ, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "toolchains//:msan": ["-O1", "-g"] + _MSAN + ["-fno-pie", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
}

_SAN_MODES = ["toolchains//:san", "toolchains//:fuzz"]

# The self-test's private copy of the library is never instrumented: two instrumented copies of the
# same code in one process are an ASan "odr-violation" by construction.
_MODE_FLAGS_PLAIN = {
    "toolchains//:release": ["-O2"],
    "toolchains//:san": ["-O1", "-g"],
    "toolchains//:cov": ["-O2"],
    "toolchains//:fuzz": ["-O1", "-g"],
    "toolchains//:msan": ["-O1", "-g"],
}

def c_third_party(
        name,
        url,
        sha256,
        size_bytes,
        top,
        dirs,
        files,
        srcs,
        own_srcs,
        private_headers,
        public_headers,
        config_header,
        config_macro,
        extra_headers = {},
        defines = [],
        symbols_in_every_mode = False,
        instrument = True,
        public_header_map = None,
        tree_input = False,
        no_sanitize = []):
    """A static library from a pinned tarball.

    `files`: the manifest (every `.c`/`.h` below `dirs`). `srcs`, `private_headers`, `public_headers`:
    paths in the manifest (public headers are exported with their `include/` prefix removed).
    `own_srcs`: gate-owned sources in this package (platform glue), compiled with the library.
    `symbols_in_every_mode`: `<name>_symbols` normally exists in release only (like every facts target);
    the self-test's private copy needs it in each mode.
    `instrument`: False builds the sanitizer modes without instrumentation (self-test copy only).
    `extra_headers`: further gate-owned exported headers (name -> source).
    `public_header_map`: exported header name -> path in the manifest, instead of the `include/` prefix
    strip (a library whose public headers keep their directory layout, like LVGL's `include/lvgl/...`).
    `tree_input`: the compile actions of the library get the whole unpacked tree as input and `-I` it, for
    sources that include siblings by relative path (`../misc/x.h`). The default (a sub-target per file,
    flat private headers) is what mbedTLS uses.
    `no_sanitize`: sanitizer checks switched off for THIS library's own objects in the san and fuzz modes, as
    `-fno-sanitize=<check>` (T114: LVGL gets `["function"]`, see docs/third-party.md). Nothing else is affected:
    every other check stays on for the library, and the flags never reach a user (they are not exported).
    `config_header`: the gate-owned configuration file in this package, exported as its own name and
    forced through `-D<config_macro>=<name>` on the library and on every user.
    """
    for path in srcs + private_headers + public_headers:
        if path not in files:
            fail("{}: {} is not in the manifest".format(name, path))
    src = name + "_src"
    third_party_tree(name = src, url = url, sha256 = sha256, size_bytes = size_bytes, top = top, dirs = dirs, files = files)

    def ref(path):
        return ":{}[{}]".format(src, path)

    if public_header_map:
        for path in public_header_map.values():
            if path not in files:
                fail("{}: {} is not in the manifest".format(name, path))
        exported = {n: ref(p) for n, p in public_header_map.items()}
    else:
        exported = {p[len("include/"):]: ref(p) for p in public_headers}
    exported[config_header] = config_header
    exported.update(extra_headers)
    flags = ["-D{}=<{}>".format(config_macro, config_header)] + defines
    mode_flags = _MODE_FLAGS if instrument else _MODE_FLAGS_PLAIN
    if no_sanitize:
        off = ["-fno-sanitize={}".format(c) for c in no_sanitize]
        mode_flags = {m: f + off if m in _SAN_MODES and instrument else f for m, f in mode_flags.items()}

    # `<name>_headers`: the public headers and the forced configuration, nothing to link.
    native.cxx_library(
        name = name + "_headers",
        exported_headers = exported,
        header_namespace = "",
        exported_header_style = "system",
        exported_preprocessor_flags = flags,
        visibility = ["PUBLIC"],
    )
    native.cxx_library(
        name = name,
        srcs = [ref(p) for p in srcs] + own_srcs,
        headers = {p.split("/")[-1]: ref(p) for p in private_headers},
        exported_deps = [":" + name + "_headers"],
        compiler_flags = select(mode_flags) + ["-std=c17", "-w"] +
                         (["-I$(location :{})".format(src)] if tree_input else []),
        link_style = "static",
        visibility = ["PUBLIC"],
    )
    third_party_symbols(
        name = name + "_symbols",
        lib_name = name,
        unit = ":" + name,
        expected_units = len(srcs) + len(own_srcs),
        target_compatible_with = [] if symbols_in_every_mode else ["toolchains//:release"],
        visibility = ["PUBLIC"],
    )
