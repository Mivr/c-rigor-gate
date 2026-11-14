"""The APK self-test of selftest/android.sh, run as one action on an RE worker (stdlib only; test tooling, not a product rule).

    apk_lab.py --apk APK --spec SPEC.json --lib libNAME.so --wide WIDE.so --android-jar JAR --cert-sha256 FILE --keystore KS
               --aapt2 CMD --zipalign CMD --apksigner CMD --keytool CMD
               --apk-check-py F --elf-check-py F --apk-manifest-py F --apk-java-py F --javac CMD --d8 CMD --out LOG [SRC.java...]

It reads the real APK back with the pinned tools, then breaks it and demands that `apk_check.py` refuses each break for its own
single reason: five ways for an APK without Java; for an APK with `java_srcs` (the trailing SRC.java files) the Java ways (T-G3b):
a dex with an extra class, a dex that lacks a declared class, a corrupt dex, a missing classes.dex, an undeclared res file, and a
manifest with an undeclared receiver (the declaration is tampered with, the APK is the real one). It runs on RE because the build-tools files cannot be reliably downloaded to a client from the farm
(docs/toolchain.md, "Known limitation"). Exit 0 and LOG written only if every step holds; otherwise the failing step is
printed. The file names and arguments mirror rules/apk_check.py.
"""

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile

KEYS = ("apk", "spec", "lib", "wide", "android-jar", "cert-sha256", "keystore", "aapt2", "zipalign", "apksigner", "keytool",
        "apk-check-py", "elf-check-py", "apk-manifest-py", "apk-java-py", "javac", "d8", "out")
LOG = []


def say(text):
    LOG.append(text)
    print(text, flush=True)


def run(command, *args, check=True):
    done = subprocess.run(shlex.split(command) + [str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, check=False)
    text = done.stdout.decode("utf-8", "replace")
    if check and done.returncode != 0:
        sys.exit("FAIL: %s %s exited %d:\n%s" % (command.split()[-1], " ".join(map(str, args))[:200], done.returncode, text[-1500:]))
    return done.returncode, text


class Lab:
    def __init__(self, opts, scratch):
        self.o, self.dir = opts, scratch
        with open(opts["spec"], encoding="utf-8") as handle:
            self.spec = json.load(handle)
        with open(opts["cert-sha256"], encoding="utf-8") as handle:
            self.cert = handle.read().strip()
        self.lib = opts["lib"]
        self.entry = "lib/arm64-v8a/" + self.lib

    def path(self, name):
        return os.path.join(self.dir, name)

    def check(self, apk, *extra, spec=None, exports=("ANativeActivity_onCreate",)):
        spec_file = self.o["spec"]
        if spec is not None:
            spec_file = self.path("spec_other.json")
            with open(spec_file, "w", encoding="utf-8") as handle:
                json.dump(spec, handle)
        args = ["python3", "-I", "-B", self.o["apk-check-py"], "--spec", spec_file, "--lib", self.lib,
                "--aapt2", self.o["aapt2"], "--zipalign", self.o["zipalign"], "--apksigner", self.o["apksigner"],
                "--android-jar", self.o["android-jar"], "--cert-sha256", self.o["cert-sha256"],
                "--elf-check-py", self.o["elf-check-py"], "--apk-manifest-py", self.o["apk-manifest-py"]]
        for symbol in exports:
            args += ["--export", symbol]
        done = subprocess.run(args + list(extra) + [apk], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        text = done.stdout.decode("utf-8", "replace")
        found = re.findall(r"^  \[([a-z]+)\] (.*)$", text, re.M)
        return done.returncode, ["%s: %s" % pair for pair in found], text

    def refused(self, name, apk, pattern, **kw):
        code, problems, text = self.check(apk, **kw)
        if code == 0:
            sys.exit("FAIL: %s was accepted" % name)
        if len(problems) != 1 or not re.search(pattern, problems[0]):
            sys.exit("FAIL: %s: wanted exactly one problem matching /%s/, got %s\n%s" % (name, pattern, problems, text))
        say("  %s refused: %s" % (name, problems[0][:150]))

    def sign(self, src, dst, keystore=None, alias="androiddebugkey"):
        run(self.o["apksigner"], "sign", "--ks", keystore or self.o["keystore"], "--ks-pass", "pass:android", "--ks-key-alias", alias,
            "--key-pass", "pass:android", "--min-sdk-version", "28", "--alignment-preserved", "true",
            "--v1-signing-enabled", "false", "--v4-signing-enabled", "false", "--out", dst, src)

    def align(self, src, dst):
        run(self.o["zipalign"], "-f", "-P", "16", "4", src, dst)

    def repack(self, dst, replace=None, add=None, drop=()):
        """The real APK with entries replaced (name -> bytes), added or dropped, aligned and signed with the debug key."""
        raw, aligned = self.path("repack_raw.apk"), self.path("repack_aligned.apk")
        info = zipfile.ZipInfo
        def entry(name):
            item = info(name, (1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_STORED
            item.external_attr = 0o644 << 16
            return item
        with zipfile.ZipFile(self.o["apk"]) as zin, zipfile.ZipFile(raw, "w") as zout:
            for item in zin.infolist():
                if item.filename not in drop:
                    zout.writestr(entry(item.filename), (replace or {}).get(item.filename, zin.read(item)))
            for name, data in (add or {}).items():
                zout.writestr(entry(name), data)
        self.align(raw, aligned)
        self.sign(aligned, dst)

    def rewrite(self, mode, dst, swap=None):
        def entry(name):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            return info
        with zipfile.ZipFile(self.o["apk"]) as zin, zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info)
                if swap and info.filename == self.entry:
                    data = open(swap, "rb").read()
                zout.writestr(entry(info.filename), data)
            if mode == "extra":
                zout.writestr(entry("assets/extra.txt"), b"not declared\n")

    def read_back(self):
        apk = self.o["apk"]
        code, text = run(self.o["zipalign"], "-c", "-P", "16", "-v", "4", apk)
        if "%s (OK)" % self.entry not in text:
            sys.exit("FAIL: the object is not reported aligned:\n" + text)
        _, text = run(self.o["apksigner"], "verify", "--verbose", "--print-certs", "--min-sdk-version", "28", apk)
        if "Number of signers: 1" not in text or ("Signer #1 certificate SHA-256 digest: " + self.cert) not in text:
            sys.exit("FAIL: not one signer, or not the debug key:\n" + text)
        _, badging = run(self.o["aapt2"], "dump", "badging", apk)
        spec = self.spec
        for want in ("package: name='%s' versionCode='%d' versionName='%s'" % (spec["package"], spec["version_code"], spec["version_name"]),
                     "minSdkVersion:'28'", "targetSdkVersion:'35'", "application: label='%s'" % spec["label"],
                     "native-code: 'arm64-v8a'", "launchable-activity: name='android.app.NativeActivity'"):
            if want not in badging:
                sys.exit("FAIL: badging lacks %s:\n%s" % (want, badging))
        if bool(spec["permissions"]) != ("uses-permission" in badging):
            sys.exit("FAIL: badging permissions differ from the declaration:\n" + badging)
        with zipfile.ZipFile(apk) as z:
            names = sorted(i.filename for i in z.infolist())
            if names != sorted(["AndroidManifest.xml", "resources.arsc", self.entry]) or z.getinfo(self.entry).compress_type != zipfile.ZIP_STORED:
                sys.exit("FAIL: wrong entries %s" % names)
        code, _, text = self.check(apk)
        if code != 0:
            sys.exit("FAIL: apk_check refuses the real APK:\n" + text)
        say("  read back with zipalign, apksigner, aapt2 and apk_check: all hold; entries %s" % names)

    def alignment_extra_manifest(self):
        apk = self.o["apk"]
        raw, unaligned = self.path("unaligned_raw.apk"), self.path("unaligned.apk")
        self.rewrite("unaligned", raw)
        self.sign(raw, unaligned)
        if run(self.o["zipalign"], "-c", "-P", "16", "4", unaligned, check=False)[0] == 0:
            sys.exit("FAIL: the rewritten APK is aligned after all")
        run(self.o["apksigner"], "verify", "--min-sdk-version", "28", unaligned)
        code, problems, text = self.check(unaligned)
        kinds = sorted(p.split(":")[0] for p in problems)
        if code == 0 or kinds != ["library", "zipalign"] or not re.search(r"data starts at .*not a multiple of 16384", " ".join(problems)):
            sys.exit("FAIL: the misaligned APK was not refused for exactly its two alignment problems: %s\n%s" % (problems, text))
        say("  misaligned: " + "; ".join(p[:110] for p in problems))
        raw2, aligned2, extra = self.path("extra_raw.apk"), self.path("extra_aligned.apk"), self.path("extra.apk")
        self.rewrite("extra", raw2)
        self.align(raw2, aligned2)
        self.sign(aligned2, extra)
        self.refused("extra_file", extra, r"^entries: unexpected entry assets/extra.txt$")
        other = dict(self.spec, version_code=self.spec["version_code"] + 1)
        self.refused("other_manifest", apk, r"^manifest: the manifest differs from the declaration at line", spec=other)

    def exports_and_keys(self):
        apk = self.o["apk"]
        raw, aligned, wide = self.path("wide_raw.apk"), self.path("wide_aligned.apk"), self.path("wide.apk")
        self.rewrite("swap", raw, swap=self.o["wide"])
        self.align(raw, aligned)
        self.sign(aligned, wide)
        self.refused("extra_export", wide, r"^library: %s: exports extra_symbol, which is not in the allowed export list$" % re.escape(self.lib))
        code, problems, text = self.check(apk, exports=("other_entry",))
        want = sorted(["library: %s: does not define the export other_entry" % self.lib,
                       "library: %s: exports ANativeActivity_onCreate, which is not in the allowed export list" % self.lib])
        if code == 0 or sorted(problems) != want:
            sys.exit("FAIL: wrong problems for a wrong export list: %s\n%s" % (problems, text))
        say("  wrong export list refused: both the missing and the unexpected export reported")
        store = self.path("other.keystore")
        run(self.o["keytool"], "-genkeypair", "-keystore", store, "-storetype", "PKCS12", "-storepass", "android", "-keypass", "android",
            "-alias", "otherkey", "-keyalg", "RSA", "-keysize", "2048", "-validity", "3650", "-dname", "CN=another key")
        other = self.path("other_key.apk")
        self.sign(apk, other, keystore=store, alias="otherkey")
        run(self.o["apksigner"], "verify", "--min-sdk-version", "28", other)
        say("  (apksigner verify alone accepts the APK signed by another key; only the pinned certificate says no)")
        self.refused("other_key", other, r"^signature: signer certificate SHA-256 is \[")
        raw_bytes = bytearray(open(apk, "rb").read())
        with zipfile.ZipFile(apk) as z:
            info = z.getinfo("AndroidManifest.xml")
            at = info.header_offset + 30 + len(info.filename) + len(info.extra) + info.file_size // 2
        raw_bytes[at] ^= 0xFF
        tampered = self.path("tampered.apk")
        with open(tampered, "wb") as handle:
            handle.write(raw_bytes)
        code, problems, text = self.check(tampered)
        if code == 0 or not any(p.startswith("signature: apksigner verify refused it") for p in problems):
            sys.exit("FAIL: the tampering was not caught by the signature: %s\n%s" % (problems, text))
        say("  tampered: signature refused")


class JavaLab(Lab):
    """The Java ways (T-G3b): the APK has java_srcs, a res/xml file and receivers."""

    def __init__(self, opts, scratch, sources):
        super().__init__(opts, scratch)
        self.sources = sources
        spec = importlib.util.spec_from_file_location("apk_java", opts["apk-java-py"])
        self.java = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.java)
        self.classes = self.spec["java_classes"]
        self.res = ["res/xml/" + r for r in self.spec["res_xml"]]

    def build_dex(self, tag, sources, skip=()):
        scratch = self.path("dex_" + tag)
        os.mkdir(scratch)
        o = self.o
        with open(self.java.build(o["javac"], o["d8"], o["android-jar"], "28", sources, scratch, skip), "rb") as handle:
            return handle.read()

    def read_back_java(self):
        apk = self.o["apk"]
        _, badging = run(self.o["aapt2"], "dump", "badging", apk)
        for want in ("package: name='%s'" % self.spec["package"], "application: label='%s'" % self.spec["label"], "native-code: 'arm64-v8a'"):
            if want not in badging:
                sys.exit("FAIL: badging lacks %s:\n%s" % (want, badging))
        _, xml = run(self.o["aapt2"], "dump", "xmltree", "--file", "AndroidManifest.xml", apk)
        for want in ('E: receiver', 'A: http://schemas.android.com/apk/res/android:hasCode(0x0101000c)=true', 'android.intent.category.HOME',
                     'A: http://schemas.android.com/apk/res/android:lockTaskMode'):
            if want not in xml:
                sys.exit("FAIL: the manifest lacks %s:\n%s" % (want, xml))
        with zipfile.ZipFile(apk) as z:
            names = sorted(i.filename for i in z.infolist())
            if names != sorted(["AndroidManifest.xml", "resources.arsc", "classes.dex", self.entry] + self.res):
                sys.exit("FAIL: wrong entries %s" % names)
            self.dex = z.read("classes.dex")
        code, _, text = self.check(apk)
        if code != 0:
            sys.exit("FAIL: apk_check refuses the real APK:\n" + text)
        say("  read back with aapt2 and apk_check: all hold; entries %s" % names)

    def cases(self):
        apk, name = self.o["apk"], self.path
        extra = name("Extra.java")
        with open(extra, "w", encoding="utf-8") as handle:
            handle.write("package %s;\n\npublic final class Extra {\n}\n" % self.spec["package"])
        self.repack(name("extra_class.apk"), replace={"classes.dex": self.build_dex("extra", self.sources + [extra])})
        self.refused("extra_class", name("extra_class.apk"), r"^dex: classes.dex defines %s\.Extra, which is not a declared class$" % re.escape(self.spec["package"]))
        gone = self.classes[-1]
        self.repack(name("missing_class.apk"), replace={"classes.dex": self.build_dex("missing", self.sources, skip=(gone.replace(".", "/") + ".class",))})
        self.refused("missing_class", name("missing_class.apk"), r"^dex: classes.dex does not define the declared class %s$" % re.escape(gone))
        broken = bytearray(self.dex)
        broken[-1] ^= 0xFF
        self.repack(name("corrupt_dex.apk"), replace={"classes.dex": bytes(broken)})
        self.refused("corrupt_dex", name("corrupt_dex.apk"), r"^dex: classes.dex: bad dex checksum$")
        self.repack(name("no_dex.apk"), drop=("classes.dex",))
        self.refused("no_dex", name("no_dex.apk"), r"^entries: missing entry classes.dex$")
        self.repack(name("extra_res.apk"), add={"res/xml/extra.xml": b"<x/>"})
        self.refused("extra_res", name("extra_res.apk"), r"^entries: unexpected entry res/xml/extra.xml$")
        fewer = dict(self.spec, receivers=self.spec["receivers"][:-1])
        self.refused("undeclared_receiver", apk, r"^manifest: the manifest differs from the declaration at line", spec=fewer)
        say("  (the declaration without the last receiver is a valid declaration: only the manifest of the APK differs)")


def main(argv):
    opts, sources, args = {}, [], list(argv[1:])
    while args:
        key = args.pop(0)
        if key.endswith(".java") and not key.startswith("--"):
            sources.append(key)
        elif not key.startswith("--") or key[2:] not in KEYS or not args:
            sys.exit(__doc__)
        else:
            opts[key[2:]] = args.pop(0)
    if sorted(opts) != sorted(KEYS):
        sys.exit(__doc__)
    with tempfile.TemporaryDirectory() as scratch:
        with open(opts["spec"], encoding="utf-8") as handle:
            java = bool(json.load(handle).get("java_classes"))
        if java != bool(sources):
            sys.exit("FAIL: the sources of a Java APK (and only those) must be given")
        if java:
            lab = JavaLab(opts, scratch, sources)
            lab.read_back_java()
            lab.cases()
        else:
            lab = Lab(opts, scratch)
            lab.read_back()
            lab.alignment_extra_manifest()
            lab.exports_and_keys()
    with open(opts["out"], "w", encoding="utf-8") as handle:
        handle.write("\n".join(LOG) + "\nAPK LAB PASSED\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
