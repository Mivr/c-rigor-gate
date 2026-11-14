"""T-G3: rules/apk_manifest.py, apk_pack.py and apk_check.py (pure parts), the pins of the SDK trees, and what `c_apk` cannot do.

The tools themselves (aapt2, zipalign, apksigner) run only on the RE farm: selftest/android.sh builds a real APK and breaks it.
"""

import importlib.util
import json
import os
import struct
import sys
import unittest
import zipfile
from pathlib import Path

from tests.helpers import TempDirTestCase

ROOT = Path(__file__).resolve().parent.parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "rules" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manifest, pack, check = load("apk_manifest"), load("apk_pack"), load("apk_check")
SPEC = {"label": "Club", "orientation": "landscape", "package": "org.example.club", "permissions": ["INTERNET"],
        "version_code": 7, "version_name": "1.2.3"}


class ManifestTest(unittest.TestCase):
    def test_the_rendered_manifest_has_the_fixed_attributes_and_the_declared_ones(self):
        text = manifest.render(SPEC, "libclub.so")
        for needle in ('package="org.example.club"', 'android:versionCode="7"', 'android:versionName="1.2.3"',
                       'android:minSdkVersion="28"', 'android:targetSdkVersion="35"', 'android:hasCode="false"',
                       'android:extractNativeLibs="false"', 'android:label="Club"', 'android:screenOrientation="landscape"',
                       'android:name="android.permission.INTERNET"', 'android:name="android.app.lib_name" android:value="club"',
                       'android:name="android.app.NativeActivity"'):
            self.assertIn(needle, text)
        self.assertEqual(text.count("<uses-permission"), 1)
        self.assertEqual(manifest.render(dict(SPEC, permissions=[]), "libclub.so").count("<uses-permission"), 0)

    def test_every_attribute_is_validated(self):
        bad = {"package": ["Org.example", "org", "org.1x", "org.a b", 'org.a"b', ".a.b", "a..b", "org.example." + "a" * 120],
               "label": ["", " x", 'a"b', "a<b", "a&b", "x" * 41, "é"],
               "version_name": ["", "1 2", '1"', "-1", "1" * 33],
               "version_code": [0, -1, 2100000001, "1", True, 1.5],
               "orientation": ["", "left", "landscape\" x=\"y"],
               "permissions": [["READ_SMS"], ["INTERNET", "INTERNET"], "INTERNET", ["android.permission.INTERNET"]]}
        for key, values in bad.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(SystemExit) as raised:
                        manifest.render(dict(SPEC, **{key: value}), "libclub.so")
                    self.assertIn("apk_manifest:", str(raised.exception))

    def test_only_the_declaration_keys_are_accepted(self):
        for spec in (dict(SPEC, extra=1), {k: v for k, v in SPEC.items() if k != "label"}, [], None):
            self.assertTrue(manifest.validate(spec))

    def test_the_object_name_is_lib_name_dot_so(self):
        for name in ("club.so", "libclub", "libClub.so", "lib.so", "lib-x.so", "libx.so.1", 'libx".so'):
            with self.subTest(name=name):
                with self.assertRaises(SystemExit):
                    manifest.render(SPEC, name)
        self.assertIn('android:value="a_b2"', manifest.render(SPEC, "liba_b2.so"))

    def test_main_writes_the_file(self):
        with open(os.path.join(os.environ.get("TMPDIR", "/tmp"), "apk_spec_%d.json" % os.getpid()), "w") as handle:
            json.dump(SPEC, handle)
            spec_path = handle.name
        out = spec_path + ".xml"
        try:
            self.assertEqual(manifest.main(["x", spec_path, "libclub.so", out]), 0)
            self.assertEqual(Path(out).read_text(), manifest.render(SPEC, "libclub.so"))
            with self.assertRaises(SystemExit):
                manifest.main(["x"])
        finally:
            for path in (spec_path, out):
                if os.path.exists(path):
                    os.unlink(path)


class PackTest(TempDirTestCase):
    def make(self, entries):
        path = self.tmp / "base.apk"
        with zipfile.ZipFile(path, "w") as z:
            for name, data in entries:
                z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        return path

    def test_the_library_is_added_after_the_base_entries_and_everything_is_stored_and_dated_the_same(self):
        base = self.make([("AndroidManifest.xml", b"m" * 500), ("resources.arsc", b"r" * 500)])
        lib = self.tmp / "libclub.so"
        lib.write_bytes(b"\x7fELF" + b"x" * 100)
        out = self.tmp / "out.apk"
        self.assertEqual(pack.main(["x", str(base), str(lib), str(out)]), 0)
        with zipfile.ZipFile(out) as z:
            infos = z.infolist()
            self.assertEqual([i.filename for i in infos], ["AndroidManifest.xml", "resources.arsc", "lib/arm64-v8a/libclub.so"])
            self.assertEqual({i.compress_type for i in infos}, {zipfile.ZIP_STORED})
            self.assertEqual({i.date_time for i in infos}, {(1980, 1, 1, 0, 0, 0)})
            self.assertEqual(z.read("AndroidManifest.xml"), b"m" * 500)
            self.assertEqual(z.read("lib/arm64-v8a/libclub.so"), lib.read_bytes())
        second = self.tmp / "out2.apk"
        pack.pack(str(base), str(lib), str(second))
        self.assertEqual(out.read_bytes(), second.read_bytes())    # a function of its inputs

    def test_a_base_with_a_directory_or_a_lib_entry_is_refused(self):
        lib = self.tmp / "libclub.so"
        lib.write_bytes(b"x")
        for name in ("lib/arm64-v8a/libother.so", "res/"):
            with self.subTest(name=name), self.assertRaises(SystemExit):
                pack.pack(str(self.make([(name, b"")])), str(lib), str(self.tmp / "o.apk"))
        with self.assertRaises(SystemExit):
            pack.main(["x"])


class CheckTest(TempDirTestCase):
    def test_the_entries_are_exactly_the_expected_ones(self):
        good = ["AndroidManifest.xml", "resources.arsc", "lib/arm64-v8a/libclub.so"]
        self.assertEqual(check.entry_problems(good, "libclub.so", []), [])
        self.assertEqual(check.entry_problems(good + ["assets/a.txt"], "libclub.so", ["a.txt"]), [])
        self.assertEqual(check.entry_problems(good + ["extra.txt"], "libclub.so", []), ["unexpected entry extra.txt"])
        self.assertEqual(check.entry_problems(good + ["META-INF/CERT.RSA"], "libclub.so", []), ["unexpected entry META-INF/CERT.RSA"])
        self.assertEqual(check.entry_problems(good[:2], "libclub.so", []), ["missing entry lib/arm64-v8a/libclub.so"])
        self.assertEqual(check.entry_problems(good + ["assets/a.txt"], "libclub.so", []), ["unexpected entry assets/a.txt"])
        self.assertEqual(check.entry_problems(good, "libclub.so", ["a.txt"]), ["missing entry assets/a.txt"])
        self.assertEqual(check.entry_problems(good + [good[0]], "libclub.so", []), ["repeated entry AndroidManifest.xml"])
        self.assertEqual(check.entry_problems(good + ["lib/armeabi-v7a/libclub.so", "lib/"], "libclub.so", []),
                         ["unexpected entry lib/", "unexpected entry lib/armeabi-v7a/libclub.so"])

    def test_the_data_offset_is_where_the_entry_bytes_start(self):
        path = self.tmp / "a.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(zipfile.ZipInfo("a.bin"), b"AAAA", compress_type=zipfile.ZIP_STORED)
            info = zipfile.ZipInfo("b.bin")
            info.extra = b"\xfe\xca\x04\x00" + b"\0\0\0\0"    # an 8-byte extra field, as zipalign writes padding
            z.writestr(info, b"BBBB", compress_type=zipfile.ZIP_STORED)
        raw = path.read_bytes()
        with zipfile.ZipFile(path) as z:
            for name, data in (("a.bin", b"AAAA"), ("b.bin", b"BBBB")):
                info = z.getinfo(name)
                at = check.data_offset(str(path), info)
                self.assertEqual(raw[at:at + 4], data)
            info = z.getinfo("a.bin")
            info.header_offset = 3
            self.assertIsNone(check.data_offset(str(path), info))

    def test_the_arguments_are_all_required(self):
        full = ["x", "--spec", "s", "--lib", "libclub.so", "--aapt2", "a", "--zipalign", "z", "--apksigner", "s",
                "--android-jar", "j", "--cert-sha256", "c", "--elf-check-py", "e", "--apk-manifest-py", "m", "--export", "f",
                "--asset", "a.txt", "--asset", "b.txt", "out.apk"]
        opts, apk = check.parse(full)
        self.assertEqual((apk, opts["export"], opts["asset"], opts["lib"]), ("out.apk", ["f"], ["a.txt", "b.txt"], "libclub.so"))
        for drop in ("--spec", "--lib", "--aapt2", "--zipalign", "--apksigner", "--android-jar", "--cert-sha256",
                     "--elf-check-py", "--apk-manifest-py", "--export"):
            at = full.index(drop)
            with self.subTest(drop=drop), self.assertRaises(SystemExit):
                check.parse(full[:at] + full[at + 2:])
        with self.assertRaises(SystemExit):
            check.parse(full[:-1])
        with self.assertRaises(SystemExit):
            check.parse(full + ["--release-key", "k"])
        with self.assertRaises(SystemExit):
            check.parse(full + ["second.apk"])

    def test_an_unreadable_archive_is_reported_not_crashed_on(self):
        bad = self.tmp / "bad.apk"
        bad.write_bytes(b"not a zip")
        spec = self.tmp / "spec.json"
        spec.write_text(json.dumps(SPEC))
        cert = self.tmp / "cert"
        cert.write_text("00\n")
        argv = ["x", "--spec", str(spec), "--lib", "libclub.so", "--aapt2", "a", "--zipalign", "z", "--apksigner", "s",
                "--android-jar", "j", "--cert-sha256", str(cert), "--elf-check-py", "e", "--apk-manifest-py", "m",
                "--export", "f", str(bad)]
        self.assertEqual(check.main(argv), 1)


class PinsTest(unittest.TestCase):
    """The SDK pins are those of the Rust kiosk's toolchains/android.bzl (owner-approved), nothing else."""

    PINS = (
        ("build-tools_r35_linux.zip", "bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88", "61958799"),
        ("platform-35_r02.zip", "0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0", "64273788"),
        ("OpenJDK21U-jdk_x64_linux_hotspot_21.0.6_7.tar.gz", "a2650fba422283fbed20d936ce5d2a52906a5414ec17b2f7676dddb87201dbae", "206861665"),
    )

    def test_the_urls_hashes_and_sizes_are_the_approved_ones(self):
        text = (ROOT / "toolchains" / "BUCK").read_text()
        for name, sha, size in self.PINS:
            at = text.index(name)
            block = text[text.rindex("\n\n", 0, at):text.index("\n)\n", at)]
            self.assertIn('sha256 = "%s"' % sha, block)
            self.assertIn("size_bytes = %s," % size, block)
        self.assertIn('https://dl.google.com/android/repository/build-tools_r35_linux.zip', text)
        self.assertIn('https://dl.google.com/android/repository/platform-35_r02.zip', text)
        self.assertIn("https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.6%2B7/", text)

    def test_the_trees_only_hold_the_members_c_apk_runs(self):
        text = (ROOT / "toolchains" / "BUCK").read_text()
        self.assertNotIn("TMPLIST", text)
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        for forbidden in ("src.zip", "ct.sym", "jmods", "bin/javac"):
            self.assertNotIn(forbidden, code)


class NoReleaseKeyTest(unittest.TestCase):
    """Release signing is out of scope: no argument, environment variable or file of a product reaches the signing step."""

    def test_the_rule_and_the_scripts_read_no_environment_and_take_no_key(self):
        for name in ("rules/apk.bzl", "rules/apk_manifest.py", "rules/apk_pack.py", "rules/apk_check.py"):
            text = (ROOT / name).read_text()
            for needle in ("getenv", "os.environ", "read_config", "read_root_config", "JAVA_HOME", "ANDROID_"):
                self.assertNotIn(needle, text, name)
        macro = (ROOT / "rules" / "c.bzl").read_text()
        head = macro[macro.index("def c_apk("):macro.index(")", macro.index("def c_apk("))]
        for forbidden in ("key", "sign", "release", "store", "pass"):
            self.assertNotIn(forbidden, head.lower())
        rule = (ROOT / "rules" / "apk.bzl").read_text().split("def _lab_impl")[0]     # the product rules, not the test lab
        self.assertEqual(rule.count("_keystore"), 2)          # declared once (a checked-in file), used once
        self.assertIn('"toolchains//:android_debug.keystore"', rule)
        self.assertEqual(rule.count('"pass:android"'), 2)

    def test_the_debug_key_is_marked_and_its_certificate_digest_is_pinned(self):
        digest = (ROOT / "toolchains" / "android_debug.cert.sha256").read_text().strip()
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual((ROOT / "toolchains" / "android_debug.keystore").read_bytes()[:1], b"\x30")   # a DER (PKCS#12) file
        self.assertIn("TEST-ONLY", (ROOT / "rules" / "apk.bzl").read_text())
        self.assertIn("TEST-ONLY", (ROOT / "docs" / "products.md").read_text())


if __name__ == "__main__":
    unittest.main()
