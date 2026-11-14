"""`c_apk` support: the signed APK and its check (see `c_apk` in rules/c.bzl).

Actions, all on RE with the pinned SDK (toolchains//:android_build_tools, :android_platform, :jdk):
  1. manifest   rules/apk_manifest.py renders AndroidManifest.xml from the validated declaration;
  2. link       `aapt2 link` against the platform android.jar (and the assets, if any) -> the base APK;
  2b. java      (java_srcs only) rules/apk_java.py: javac of the pinned JDK against android.jar (-Werror, no processors), then the pinned d8
                (--min-api 28) -> classes.dex; (res_xml only) `aapt2 compile` of res/xml/*.xml, linked with -R;
  3. pack       rules/apk_pack.py adds classes.dex (java_srcs only) and `lib/arm64-v8a/lib<name>.so`, every entry STORED;
  4. align      `zipalign -f -P 16 4` page-aligns the stored object;
  5. sign       `apksigner sign --alignment-preserved` (it must not move what zipalign placed) with the checked-in TEST-ONLY debug key (toolchains/android_debug.keystore, public password
                `android`, its certificate digest in toolchains/android_debug.cert.sha256). Release signing does not exist
                here: the macro has no signing argument, nothing reads an environment variable, and the check refuses any
                APK whose signer is not the debug key.
`<name>_check` runs rules/apk_check.py on the result (a build action that fails when the APK is not acceptable) and is
also a runnable command: `buck2 run //pkg:<name>_check -- OTHER.apk`.
"""

load("@gate//rules:android.bzl", "AndroidSoInfo")

ApkInfo = provider(fields = {"apk": Artifact, "assets": list[str], "exports": list[str], "java_srcs": list[Artifact], "lib": str, "spec": Artifact})

_ENTRY = "ANativeActivity_onCreate"
_PY = ["/usr/bin/env", "python3", "-I", "-B"]

def _as_command(run_info):
    """One argument holding a whole command line (the check script splits it), for a tool given as RunInfo."""
    return cmd_args(run_info, delimiter = " ")

def _apk_impl(ctx: AnalysisContext) -> list[Provider]:
    so = ctx.attrs.so[DefaultInfo].default_outputs[0]
    exports = ctx.attrs.so[AndroidSoInfo].exports
    if exports != [_ENTRY]:
        fail("{}: the shared object must export exactly {} (a NativeActivity), it exports {}".format(ctx.label, _ENTRY, exports))
    spec = ctx.actions.write_json("spec.json", {
        "activity": {
            "categories": ctx.attrs.categories,
            "exclude_from_recents": ctx.attrs.exclude_from_recents,
            "launch_mode": ctx.attrs.launch_mode,
            "lock_task_mode": ctx.attrs.lock_task_mode,
            "soft_input_mode": ctx.attrs.soft_input_mode,
        },
        "application_class": ctx.attrs.application_class,
        "java_classes": ctx.attrs.java_classes,
        "label": ctx.attrs.label,
        "orientation": ctx.attrs.orientation,
        "package": ctx.attrs.package,
        "permissions": ctx.attrs.permissions,
        "receivers": ctx.attrs.receivers,
        "res_xml": ctx.attrs.res_xml_names,
        "version_code": ctx.attrs.version_code,
        "version_name": ctx.attrs.version_name,
    })
    android_jar = ctx.attrs._platform[DefaultInfo].default_outputs[0].project("android-35/android.jar")

    manifest = ctx.actions.declare_output("AndroidManifest.xml")
    ctx.actions.run(
        cmd_args(_PY, ctx.attrs._manifest, spec, so.basename, manifest.as_output()),
        category = "apk_manifest",
        identifier = ctx.label.name,
    )

    base = ctx.actions.declare_output("base.apk")
    link = cmd_args(ctx.attrs._aapt2[RunInfo], "link", "-I", android_jar, "--manifest", manifest, "-o", base.as_output())
    if ctx.attrs.assets:
        assets = ctx.actions.copied_dir("assets", {name: src for name, src in zip(ctx.attrs.asset_names, ctx.attrs.assets)})
        link.add("-A", assets)
    if ctx.attrs.res_xml:
        res = ctx.actions.copied_dir("res", {"xml/" + name: src for name, src in zip(ctx.attrs.res_xml_names, ctx.attrs.res_xml)})
        compiled = ctx.actions.declare_output("res.zip")
        ctx.actions.run(
            cmd_args(ctx.attrs._aapt2[RunInfo], "compile", "--dir", res, "-o", compiled.as_output()),
            category = "apk_res",
            identifier = ctx.label.name,
        )
        link.add("-R", compiled)
    ctx.actions.run(link, category = "apk_link", identifier = ctx.label.name)

    pack = cmd_args(_PY, ctx.attrs._pack)
    dex = None
    if ctx.attrs.java_srcs:
        dex = ctx.actions.declare_output("classes.dex")
        ctx.actions.run(
            cmd_args(
                _PY,
                ctx.attrs._java,
                "--javac", _as_command(ctx.attrs._javac[RunInfo]),
                "--d8", _as_command(ctx.attrs._d8[RunInfo]),
                "--android-jar", android_jar,
                "--min-api", "28",
                "--out", dex.as_output(),
                ctx.attrs.java_srcs,
            ),
            category = "apk_java",
            identifier = ctx.label.name,
        )

    packed = ctx.actions.declare_output("packed.apk")
    pack.add(base, so, packed.as_output())
    if dex:
        pack.add(dex)
    ctx.actions.run(
        pack,
        category = "apk_pack",
        identifier = ctx.label.name,
    )

    aligned = ctx.actions.declare_output("aligned.apk")
    ctx.actions.run(
        cmd_args(ctx.attrs._zipalign[RunInfo], "-f", "-P", "16", "4", packed, aligned.as_output()),
        category = "apk_align",
        identifier = ctx.label.name,
    )

    out = ctx.actions.declare_output(ctx.attrs.apk_name)
    ctx.actions.run(
        cmd_args(
            ctx.attrs._apksigner[RunInfo],
            "sign",
            "--ks", ctx.attrs._keystore,
            "--ks-pass", "pass:android",
            "--ks-key-alias", "androiddebugkey",
            "--key-pass", "pass:android",
            "--min-sdk-version", "28",
            "--alignment-preserved", "true",
            "--v1-signing-enabled", "false",
            "--v2-signing-enabled", "true",
            "--v3-signing-enabled", "true",
            "--v4-signing-enabled", "false",
            "--out", out.as_output(),
            aligned,
        ),
        category = "apk_sign",
        identifier = ctx.label.name,
    )
    return [DefaultInfo(default_output = out), ApkInfo(apk = out, exports = exports, java_srcs = ctx.attrs.java_srcs, spec = spec, lib = so.basename, assets = ctx.attrs.asset_names)]

apk = rule(
    impl = _apk_impl,
    attrs = {
        "apk_name": attrs.string(),
        "application_class": attrs.string(default = ""),
        "asset_names": attrs.list(attrs.string(), default = []),
        "assets": attrs.list(attrs.source(), default = []),
        "categories": attrs.list(attrs.string(), default = []),
        "exclude_from_recents": attrs.bool(default = False),
        "java_classes": attrs.list(attrs.string(), default = []),
        "java_srcs": attrs.list(attrs.source(), default = []),
        "label": attrs.string(),
        "launch_mode": attrs.string(default = ""),
        "lock_task_mode": attrs.string(default = ""),
        "orientation": attrs.string(),
        "package": attrs.string(),
        "permissions": attrs.list(attrs.string(), default = []),
        "receivers": attrs.list(attrs.dict(attrs.string(), attrs.any()), default = []),
        "res_xml": attrs.list(attrs.source(), default = []),
        "res_xml_names": attrs.list(attrs.string(), default = []),
        "so": attrs.dep(providers = [AndroidSoInfo]),
        "soft_input_mode": attrs.string(default = ""),
        "version_code": attrs.int(),
        "version_name": attrs.string(),
        "_aapt2": attrs.exec_dep(default = "toolchains//:aapt2", providers = [RunInfo]),
        "_apksigner": attrs.exec_dep(default = "toolchains//:apksigner", providers = [RunInfo]),
        "_d8": attrs.exec_dep(default = "toolchains//:d8", providers = [RunInfo]),
        "_java": attrs.source(default = "gate//rules:apk_java.py"),
        "_javac": attrs.exec_dep(default = "toolchains//:javac", providers = [RunInfo]),
        "_keystore": attrs.source(default = "toolchains//:android_debug.keystore"),
        "_manifest": attrs.source(default = "gate//rules:apk_manifest.py"),
        "_pack": attrs.source(default = "gate//rules:apk_pack.py"),
        "_platform": attrs.exec_dep(default = "toolchains//:android_platform"),
        "_zipalign": attrs.exec_dep(default = "toolchains//:zipalign"),
    },
)

def _check_impl(ctx: AnalysisContext) -> list[Provider]:
    info = ctx.attrs.apk[ApkInfo]
    android_jar = ctx.attrs._platform[DefaultInfo].default_outputs[0].project("android-35/android.jar")
    command = cmd_args(
        _PY,
        ctx.attrs._check,
        "--spec", info.spec,
        "--lib", info.lib,
        "--aapt2", _as_command(ctx.attrs._aapt2[RunInfo]),
        "--zipalign", _as_command(ctx.attrs._zipalign[RunInfo]),
        "--apksigner", _as_command(ctx.attrs._apksigner[RunInfo]),
        "--android-jar", android_jar,
        "--cert-sha256", ctx.attrs._cert,
        "--elf-check-py", ctx.attrs._elf_check,
        "--apk-manifest-py", ctx.attrs._manifest,
    )
    for symbol in info.exports:
        command.add("--export", symbol)
    for name in info.assets:
        command.add("--asset", name)
    out = ctx.actions.declare_output("check.txt")
    run = cmd_args(command)
    run.add(info.apk, "--out", out.as_output())
    ctx.actions.run(run, category = "apk_check", identifier = ctx.label.name)
    return [DefaultInfo(default_output = out, sub_targets = {"run": [DefaultInfo(), RunInfo(args = command)]})]

apk_check = rule(
    impl = _check_impl,
    attrs = {
        "apk": attrs.dep(providers = [ApkInfo]),
        "_aapt2": attrs.exec_dep(default = "toolchains//:aapt2", providers = [RunInfo]),
        "_apksigner": attrs.exec_dep(default = "toolchains//:apksigner", providers = [RunInfo]),
        "_cert": attrs.source(default = "toolchains//:android_debug.cert.sha256"),
        "_check": attrs.source(default = "gate//rules:apk_check.py"),
        "_elf_check": attrs.source(default = "gate//rules:elf_check.py"),
        "_manifest": attrs.source(default = "gate//rules:apk_manifest.py"),
        "_platform": attrs.exec_dep(default = "toolchains//:android_platform"),
        "_zipalign": attrs.exec_dep(default = "toolchains//:zipalign"),
    },
)

def _lab_impl(ctx: AnalysisContext) -> list[Provider]:
    """Test tooling (selftest/android.sh): breaks the APK of `apk` (ways of apk_lab.py; the Java ones when `apk` has java_srcs) inside one RE action and demands that apk_check refuses each."""
    info = ctx.attrs.apk[ApkInfo]
    android_jar = ctx.attrs._platform[DefaultInfo].default_outputs[0].project("android-35/android.jar")
    out = ctx.actions.declare_output("lab.txt")
    ctx.actions.run(
        cmd_args(
            _PY,
            ctx.attrs._lab,
            "--apk", info.apk,
            "--spec", info.spec,
            "--lib", info.lib,
            "--wide", ctx.attrs.wide[DefaultInfo].default_outputs[0],
            "--android-jar", android_jar,
            "--cert-sha256", ctx.attrs._cert,
            "--keystore", ctx.attrs._keystore,
            "--aapt2", _as_command(ctx.attrs._aapt2[RunInfo]),
            "--zipalign", _as_command(ctx.attrs._zipalign[RunInfo]),
            "--apksigner", _as_command(ctx.attrs._apksigner[RunInfo]),
            "--keytool", _as_command(ctx.attrs._keytool[RunInfo]),
            "--apk-check-py", ctx.attrs._check,
            "--elf-check-py", ctx.attrs._elf_check,
            "--apk-manifest-py", ctx.attrs._manifest,
            "--apk-java-py", ctx.attrs._java,
            "--javac", _as_command(ctx.attrs._javac[RunInfo]),
            "--d8", _as_command(ctx.attrs._d8[RunInfo]),
            "--out", out.as_output(),
            info.java_srcs,
        ),
        category = "apk_lab",
        identifier = ctx.label.name,
    )
    return [DefaultInfo(default_output = out)]

apk_lab = rule(
    impl = _lab_impl,
    attrs = {
        "apk": attrs.dep(providers = [ApkInfo]),
        "wide": attrs.dep(providers = [AndroidSoInfo]),
        "_aapt2": attrs.exec_dep(default = "toolchains//:aapt2", providers = [RunInfo]),
        "_apksigner": attrs.exec_dep(default = "toolchains//:apksigner", providers = [RunInfo]),
        "_cert": attrs.source(default = "toolchains//:android_debug.cert.sha256"),
        "_check": attrs.source(default = "gate//rules:apk_check.py"),
        "_d8": attrs.exec_dep(default = "toolchains//:d8", providers = [RunInfo]),
        "_elf_check": attrs.source(default = "gate//rules:elf_check.py"),
        "_java": attrs.source(default = "gate//rules:apk_java.py"),
        "_javac": attrs.exec_dep(default = "toolchains//:javac", providers = [RunInfo]),
        "_keystore": attrs.source(default = "toolchains//:android_debug.keystore"),
        "_keytool": attrs.exec_dep(default = "toolchains//:keytool", providers = [RunInfo]),
        "_lab": attrs.source(default = "gate//rules:apk_lab.py"),
        "_manifest": attrs.source(default = "gate//rules:apk_manifest.py"),
        "_platform": attrs.exec_dep(default = "toolchains//:android_platform"),
        "_zipalign": attrs.exec_dep(default = "toolchains//:zipalign"),
    },
)
