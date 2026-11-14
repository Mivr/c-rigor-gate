#!/usr/bin/env bash
# Self-test of the Android shared object rule `c_android_so` (T-G2) and the NDK twins of the Linux facts (T-G1).
# And of `c_apk` (T-G3): the signed, 16 KB aligned APK, its check, and five ways to break an APK that the check must refuse.
# Needs bash, python3 (stdlib) and tools/buck2. Builds on the RE farm; `buck2 run` executes the pinned NDK llvm-readelf.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
AND=toolchains//:android_release
scratch="selftest/scratch_android"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
must_pass() { local log="$out/$step.log"; run "$log" "$@" || fail "$CUR: buck2 $* failed" "$log"; }
must_fail_with() { local re="$1"; shift; local log="$out/$step.log"
  if run "$log" "$@"; then fail "$CUR: buck2 $* unexpectedly succeeded" "$log"; fi
  grep -Eq "$re" "$log" || fail "$CUR: failed, but not for the right reason (wanted /$re/)" "$log"; }
# output <logfile> <target>: the path --show-output printed for the target
output() { awk -v t="$2" '$1 ~ t"$" && /buck-out/ {print $2}' "$1" | tail -1; }

begin "examples/android builds lib<name>.so for android_release; the facts targets exist for the android mode only"
must_pass build --target-platforms $AND //examples/android:club //examples/android:club_facts //examples/android:core --show-output
so="$root/$(output "$out/$step.log" '//examples/android:club')"
[ -f "$so" ] && [ "$(basename "$so")" = "libclub.so" ] || fail "$CUR: no libclub.so ($so)" "$out/$step.log"
echo "  $so"
must_fail_with "incompatible|Incompatible" build //examples/android:club
echo "  linux_release refuses the shared object (android mode only)"
must_fail_with "incompatible|Incompatible" build --target-platforms $AND //examples/hello:hello
must_fail_with "incompatible|Incompatible" build --target-platforms $AND //examples/hello:hello_test
echo "  the android mode refuses c_binary and c_test (they run on the Linux workers only)"

begin "llvm-readelf from the pinned NDK: the dynamic symbol table defines the entry symbol and nothing else"
log="$out/readelf.log"
run "$log" run toolchains//:ndk-llvm-readelf -- --dyn-syms --wide "$so" || fail "$CUR: llvm-readelf failed" "$log"
python3 -I - "$log" <<'PY' || fail "$CUR: wrong dynamic symbols" "$log"
import re, sys
defined, undefined = [], []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    f = line.split()
    if len(f) >= 8 and re.fullmatch(r"\d+:", f[0]):
        (undefined if f[6] == "UND" else defined).append(f[7].split("@")[0])
print("  defined:", defined, " undefined:", sorted(undefined))
assert defined == ["ANativeActivity_onCreate"], defined
assert "__android_log_write" in undefined and "ANativeActivity_finish" in undefined, undefined
PY

begin "every LOAD segment is 16 KB aligned (llvm-readelf -l, independent of the build's own check)"
run "$log" run toolchains//:ndk-llvm-readelf -- -l --wide "$so" || fail "$CUR: llvm-readelf -l failed" "$log"
python3 -I - "$log" <<'PY' || fail "$CUR: LOAD alignment" "$log"
import sys
aligns = [int(l.split()[-1], 16) for l in open(sys.argv[1], encoding="utf-8", errors="replace") if l.split()[:1] == ["LOAD"]]
print("  LOAD align:", [hex(a) for a in aligns])
assert aligns and all(a >= 16384 for a in aligns), aligns
PY

begin "the build's own check (rules/elf_check.py) refuses a 4 KB-aligned copy and an object with an extra export"
python3 -I - "$so" "$out" <<'PY' || fail "$CUR"
import struct, sys
data = bytearray(open(sys.argv[1], "rb").read())
phoff, = struct.unpack_from("<Q", data, 32)
phentsize, phnum = struct.unpack_from("<HH", data, 54)
patched = 0
for i in range(phnum):
    at = phoff + i * phentsize
    if struct.unpack_from("<I", data, at)[0] == 1:   # PT_LOAD
        struct.pack_into("<Q", data, at + 48, 4096)
        patched += 1
assert patched, "no LOAD segment"
open(sys.argv[2] + "/four_kb.so", "wb").write(data)
PY
if python3 -I rules/elf_check.py --page-size 16384 --export ANativeActivity_onCreate "$out/four_kb.so" "$out/never.so" 2> "$out/e1.log"; then fail "$CUR: a 4 KB-aligned object was accepted"; fi
grep -q "aligned to 4096, not 16384" "$out/e1.log" || fail "$CUR: refused for the wrong reason" "$out/e1.log"
python3 -I rules/elf_check.py --page-size 16384 --export ANativeActivity_onCreate "$so" "$out/ok.so" || fail "$CUR: the real object was refused"
if python3 -I rules/elf_check.py --page-size 16384 --export other_entry "$so" "$out/never.so" 2> "$out/e2.log"; then fail "$CUR: a wrong export list was accepted"; fi
grep -q "exports ANativeActivity_onCreate" "$out/e2.log" && grep -q "does not define the export other_entry" "$out/e2.log" || fail "$CUR: refused for the wrong reason" "$out/e2.log"
[ ! -e "$out/never.so" ] || fail "$CUR: a refused object was written"
echo "  4 KB refused, wrong exports refused, the real libclub.so accepted"

begin "the symbols gate (NDK libc list, android-mode facts) accepts the example"
mkdir -p "$out/facts" "$out/res"
must_pass build --target-platforms $AND //examples/android:club_facts toolchains//:libc_symbols_android --show-output
cp "$(output "$out/$step.log" '//examples/android:club_facts')" "$out/facts/club.json" || fail "$CUR: no club facts"
cp "$(output "$out/$step.log" 'toolchains//:libc_symbols_android')" "$out/libc_android.symbols" || fail "$CUR: no android libc list"
# the dependency's facts come from the Linux release mode, the one fact source of its policy
must_pass build //examples/android:core_facts --show-output
cp "$(output "$out/$step.log" '//examples/android:core_facts')" "$out/facts/core.json" || fail "$CUR: no core facts"
for sym in ANativeWindow_lock __android_log_write malloc pthread_create getrandom; do
  grep -qx "$sym" "$out/libc_android.symbols" || fail "$CUR: the android libc list lacks $sym"; done
grep -q '"kind":"c_android_so"' "$out/facts/club.json" || fail "$CUR: the facts are not of kind c_android_so"
cat > "$out/policy.toml" <<'TOML'
[global]
deny = ["getenv", "abort", "exit", "_exit", "signal", "sigaction", "system", "fopen", "open", "socket", "dlopen", "time"]

[module."//examples/android:core"]
level = "L3"
exports = ["android_core_answer"]

[module."//examples/android:club"]
level = "L3"
exports = ["ANativeActivity_onCreate"]
system_libs = ["android", "log"]
allow = ["__android_log_write", "ANativeActivity_finish"]
TOML
gate_case() { # <name> <want-exit> <facts dir> <policy> <expected rule[:detail]>...
  local name="$1" want="$2" fd="$3" pol="$4"; shift 4
  python3 -I -B gate/rigor facts --gate symbols --facts "$fd" --policy "$pol" --libc "$out/libc_android.symbols" --out "$out/res/$name.json" > "$out/res/$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: $name exited $rc, wanted $want" "$out/res/$name.txt"
  python3 -I - "$out/res/$name.json" "$@" <<'PY' || fail "$CUR: $name findings differ" "$out/res/$name.txt"
import json, sys
doc = json.load(open(sys.argv[1]))
got = sorted(f["rule"] + (":" + f["symbol"] if f.get("symbol") else "") for f in doc["findings"] if f["severity"] == "error")
want = sorted(sys.argv[2:])
if got != want:
    sys.exit("  wanted %s\n  got    %s" % (want, got))
print("  %s: %s" % (doc["status"], got or "no findings"))
PY
}
gate_case example 0 "$out/facts" "$out/policy.toml"

begin "the symbols gate rejects a denied symbol (getenv) and a redefined bionic symbol (ANativeWindow_lock) in a c_android_so"
mkdir -p "$scratch"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_android_so")
c_android_so(name = "bad", srcs = ["bad.c"], exports = ["ANativeActivity_onCreate"])
c_android_so(name = "clash", srcs = ["clash.c"], exports = ["ANativeActivity_onCreate"])
BUCK
cat > "$scratch/bad.c" <<'C'
#include <android/native_activity.h>
#include <stdlib.h>
#include <stddef.h>
void ANativeActivity_onCreate(ANativeActivity *activity, void *saved, size_t saved_size) {
    (void)activity;
    (void)saved;
    (void)saved_size;
    (void)getenv("HOME");
}
C
cat > "$scratch/clash.c" <<'C'
#include <stddef.h>
/* Redefines a bionic export (no android header is included, so the declaration does not clash). */
int ANativeWindow_lock(void) { return 1; }
void ANativeActivity_onCreate(void *activity, void *saved, size_t saved_size) {
    (void)activity;
    (void)saved;
    (void)saved_size;
    (void)ANativeWindow_lock();
}
C
python3 -I -B gate/rigor buckfiles --root "$scratch" > "$out/bf.txt" 2>&1 || fail "$CUR: buckfiles refuses a c_android_so" "$out/bf.txt"
python3 -I -B gate/rigor buckfiles --root examples > "$out/bf2.txt" 2>&1 || fail "$CUR: buckfiles refuses examples/" "$out/bf2.txt"
must_pass build --target-platforms $AND //selftest/scratch_android:bad_facts //selftest/scratch_android:clash_facts --show-output
for n in bad clash; do
  mkdir -p "$out/facts_$n"
  cp "$(output "$out/$step.log" "//selftest/scratch_android:${n}_facts")" "$out/facts_$n/$n.json" || fail "$CUR: no $n facts"
done
cat > "$out/policy_bad.toml" <<'TOML'
[global]
deny = ["getenv", "abort", "exit"]

[module."//selftest/scratch_android:bad"]
level = "L3"
exports = ["ANativeActivity_onCreate"]
TOML
cat > "$out/policy_clash.toml" <<'TOML'
[global]
deny = ["getenv", "abort", "exit"]

[module."//selftest/scratch_android:clash"]
level = "L3"
exports = ["ANativeActivity_onCreate", "ANativeWindow_lock"]
TOML
gate_case denied 1 "$out/facts_bad" "$out/policy_bad.toml" denied-symbol:getenv
gate_case clash 1 "$out/facts_clash" "$out/policy_clash.toml" symbol-collision:ANativeWindow_lock
rm -rf "$scratch"

begin "the link refuses a c_android_so whose entry symbol is not defined (the version script names it)"
mkdir -p "$scratch"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_android_so")
c_android_so(name = "noentry", srcs = ["noentry.c"], exports = ["ANativeActivity_onCreate"])
BUCK
printf 'int noentry_unused(void) { return 0; }\n' > "$scratch/noentry.c"
must_fail_with "version script assignment of .global. to symbol .ANativeActivity_onCreate. failed: symbol not defined" build --target-platforms $AND //selftest/scratch_android:noentry
rm -rf "$scratch"

# ---------------------------------------------------------------------------------------------------------------------
# c_apk (T-G3)
# ---------------------------------------------------------------------------------------------------------------------
begin "examples/android builds app.apk and its _check; the pinned SDK tools read it back independently"
must_pass build --target-platforms $AND //examples/android:app //examples/android:app_check --show-output
apk="$root/$(output "$out/$step.log" '//examples/android:app')"
[ -f "$apk" ] && [ "$(basename "$apk")" = "app.apk" ] || fail "$CUR: no app.apk ($apk)" "$out/$step.log"
echo "  $apk"
must_fail_with "incompatible|Incompatible" build //examples/android:app
echo "  linux_release refuses the APK (android mode only)"
# The SDK trees in the default configuration (their blobs are what the verified-tree step reads); paths of the tools:
must_pass build --materializations all toolchains//:android_build_tools toolchains//:android_platform toolchains//:jdk --show-full-output
tree_of() { awk -v t="$1" '$1 == t {print $2}' "$out/$step.log" | tail -1; }
BT="$(tree_of toolchains//:android_build_tools)/android-15"
JAR="$(tree_of toolchains//:android_platform)/android-35/android.jar"
JDK="$(tree_of toolchains//:jdk)/jdk-21.0.6+7"
for f in "$BT/aapt2" "$BT/zipalign" "$BT/lib/apksigner.jar" "$JAR" "$JDK/bin/java" "$JDK/bin/keytool"; do [ -f "$f" ] || fail "$CUR: missing $f" "$out/$step.log"; done
APKSIGNER=("$JDK/bin/java" -Xmx1g -jar "$BT/lib/apksigner.jar")
"$BT/zipalign" -c -P 16 -v 4 "$apk" > "$out/za.log" 2>&1 || fail "$CUR: zipalign -c -P 16 refuses the APK" "$out/za.log"
grep -q "lib/arm64-v8a/libclub.so (OK)" "$out/za.log" || fail "$CUR: the object is not reported aligned" "$out/za.log"
"${APKSIGNER[@]}" verify --verbose --print-certs --min-sdk-version 28 "$apk" > "$out/sig.log" 2>&1 || fail "$CUR: apksigner verify refuses the APK" "$out/sig.log"
grep -q "Number of signers: 1" "$out/sig.log" || fail "$CUR: not exactly one signer" "$out/sig.log"
digest="$(sed -n 's/^Signer #1 certificate SHA-256 digest: //p' "$out/sig.log")"
[ "$digest" = "$(tr -d '\n' < toolchains/android_debug.cert.sha256)" ] || fail "$CUR: signed by $digest, not the debug key" "$out/sig.log"
"$BT/aapt2" dump badging "$apk" > "$out/badging.log" 2>&1 || fail "$CUR: aapt2 dump badging failed" "$out/badging.log"
for want in "package: name='org.example.club' versionCode='1' versionName='0.1.0'" "minSdkVersion:'28'" "targetSdkVersion:'35'" \
            "application: label='Club example'" "native-code: 'arm64-v8a'" "launchable-activity: name='android.app.NativeActivity'"; do
  grep -qF "$want" "$out/badging.log" || fail "$CUR: badging lacks $want" "$out/badging.log"; done
! grep -q "uses-permission" "$out/badging.log" || fail "$CUR: the example declares no permission" "$out/badging.log"
python3 -I - "$apk" <<'PY' || fail "$CUR: wrong entries"
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
names = [i.filename for i in z.infolist()]
print("  entries:", names)
assert sorted(names) == ["AndroidManifest.xml", "lib/arm64-v8a/libclub.so", "resources.arsc"], names
so = z.getinfo("lib/arm64-v8a/libclub.so")
assert so.compress_type == zipfile.ZIP_STORED
PY
cat > "$out/spec.json" <<'JSON'
{"label": "Club example", "orientation": "landscape", "package": "org.example.club", "permissions": [], "version_code": 1, "version_name": "0.1.0"}
JSON
# The build's check, run by hand on any APK: tools, spec and the debug certificate as the rule passes them.
CHECK_BASE=(python3 -I -B rules/apk_check.py --spec "$out/spec.json" --lib libclub.so
       --aapt2 "$BT/aapt2" --zipalign "$BT/zipalign" --apksigner "$JDK/bin/java -Xmx1g -jar $BT/lib/apksigner.jar"
       --android-jar "$JAR" --cert-sha256 toolchains/android_debug.cert.sha256
       --elf-check-py rules/elf_check.py --apk-manifest-py rules/apk_manifest.py)
CHECK=("${CHECK_BASE[@]}" --export ANativeActivity_onCreate)
"${CHECK[@]}" "$apk" > "$out/check_ok.log" 2>&1 || fail "$CUR: apk_check refuses the real APK" "$out/check_ok.log"
cat "$out/check_ok.log"

# problems <log>: the tags and texts of the problem lines of an apk_check run
problems() { sed -n 's/^  \[\([a-z]*\)\] \(.*\)$/\1: \2/p' "$1"; }
expect_refused() { # <name> <regex of the one problem> <apk> [extra apk_check arguments]
  local name="$1" re="$2" file="$3"; shift 3
  "${CHECK[@]}" "$@" "$file" > "$out/$name.log" 2>&1 && fail "$CUR: $name was accepted" "$out/$name.log"
  local n; n="$(problems "$out/$name.log" | wc -l)"
  [ "$n" = 1 ] && problems "$out/$name.log" | grep -Eq "$re" || fail "$CUR: $name: wanted exactly one problem matching /$re/" "$out/$name.log"
  echo "  $name refused: $(problems "$out/$name.log" | head -1 | cut -c1-150)"
}
sign() { "${APKSIGNER[@]}" sign --ks "${3:-toolchains/android_debug.keystore}" --ks-pass pass:android --ks-key-alias "${4:-androiddebugkey}" --key-pass pass:android \
           --min-sdk-version 28 --alignment-preserved true --v1-signing-enabled false --v4-signing-enabled false --out "$2" "$1" > "$out/sign.log" 2>&1 || fail "$CUR: apksigner sign" "$out/sign.log"; }
align() { "$BT/zipalign" -f -P 16 4 "$1" "$2" > "$out/align.log" 2>&1 || fail "$CUR: zipalign" "$out/align.log"; }
cat > "$out/mut.py" <<'PY'
"""mut.py unaligned|extra|swap IN [LIB] OUT: rewrite a zip without its signature (the caller re-aligns and re-signs)."""
import sys, zipfile
mode, src, out = sys.argv[1], sys.argv[2], sys.argv[-1]
def entry(name):
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_STORED; info.external_attr = 0o644 << 16
    return info
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
    for info in zin.infolist():
        data = zin.read(info)
        if mode == "swap" and info.filename.endswith("libclub.so"):
            data = open(sys.argv[3], "rb").read()
        zout.writestr(entry(info.filename), data)
    if mode == "extra":
        zout.writestr(entry("assets/extra.txt"), b"not declared\n")
if mode == "unaligned":
    with zipfile.ZipFile(out) as z:
        info = z.getinfo("lib/arm64-v8a/libclub.so")
        at = info.header_offset + 30 + len(info.filename)
        assert at % 16384 != 0, "the rewritten object happens to be aligned"
PY

begin "a misaligned APK (re-signed, so only the alignment is wrong), an APK with an extra file and a wrong manifest are each refused for their own reason"
python3 -I "$out/mut.py" unaligned "$apk" "$out/unaligned_raw.apk" || fail "$CUR: mut unaligned"
sign "$out/unaligned_raw.apk" "$out/unaligned.apk"
"$BT/zipalign" -c -P 16 4 "$out/unaligned.apk" > /dev/null 2>&1 && fail "$CUR: the rewritten APK is aligned after all"
"${APKSIGNER[@]}" verify --min-sdk-version 28 "$out/unaligned.apk" > /dev/null 2>&1 || fail "$CUR: the re-signed misaligned APK does not even verify"
"${CHECK[@]}" "$out/unaligned.apk" > "$out/unaligned.log" 2>&1 && fail "$CUR: a misaligned APK was accepted" "$out/unaligned.log"
problems "$out/unaligned.log" | grep -Eq "^library: .*data starts at .*not a multiple of 16384" || fail "$CUR: the object offset was not refused" "$out/unaligned.log"
problems "$out/unaligned.log" | grep -Eq "^zipalign: " || fail "$CUR: zipalign -c did not refuse it" "$out/unaligned.log"
[ "$(problems "$out/unaligned.log" | wc -l)" = 2 ] || fail "$CUR: more than the two alignment problems" "$out/unaligned.log"
echo "  misaligned: $(problems "$out/unaligned.log" | cut -c1-110 | tr '\n' ';')"
python3 -I "$out/mut.py" extra "$apk" "$out/extra_raw.apk" || fail "$CUR: mut extra"
align "$out/extra_raw.apk" "$out/extra_aligned.apk"; sign "$out/extra_aligned.apk" "$out/extra.apk"
expect_refused extra_file '^entries: unexpected entry assets/extra.txt$' "$out/extra.apk"
printf '{"label": "Club example", "orientation": "landscape", "package": "org.example.club", "permissions": [], "version_code": 2, "version_name": "0.1.0"}\n' > "$out/spec2.json"
expect_refused other_manifest '^manifest: the manifest differs from the declaration at line' "$apk" --spec "$out/spec2.json"

begin "an object with an extra export, an export list that names another entry, and an APK signed by another key are refused"
mkdir -p "$scratch"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_android_so")
c_android_so(name = "club", srcs = ["wide.c"], exports = ["ANativeActivity_onCreate", "extra_symbol"])
BUCK
cat > "$scratch/wide.c" <<'C'
#include <stddef.h>
int extra_symbol(void) { return 7; }
void ANativeActivity_onCreate(void *activity, void *saved, size_t saved_size) {
    (void)activity;
    (void)saved;
    (void)saved_size;
    (void)extra_symbol();
}
C
must_pass build --target-platforms $AND //selftest/scratch_android:club --show-output
wide="$root/$(output "$out/$step.log" '//selftest/scratch_android:club')"
python3 -I "$out/mut.py" swap "$apk" "$wide" "$out/wide_raw.apk" || fail "$CUR: mut swap"
align "$out/wide_raw.apk" "$out/wide_aligned.apk"; sign "$out/wide_aligned.apk" "$out/wide.apk"
expect_refused extra_export '^library: libclub.so: exports extra_symbol, which is not in the allowed export list$' "$out/wide.apk"
# --export other_entry gives two problems (the entry is not allowed, the other is missing): both, and nothing else, are the proof
"${CHECK_BASE[@]}" --export other_entry "$apk" > "$out/other.log" 2>&1 && fail "$CUR: a wrong export list was accepted" "$out/other.log"
[ "$(problems "$out/other.log" | sort | tr '\n' '|')" = "library: libclub.so: does not define the export other_entry|library: libclub.so: exports ANativeActivity_onCreate, which is not in the allowed export list|" ] \
  || fail "$CUR: wrong problems for a wrong export list" "$out/other.log"
rm -rf "$scratch"
# another key: a fresh key pair from the pinned keytool, the same APK re-signed with it
rm -f "$out/other.keystore"
"$JDK/bin/keytool" -genkeypair -keystore "$out/other.keystore" -storetype PKCS12 -storepass android -keypass android -alias otherkey \
  -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=another key" > "$out/keytool.log" 2>&1 || fail "$CUR: keytool" "$out/keytool.log"
sign "$apk" "$out/other_key.apk" "$out/other.keystore" otherkey
"${APKSIGNER[@]}" verify --min-sdk-version 28 "$out/other_key.apk" > /dev/null 2>&1 || fail "$CUR: apksigner itself does not accept the APK signed by the other key"
echo "  (apksigner verify alone accepts it; only the pinned certificate says no)"
expect_refused other_key '^signature: signer certificate SHA-256 is \[' "$out/other_key.apk"
# a tampered APK (one byte of the signed manifest) fails the signature itself
python3 -I - "$apk" "$out/tampered.apk" <<'PY' || fail "$CUR: tamper"
import sys, zipfile
raw = bytearray(open(sys.argv[1], "rb").read())
with zipfile.ZipFile(sys.argv[1]) as z:
    info = z.getinfo("AndroidManifest.xml")
    at = info.header_offset + 30 + len(info.filename) + len(info.extra) + info.file_size // 2
raw[at] ^= 0xFF
open(sys.argv[2], "wb").write(raw)
PY
"${CHECK[@]}" "$out/tampered.apk" > "$out/tampered.log" 2>&1 && fail "$CUR: a tampered APK was accepted" "$out/tampered.log"
problems "$out/tampered.log" | grep -Eq "^signature: apksigner verify refused it" || fail "$CUR: the tampering was not caught by the signature" "$out/tampered.log"
echo "  tampered: signature refused"

begin "c_apk takes no signing argument, validates every attribute, and refuses a private or foreign shared object"
for bad in 'signing = "release"' 'keystore = "k.jks"' 'min_sdk = 21'; do
  mkdir -p "$scratch"; : > "$scratch/a.c"
  printf 'load("@gate//rules:c.bzl", "c_android_so", "c_apk")\nc_android_so(name = "club", srcs = ["a.c"], exports = ["ANativeActivity_onCreate"])\nc_apk(name = "app", so = ":club", package = "org.example.club", label = "Club", version_code = 1, version_name = "1", %s)\n' "$bad" > "$scratch/BUCK"
  python3 -I -B gate/rigor buckfiles --root "$scratch" > "$out/bf_bad.txt" 2>&1 && fail "$CUR: buckfiles accepted c_apk with $bad" "$out/bf_bad.txt"
  grep -q "bad-argument" "$out/bf_bad.txt" || fail "$CUR: buckfiles refused $bad for another reason" "$out/bf_bad.txt"
  must_fail_with "extra named|Extra named|unexpected|Unexpected|Found .* named parameter|not a valid parameter" build --target-platforms $AND //selftest/scratch_android:app
  rm -rf "$scratch"
done
echo "  signing, keystore and SDK-level keywords: refused by buckfiles and by the macro"
i=0
while IFS='|' read -r attr value re; do
  i=$((i + 1)); mkdir -p "$scratch"; : > "$scratch/a.c"
  python3 -I - "$attr" "$value" > "$scratch/BUCK" <<'PY'
import sys
args = {"so": '":club"', "package": '"org.example.club"', "label": '"Club"', "version_code": "1", "version_name": '"1"',
        "orientation": '"landscape"', "permissions": "[]", "assets": "[]"}
args[sys.argv[1]] = sys.argv[2]
print('load("@gate//rules:c.bzl", "c_android_so", "c_apk")')
print('c_android_so(name = "club", srcs = ["a.c"], exports = ["ANativeActivity_onCreate"])')
print('c_apk(name = "app", ' + ", ".join("%s = %s" % kv for kv in args.items()) + ")")
PY
  must_fail_with "$re" build --target-platforms $AND //selftest/scratch_android:app
  rm -rf "$scratch"
done <<'CASES'
package|"Bad Package"|c_apk app: `package`
label|"a<b"|c_apk app: `label`
version_name|"1 2"|c_apk app: `version_name`
version_code|0|c_apk app: `version_code`
orientation|"left"|c_apk app: `orientation`
permissions|["READ_SMS"]|c_apk app: `permissions`
assets|["../x"]|c_apk app: `assets`
so|":club__lib"|c_apk app: `so` must be
so|"//p:club"|c_apk app: `so` must be
CASES
echo "  $i attribute cases refused at analysis"
mkdir -p "$scratch"
printf 'load("@gate//rules:c.bzl", "c_android_so", "c_apk")\nc_android_so(name = "club", srcs = ["a.c"], exports = ["ANativeActivity_onCreate", "other"])\nc_apk(name = "app", so = ":club", package = "org.example.club", label = "Club", version_code = 1, version_name = "1")\n' > "$scratch/BUCK"
printf '#include <stddef.h>\nvoid ANativeActivity_onCreate(void *a, void *b, size_t c) { (void)a; (void)b; (void)c; }\nvoid other(void) {}\n' > "$scratch/a.c"
must_fail_with "must export exactly ANativeActivity_onCreate" build --target-platforms $AND //selftest/scratch_android:app
rm -rf "$scratch"

mkdir -p "$scratch"; : > "$scratch/w.c"
printf 'load("@gate//rules:c.bzl", "c_sim")\nc_sim(name = "world", srcs = ["w.c"])\n' > "$scratch/BUCK"
must_fail_with "incompatible|Incompatible" build --target-platforms $AND //selftest/scratch_android:world
echo "  a c_sim is incompatible with the android mode (it does not interact with c_android_so / c_apk)"
rm -rf "$scratch"

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
