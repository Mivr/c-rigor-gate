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
import zlib
from pathlib import Path

from tests.helpers import TempDirTestCase

ROOT = Path(__file__).resolve().parent.parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "rules" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manifest, pack, check, java = load("apk_manifest"), load("apk_pack"), load("apk_check"), load("apk_java")
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


JAVA = dict(SPEC, permissions=["RECEIVE_BOOT_COMPLETED"], java_classes=["org.example.club.A", "org.example.club.A$App", "org.example.club.A$Boot"],
            res_xml=["device_admin.xml"], application_class="org.example.club.A$App",
            receivers=[{"name": "org.example.club.A", "permission": "BIND_DEVICE_ADMIN", "exported": True, "actions": ["DEVICE_ADMIN_ENABLED"],
                        "meta_data": {"android.app.device_admin": "device_admin"}},
                       {"name": "org.example.club.A$Boot", "permission": "", "exported": True, "actions": ["BOOT_COMPLETED"], "meta_data": {}}],
            activity={"launch_mode": "singleTask", "lock_task_mode": "if_whitelisted", "exclude_from_recents": True,
                      "soft_input_mode": "stateHidden", "categories": ["HOME", "DEFAULT"]})


class JavaManifestTest(unittest.TestCase):
    def test_without_java_the_manifest_is_the_old_one(self):
        text = manifest.render(SPEC, "libclub.so")
        self.assertIn('android:hasCode="false"', text)
        for needle in ("<receiver", "android:launchMode", "android:lockTaskMode", "android:excludeFromRecents", "windowSoftInputMode",
                       "category.HOME", "category.DEFAULT", 'android:name="org'):
            self.assertNotIn(needle, text)
        self.assertEqual(text, manifest.render(dict(SPEC, java_classes=[], res_xml=[], receivers=[], application_class=""), "libclub.so"))

    def test_the_declarations_render(self):
        text = manifest.render(JAVA, "libclub.so")
        for needle in ('android:hasCode="true"', 'android:name="org.example.club.A$App"', 'android:launchMode="singleTask"',
                       'android:lockTaskMode="if_whitelisted"', 'android:excludeFromRecents="true"',
                       'android:windowSoftInputMode="stateHidden"', 'android:name="android.intent.category.HOME"',
                       'android:name="android.intent.category.DEFAULT"', 'android:permission="android.permission.BIND_DEVICE_ADMIN"',
                       'android:name="android.app.action.DEVICE_ADMIN_ENABLED"', 'android:name="android.intent.action.BOOT_COMPLETED"',
                       'android:name="android.app.device_admin" android:resource="@xml/device_admin"',
                       'android:name="android.permission.RECEIVE_BOOT_COMPLETED"'):
            self.assertIn(needle, text)
        self.assertEqual(text.count("<receiver"), 2)
        self.assertEqual(text.count("android:permission="), 1)
        self.assertEqual(manifest.render(dict(JAVA, receivers=[JAVA["receivers"][1]]), "libclub.so").count("<receiver"), 1)

    def test_every_java_declaration_is_closed(self):
        r0, r1 = JAVA["receivers"]
        activity = JAVA["activity"]
        bad = {
            "java_classes": [["Other.A"], ["org.example.club.A", "org.example.club.A"], "org.example.club.A", ["org.example.club.A b"],
                             ['org.example.club.A"x'], ["org.example.club."], ["org.example.clubx.A"], [1]],
            "res_xml": [["a/b.xml"], ["A.xml"], ["a.xml", "a.xml"], "a.xml", ["a.txt"], ["x" * 41 + ".xml"]],
            "application_class": ["org.example.club.Missing", 5, "org.example.club.A b"],
            "receivers": [[dict(r0, name="org.example.club.Missing")], [dict(r0, permission="BIND_ACCESSIBILITY_SERVICE")],
                          [dict(r0, exported="true")], [dict(r0, actions=["BOOT_COMPLETED", "BOOT_COMPLETED"])],
                          [dict(r0, actions=["android.intent.action.MAIN"])], [dict(r0, meta_data={"android.app.other": "device_admin"})],
                          [dict(r0, meta_data={"android.app.device_admin": "missing"})], [dict(r0, extra=1)],
                          [{k: v for k, v in r0.items() if k != "name"}], [r0, r0], ["org.example.club.A"], "x", [r0] * 9, [[]]],
            "activity": [dict(activity, launch_mode="fast"), dict(activity, lock_task_mode="always"), dict(activity, soft_input_mode="x"),
                         dict(activity, exclude_from_recents="true"), dict(activity, categories=["LAUNCHER"]),
                         dict(activity, categories=["HOME", "HOME"]), dict(activity, extra=1), {}, []],
            "permissions": [["BIND_DEVICE_ADMIN"], ["android.permission.RECEIVE_BOOT_COMPLETED"]],
        }
        for key, values in bad.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(SystemExit) as raised:
                        manifest.render(dict(JAVA, **{key: value}), "libclub.so")
                    self.assertIn("apk_manifest:", str(raised.exception))

    def test_unknown_keys_and_raw_xml_are_not_a_declaration(self):
        for extra in ("manifest_xml", "raw_manifest", "application"):
            self.assertTrue(manifest.validate(dict(JAVA, **{extra: "<receiver/>"})))
        self.assertEqual(manifest.validate(JAVA), [])


def build_dex(names, strings_first=True):
    """A minimal well-formed dex file whose class_defs are `names` (`org.example.A`): header, strings, type_ids, class_defs."""
    descriptors = ["L%s;" % n.replace(".", "/") for n in names]
    blob, offsets = b"", []
    base = 0x70 + 4 * len(descriptors) * 2 + 32 * len(descriptors)
    for d in descriptors:
        offsets.append(base + len(blob))
        blob += bytes([len(d)]) + d.encode("ascii") + b"\0"
    n = len(descriptors)
    body = b"".join(struct.pack("<I", o) for o in offsets) + b"".join(struct.pack("<I", i) for i in range(n))
    body += b"".join(struct.pack("<I", i) + b"\0" * 28 for i in range(n)) + blob
    header = bytearray(0x70)
    header[0:8] = b"dex\n035\0"
    struct.pack_into("<III", header, 0x20, 0x70 + len(body), 0x70, 0x12345678)
    struct.pack_into("<IIII", header, 0x38, n, 0x70, n, 0x70 + 4 * n)
    struct.pack_into("<II", header, 0x60, n, 0x70 + 8 * n)
    data = bytearray(bytes(header) + body)
    struct.pack_into("<I", data, 8, zlib.adler32(bytes(data[12:])))
    return bytes(data)


def fix(data, mutate):
    """`data` changed by `mutate(bytearray)`, with the checksum recomputed (so that only the mutation is wrong)."""
    out = bytearray(data)
    mutate(out)
    struct.pack_into("<I", out, 8, zlib.adler32(bytes(out[12:])))
    return bytes(out)


class DexTest(TempDirTestCase):
    NAMES = ["org.example.club.A", "org.example.club.A$B", "org.example.club.C"]

    def test_the_class_defs_are_read(self):
        self.assertEqual(check.dex_classes(build_dex(self.NAMES)), self.NAMES)
        self.assertEqual(check.dex_classes(build_dex([])), [])

    def test_a_malformed_dex_is_refused(self):
        good = build_dex(self.NAMES)
        cases = {
            "magic": (b"zip\n035\0" + good[8:], "not a dex file"),
            "short": (good[:0x40], "not a dex file"),
            "version": (fix(good, lambda d: d.__setitem__(slice(4, 7), b"abc")), "not a dex file"),
            "size": (good + b"\0", "bad dex header"),
            "header size": (fix(good, lambda d: struct.pack_into("<I", d, 0x24, 0x71)), "bad dex header"),
            "endian": (fix(good, lambda d: struct.pack_into("<I", d, 0x28, 0x78563412)), "bad dex header"),
            "checksum": (good[:-1] + bytes([good[-1] ^ 1]), "bad dex checksum"),
            "class table": (fix(good, lambda d: struct.pack_into("<I", d, 0x64, len(good))), "outside the file"),
            "string table": (fix(good, lambda d: struct.pack_into("<I", d, 0x3C, len(good))), "outside the file"),
            "type table": (fix(good, lambda d: struct.pack_into("<I", d, 0x44, len(good))), "outside the file"),
            "table in the header": (fix(good, lambda d: struct.pack_into("<I", d, 0x64, 0x20)), "outside the file"),
            "type index": (fix(good, lambda d: struct.pack_into("<I", d, 0x70 + 8 * 3, 9)), "names the type 9 of 3"),
            "string index": (fix(good, lambda d: struct.pack_into("<I", d, 0x70 + 4 * 3, 9)), "names the string 9 of 3"),
            "not terminated": (fix(good, lambda d: d.__setitem__(slice(-1, None), b"x")), "not terminated"),
            "not ascii": (fix(good, lambda d: d.__setitem__(len(d) - 3, 0xC3)), "not ASCII"),
            "not a class": (fix(good, lambda d: d.__setitem__(len(d) - 2, ord("x"))), "not a class"),
            "runaway length": (fix(good, lambda d: struct.pack_into("<I", d, 0x70, len(d))), "runs off the file"),
        }
        for name, (data, why) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, why):
                check.dex_classes(data)

    def test_the_dex_of_an_apk_is_compared_with_the_declared_classes(self):
        def apk_with(data):
            path = self.tmp / "a.apk"
            with zipfile.ZipFile(path, "w") as z:
                if data is not None:
                    z.writestr("classes.dex", data)
            return str(path)
        self.assertEqual(check.dex_problems(apk_with(build_dex(self.NAMES)), self.NAMES), [])
        self.assertEqual(check.dex_problems(apk_with(build_dex(self.NAMES + ["org.example.club.X"])), self.NAMES),
                         ["classes.dex defines org.example.club.X, which is not a declared class"])
        self.assertEqual(check.dex_problems(apk_with(build_dex(self.NAMES[:2])), self.NAMES),
                         ["classes.dex does not define the declared class org.example.club.C"])
        self.assertEqual(check.dex_problems(apk_with(build_dex(self.NAMES + self.NAMES[:1])), self.NAMES),
                         ["classes.dex defines org.example.club.A twice"])
        self.assertEqual(check.dex_problems(apk_with(b"not a dex file at all, but long enough to read" * 4), self.NAMES),
                         ["classes.dex: not a dex file (magic)"])
        self.assertEqual(check.dex_problems(apk_with(None), self.NAMES), [])     # the entry check reports the missing file

    def test_the_uleb128_length_prefix(self):
        self.assertEqual(check._uleb(b"\x05abc", 0), (5, 1))
        self.assertEqual(check._uleb(b"\xe5\x8e\x26", 0), (624485, 3))
        with self.assertRaises(ValueError):
            check._uleb(b"\x80", 0)
        with self.assertRaises(ValueError):
            check._uleb(b"\x80\x80\x80\x80\x80\x80", 0)

    def test_the_entries_follow_the_declaration(self):
        good = ["AndroidManifest.xml", "resources.arsc", "lib/arm64-v8a/libclub.so"]
        want = good + ["classes.dex", "res/xml/a.xml"]
        self.assertEqual(check.entry_problems(want, "libclub.so", [], True, ["a.xml"]), [])
        self.assertEqual(check.entry_problems(good, "libclub.so", [], True, ["a.xml"]), ["missing entry classes.dex", "missing entry res/xml/a.xml"])
        self.assertEqual(check.entry_problems(want, "libclub.so", []), ["unexpected entry classes.dex", "unexpected entry res/xml/a.xml"])
        self.assertEqual(check.entry_problems(want + ["classes2.dex", "res/xml/b.xml"], "libclub.so", [], True, ["a.xml"]),
                         ["unexpected entry classes2.dex", "unexpected entry res/xml/b.xml"])


class JavaToolsTest(TempDirTestCase):
    def test_pack_puts_the_dex_between_the_base_and_the_library(self):
        base = self.tmp / "base.apk"
        with zipfile.ZipFile(base, "w") as z:
            z.writestr("AndroidManifest.xml", b"m")
        lib, dex, out = self.tmp / "libclub.so", self.tmp / "classes.dex", self.tmp / "out.apk"
        lib.write_bytes(b"so")
        dex.write_bytes(b"dex")
        self.assertEqual(pack.main(["x", str(base), str(lib), str(out), str(dex)]), 0)
        with zipfile.ZipFile(out) as z:
            self.assertEqual([i.filename for i in z.infolist()], ["AndroidManifest.xml", "classes.dex", "lib/arm64-v8a/libclub.so"])
            self.assertEqual(z.read("classes.dex"), b"dex")
            self.assertEqual({i.compress_type for i in z.infolist()}, {zipfile.ZIP_STORED})
        with zipfile.ZipFile(base, "w") as z:
            z.writestr("classes.dex", b"x")
        with self.assertRaises(SystemExit):
            pack.pack(str(base), str(lib), str(out))
        with self.assertRaises(SystemExit):
            pack.main(["x", "a", "b", "c", "d", "e"])

    def test_apk_java_takes_exactly_its_arguments_and_only_java_files(self):
        full = ["x", "--javac", "j", "--d8", "d", "--android-jar", "a.jar", "--min-api", "28", "--out", "o.dex", "A.java"]
        for drop in range(1, 11, 2):
            with self.subTest(drop=full[drop]), self.assertRaises(SystemExit):
                java.main(full[:drop] + full[drop + 2:])
        for bad in (["--proc", "x"], ["B.kt"], ["-Xlint:none"], ["--out"]):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                java.main(full + bad)
        with self.assertRaises(SystemExit):
            java.main(full[:-1])         # no source

    def test_javac_is_run_with_werror_without_processors_and_with_the_boot_class_path(self):
        seen = []
        original = java.run
        java.run = lambda command, *args: seen.append((command, [str(a) for a in args])) or ""
        try:
            java.compile_sources("JAVAC", "android.jar", ["B.java", "A.java"], "out")
        finally:
            java.run = original
        command, args = seen[0]
        self.assertEqual(command, "JAVAC")
        for flag in ("-Werror", "-proc:none", "-implicit:none"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("-bootclasspath") + 1], "android.jar")
        self.assertIn("-Xlint:all,-options", args)
        self.assertEqual(args[-2:], ["A.java", "B.java"])           # sorted
        self.assertEqual((args[args.index("-source") + 1], args[args.index("-target") + 1]), ("8", "8"))

    def test_d8_is_run_with_the_min_api_and_must_write_exactly_classes_dex(self):
        out = self.tmp / "dex"
        out.mkdir()
        calls = []
        original = java.run
        def fake(command, *args):
            calls.append((command, [str(a) for a in args]))
            (out / "classes.dex").write_bytes(b"d")
            return ""
        java.run = fake
        try:
            self.assertEqual(java.dex("D8", "android.jar", "28", ["a.class"], str(out)), str(out / "classes.dex"))
            self.assertEqual(calls[0][1][:2], ["--min-api", "28"])
            (out / "classes2.dex").write_bytes(b"d")
            with self.assertRaises(SystemExit):
                java.dex("D8", "android.jar", "28", ["a.class"], str(out))
            with self.assertRaises(SystemExit):
                java.dex("D8", "android.jar", "28", [], str(out))
        finally:
            java.run = original

    def test_class_files_are_found_sorted_and_a_failing_tool_stops_the_action(self):
        (self.tmp / "p").mkdir()
        for name in ("p/B.class", "p/A.class", "p/A.java", "C.class"):
            (self.tmp / name).write_bytes(b"")
        self.assertEqual([os.path.relpath(f, self.tmp) for f in java.class_files(str(self.tmp))], ["C.class", "p/A.class", "p/B.class"])
        self.assertEqual(java.run("true"), "")
        with self.assertRaises(SystemExit) as raised:
            java.run("sh", "-c", "echo boom; exit 3")
        self.assertIn("exit 3", str(raised.exception))
        self.assertIn("boom", str(raised.exception))


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
        for forbidden in ("src.zip", "ct.sym", "jmods", "bin/javac", "lib/jrt-fs", "bin/jar"):
            self.assertNotIn(forbidden, code)


class NoReleaseKeyTest(unittest.TestCase):
    """Release signing is out of scope: no argument, environment variable or file of a product reaches the signing step."""

    def test_the_rule_and_the_scripts_read_no_environment_and_take_no_key(self):
        for name in ("rules/apk.bzl", "rules/apk_manifest.py", "rules/apk_pack.py", "rules/apk_check.py", "rules/apk_java.py"):
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
