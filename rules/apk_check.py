"""Check a signed APK against what its `c_apk` declared (stdlib only; the tools are the pinned SDK ones).

    apk_check.py --spec SPEC.json --lib libNAME.so --export SYMBOL [--export SYMBOL]... [--asset NAME]...
                 --aapt2 CMD --zipalign CMD --apksigner CMD --android-jar JAR --cert-sha256 FILE
                 --elf-check-py rules/elf_check.py --apk-manifest-py rules/apk_manifest.py [--out OUT] APK

Every problem is reported, one line each, prefixed by the check that found it; exit 0 only when there is none (and then OUT,
if given, is written). The checks:

  entries    the zip holds exactly AndroidManifest.xml, resources.arsc, lib/arm64-v8a/<lib>, assets/<asset> for each
             declared asset, res/xml/<name> for each declared `res_xml` and classes.dex exactly when the declaration has
             `java_classes`: no other file, no directory entry, no repeated name, no signature file of another scheme;
  dex        (T-G3b) classes.dex is a well-formed dex file (header, checksum, bounds) whose class_defs are exactly the
             declared `java_classes`: none missing, none extra (a small parser of the dex format, `dex_classes` below);
  library    the object is STORED and its data starts at a multiple of 16384 bytes, and (rules/elf_check.py) it is an
             AArch64 shared object whose PT_LOAD segments are aligned to 16384 and whose dynamic symbols define exactly
             the --export list;
  zipalign   `zipalign -c -P 16 -v 4` accepts the archive;
  signature  `apksigner verify --min-sdk-version 28` accepts it, with one signer and the v3 scheme (or v2: with minSdk 28 apksigner writes v3 only), and the signer
             certificate's SHA-256 is the one in --cert-sha256 (the test-only debug key; a release key, or any other, fails);
  manifest   `aapt2 dump xmltree` of the APK's manifest is identical to that of the manifest rendered from SPEC
             (rules/apk_manifest.py) and linked the same way: package, version, SDK levels, permissions, application class,
             activity attributes, receivers, all of it (the expected one is linked with stand-in @xml resources, see below).

`buck2 run //pkg:<name>_check -- OTHER.apk` runs the same checks on any APK (the selftest does).
"""

import importlib.util
import json
import os
import shlex
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

PAGE = 16384
ABI_DIR = "lib/arm64-v8a/"
DEX = "classes.dex"


def _load(opts, name):
    """The module `name` (elf_check, apk_manifest) from the path given for it: Buck2 materialises each script in its own directory."""
    spec = importlib.util.spec_from_file_location(name, opts[name.replace("_", "-") + "-py"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(command, *args):
    done = subprocess.run(shlex.split(command) + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, check=False)
    return done.returncode, done.stdout.decode("utf-8", "replace")


def _tail(text):
    return " | ".join(line.strip() for line in text.strip().splitlines()[-4:])


def entry_problems(names, lib, assets, java=False, res_xml=()):
    """The problems of the entry list alone (`java`: the declaration has java_classes; `res_xml`: the declared file names)."""
    want = {"AndroidManifest.xml", "resources.arsc", ABI_DIR + lib} | {"assets/" + a for a in assets}
    want |= {"res/xml/" + r for r in res_xml} | ({DEX} if java else set())
    found = ["repeated entry %s" % n for n in sorted({n for n in names if names.count(n) > 1})]
    found += ["unexpected entry %s" % n for n in sorted(set(names) - want)]
    found += ["missing entry %s" % n for n in sorted(want - set(names))]
    return found


def data_offset(path, info):
    with open(path, "rb") as handle:
        handle.seek(info.header_offset)
        head = handle.read(30)
    if len(head) != 30 or head[:4] != b"PK\x03\x04":
        return None
    name_len, extra_len = struct.unpack_from("<HH", head, 26)
    return info.header_offset + 30 + name_len + extra_len


def library_problems(opts, apk, lib, exports):
    elf_check = _load(opts, "elf_check")
    with zipfile.ZipFile(apk) as archive:
        try:
            info = archive.getinfo(ABI_DIR + lib)
        except KeyError:
            return []   # the entry check says it is missing
        data = archive.read(info)
    found = []
    if info.compress_type != zipfile.ZIP_STORED:
        found.append("%s is compressed (method %d), it must be STORED" % (info.filename, info.compress_type))
    offset = data_offset(apk, info)
    if offset is None or offset % PAGE:
        found.append("%s data starts at %s, not a multiple of %d" % (info.filename, offset, PAGE))
    found += ["%s: %s" % (lib, problem) for problem in elf_check.problems(data, PAGE, exports)]
    return found


def _uleb(data, at):
    value, shift = 0, 0
    while True:
        if at >= len(data) or shift > 28:
            raise ValueError("a string length runs off the file")
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, at


def dex_classes(data):
    """The class names (`org.example.A$B`) of the class_defs of a dex file; ValueError says what is wrong with the file.

    The dex format (source.android.com/docs/core/runtime/dex-format): a 0x70-byte header (magic `dex\\n0NN\\0`, adler32 of
    everything after the first 12 bytes, file_size, header_size 0x70, little-endian tag), the string_ids (offsets of
    `uleb128 length, MUTF-8 bytes, 0`), the type_ids (a string index each) and the class_defs (32 bytes, a type index first).
    """
    if len(data) < 0x70 or not (data[:4] == b"dex\n" and data[4:7].isdigit() and data[7:8] == b"\0"):
        raise ValueError("not a dex file (magic)")
    size, head, endian = struct.unpack_from("<III", data, 0x20)
    if size != len(data) or head != 0x70 or endian != 0x12345678:
        raise ValueError("bad dex header (file_size %d for %d bytes, header_size %#x, endian %#x)" % (size, len(data), head, endian))
    if struct.unpack_from("<I", data, 8)[0] != zlib.adler32(data[12:]):
        raise ValueError("bad dex checksum")
    n_strings, strings_at, n_types, types_at = struct.unpack_from("<IIII", data, 0x38)
    n_classes, classes_at = struct.unpack_from("<II", data, 0x60)
    if (strings_at + 4 * n_strings > size or types_at + 4 * n_types > size or classes_at + 32 * n_classes > size
            or min(strings_at, types_at, classes_at) < 0x70 and (n_strings or n_types or n_classes)):
        raise ValueError("a dex table lies outside the file")
    names = []
    for index in range(n_classes):
        type_index = struct.unpack_from("<I", data, classes_at + 32 * index)[0]
        if type_index >= n_types:
            raise ValueError("a class_def names the type %d of %d" % (type_index, n_types))
        string_index = struct.unpack_from("<I", data, types_at + 4 * type_index)[0]
        if string_index >= n_strings:
            raise ValueError("a type_id names the string %d of %d" % (string_index, n_strings))
        at = struct.unpack_from("<I", data, strings_at + 4 * string_index)[0]
        _, at = _uleb(data, at)
        end = data.find(b"\0", at)
        if end < 0:
            raise ValueError("a string is not terminated")
        try:
            descriptor = data[at:end].decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("a class descriptor is not ASCII") from None
        if not (descriptor.startswith("L") and descriptor.endswith(";")):
            raise ValueError("a class_def has the type %r, not a class" % descriptor)
        names.append(descriptor[1:-1].replace("/", "."))
    return names


def dex_problems(apk, declared):
    """The problems of classes.dex against the declared class names (the entry check says when the file itself is missing)."""
    with zipfile.ZipFile(apk) as archive:
        try:
            data = archive.read(DEX)
        except KeyError:
            return []
    try:
        names = dex_classes(data)
    except (ValueError, struct.error) as exc:
        return ["%s: %s" % (DEX, exc)]
    found = ["%s defines %s twice" % (DEX, n) for n in sorted({n for n in names if names.count(n) > 1})]
    found += ["%s defines %s, which is not a declared class" % (DEX, n) for n in sorted(set(names) - set(declared))]
    found += ["%s does not define the declared class %s" % (DEX, n) for n in sorted(set(declared) - set(names))]
    return found


def zipalign_problems(zipalign, apk):
    code, text = _run(zipalign, "-c", "-P", "16", "-v", "4", apk)
    return [] if code == 0 else ["zipalign -c -P 16 4 refused it (exit %d): %s" % (code, _tail(text))]


def signature_problems(apksigner, apk, digest):
    code, text = _run(apksigner, "verify", "--verbose", "--print-certs", "--min-sdk-version", "28", apk)
    if code != 0:
        return ["apksigner verify refused it (exit %d): %s" % (code, _tail(text))]
    lines = text.splitlines()
    found = []
    if "Number of signers: 1" not in lines:
        found.append("the APK does not have exactly one signer")
    if not any(line.startswith(("Verified using v2 scheme", "Verified using v3 scheme")) and line.endswith(": true") for line in lines):
        found.append("the APK is verified by neither the v2 nor the v3 scheme")
    digests = [line.split(":", 1)[1].strip() for line in lines if line.startswith("Signer #") and "certificate SHA-256 digest:" in line]
    if digests != [digest]:
        found.append("signer certificate SHA-256 is %s, expected the debug key %s" % (digests, digest))
    return found


def manifest_problems(opts, apk, spec, lib):
    aapt2, android_jar = opts["aapt2"], opts["android-jar"]
    manifest = _load(opts, "apk_manifest")
    with tempfile.TemporaryDirectory() as scratch:
        source = os.path.join(scratch, "AndroidManifest.xml")
        expected_apk = os.path.join(scratch, "expected.apk")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(manifest.render(spec, lib))
        extra = []
        if spec.get("res_xml"):     # the manifest points at @xml/<name>: link it with stand-ins of the same names (same resource ids)
            os.makedirs(os.path.join(scratch, "res", "xml"))
            for name in spec["res_xml"]:
                with open(os.path.join(scratch, "res", "xml", name), "w", encoding="utf-8") as handle:
                    handle.write('<?xml version="1.0" encoding="utf-8"?>\n<stand-in />\n')
            code, text = _run(aapt2, "compile", "--dir", os.path.join(scratch, "res"), "-o", os.path.join(scratch, "res.zip"))
            if code != 0:
                return ["could not compile the stand-in resources (exit %d): %s" % (code, _tail(text))]
            extra = ["-R", os.path.join(scratch, "res.zip")]
        code, text = _run(aapt2, "link", "-I", android_jar, "--manifest", source, *extra, "-o", expected_apk)
        if code != 0:
            return ["could not link the expected manifest (exit %d): %s" % (code, _tail(text))]
        want_code, want = _run(aapt2, "dump", "xmltree", "--file", "AndroidManifest.xml", expected_apk)
        got_code, got = _run(aapt2, "dump", "xmltree", "--file", "AndroidManifest.xml", apk)
    if want_code != 0 or got_code != 0:
        return ["aapt2 dump xmltree failed (exit %d, %d): %s" % (want_code, got_code, _tail(got if got_code else want))]
    if got == want:
        return []
    wl, gl = want.splitlines(), got.splitlines()
    for index in range(max(len(wl), len(gl))):
        a = wl[index] if index < len(wl) else "<end>"
        b = gl[index] if index < len(gl) else "<end>"
        if a != b:
            return ["the manifest differs from the declaration at line %d: declared %r, APK has %r" % (index + 1, a.strip(), b.strip())]
    return ["the manifest differs from the declaration"]


def parse(argv):
    opts = {"export": [], "asset": []}
    args, apk = list(argv[1:]), None
    names = ("spec", "lib", "aapt2", "zipalign", "apksigner", "android-jar", "cert-sha256", "elf-check-py", "apk-manifest-py", "out", "export", "asset")
    while args:
        arg = args.pop(0)
        if arg.startswith("--") and arg[2:] in names and args:
            if arg[2:] in ("export", "asset"):
                opts[arg[2:]].append(args.pop(0))
            else:
                opts[arg[2:]] = args.pop(0)
        elif not arg.startswith("--") and apk is None:
            apk = arg
        else:
            sys.exit(__doc__)
    required = ("spec", "lib", "aapt2", "zipalign", "apksigner", "android-jar", "cert-sha256", "elf-check-py", "apk-manifest-py")
    if apk is None or any(k not in opts for k in required) or not opts["export"]:
        sys.exit(__doc__)
    return opts, apk


def main(argv):
    opts, apk = parse(argv)
    with open(opts["spec"], encoding="utf-8") as handle:
        spec = json.load(handle)
    with open(opts["cert-sha256"], encoding="utf-8") as handle:
        digest = handle.read().strip()
    lib = opts["lib"]
    try:
        with zipfile.ZipFile(apk) as archive:
            names = [i.filename for i in archive.infolist()]
        problems = [("entries", p) for p in entry_problems(names, lib, opts["asset"], bool(spec.get("java_classes")), spec.get("res_xml", ()))]
    except (zipfile.BadZipFile, OSError) as exc:
        sys.stderr.write("apk_check: %s: not a readable zip archive: %s\n" % (apk, exc))
        return 1
    problems += [("library", p) for p in library_problems(opts, apk, lib, opts["export"])]
    problems += [("dex", p) for p in dex_problems(apk, spec.get("java_classes", ()))]
    problems += [("zipalign", p) for p in zipalign_problems(opts["zipalign"], apk)]
    problems += [("signature", p) for p in signature_problems(opts["apksigner"], apk, digest)]
    problems += [("manifest", p) for p in manifest_problems(opts, apk, spec, lib)]
    if problems:
        sys.stderr.write("apk_check: %s is not acceptable:\n" % apk)
        sys.stderr.write("".join("  [%s] %s\n" % pair for pair in problems))
        return 1
    if "out" in opts:
        with open(opts["out"], "w", encoding="utf-8") as handle:
            handle.write("ok: entries, dex, library, zipalign, signature, manifest\n")
    print("apk_check: %s: entries, dex, library (16 KB), zipalign, signature, manifest all hold" % apk)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
