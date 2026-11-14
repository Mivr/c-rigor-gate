#!/usr/bin/env bash
# Self-test of the Android shared object rule `c_android_so` (T-G2) and the NDK twins of the Linux facts (T-G1).
# And of `c_apk` (T-G3): the signed, 16 KB aligned APK, its check, and five ways to break an APK that the check must refuse.
# And of `c_apk` with Java and res/xml (T-G3b): classes.dex from java_srcs, the receiver/application declarations, and the ways
# to break that APK (an extra or missing class, a corrupt or missing dex, an undeclared res file or receiver).
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
begin "examples/android builds app.apk and its _check (on RE)"
must_pass build --target-platforms $AND //examples/android:app //examples/android:app_check --show-output
apk="$root/$(output "$out/$step.log" '//examples/android:app')"
[ -f "$apk" ] && [ "$(basename "$apk")" = "app.apk" ] || fail "$CUR: no app.apk ($apk)" "$out/$step.log"
echo "  $apk"
must_fail_with "incompatible|Incompatible" build //examples/android:app
echo "  linux_release refuses the APK (android mode only)"

begin "the pinned SDK tools read the APK back, then break it (misaligned, extra file, other manifest, extra or wrong export, other key, tampered): each refused for its own reason"
# Everything below runs inside ONE action on an RE worker (rules/apk_lab.py): the farm does not serve the build-tools files to a
# client reliably (docs/toolchain.md, "Known limitation"), so no SDK tool is ever run on this machine.
mkdir -p "$scratch"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:apk.bzl", "apk_lab")
load("@gate//rules:c.bzl", "c_android_so")
c_android_so(name = "wide", srcs = ["wide.c"], exports = ["ANativeActivity_onCreate", "extra_symbol"])
apk_lab(name = "lab", apk = "//examples/android:app", wide = ":wide")
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
must_pass build --target-platforms $AND //selftest/scratch_android:lab --show-output
lab="$root/$(output "$out/$step.log" '//selftest/scratch_android:lab')"
[ -f "$lab" ] && grep -q "^APK LAB PASSED$" "$lab" || fail "$CUR: the lab did not pass" "$out/$step.log"
cat "$lab"
rm -rf "$scratch"

begin "examples/android:app_java builds (javac + d8 on RE, res/xml, receivers) and its _check holds"
must_pass build --target-platforms $AND //examples/android:app_java //examples/android:app_java_check --show-output
japk="$root/$(output "$out/$step.log" '//examples/android:app_java')"
[ -f "$japk" ] && [ "$(basename "$japk")" = "app_java.apk" ] || fail "$CUR: no app_java.apk ($japk)" "$out/$step.log"
echo "  $japk"

begin "the Java APK is broken six ways inside one RE action (extra class, missing class, corrupt dex, no dex, undeclared res file, undeclared receiver): each refused for its own single reason"
mkdir -p "$scratch"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:apk.bzl", "apk_lab")
load("@gate//rules:c.bzl", "c_android_so")
c_android_so(name = "wide", srcs = ["wide.c"], exports = ["ANativeActivity_onCreate", "extra_symbol"])
apk_lab(name = "lab_java", apk = "//examples/android:app_java", wide = ":wide")
BUCK
printf '#include <stddef.h>\nint extra_symbol(void) { return 7; }\nvoid ANativeActivity_onCreate(void *a, void *b, size_t c) { (void)a; (void)b; (void)c; (void)extra_symbol(); }\n' > "$scratch/wide.c"
must_pass build --target-platforms $AND //selftest/scratch_android:lab_java --show-output
lab="$root/$(output "$out/$step.log" '//selftest/scratch_android:lab_java')"
[ -f "$lab" ] && grep -q "^APK LAB PASSED$" "$lab" || fail "$CUR: the Java lab did not pass" "$out/$step.log"
for want in "extra_class refused" "missing_class refused" "corrupt_dex refused" "no_dex refused" "extra_res refused" "undeclared_receiver refused"; do
  grep -q "$want" "$lab" || fail "$CUR: the lab did not report: $want" "$lab"; done
cat "$lab"
rm -rf "$scratch"

begin "a class in a Java package that is not listed is refused for that single reason; a listed second package builds"
must_pass build --target-platforms $AND //examples/android:app_pkg //examples/android:app_pkg_check
echo "  examples/android:app_pkg (java_packages lists org.example.owner) builds and passes its check"
mkdir -p "$scratch"
printf '#include <stddef.h>\nvoid ANativeActivity_onCreate(void *a, void *b, size_t c) { (void)a; (void)b; (void)c; }\n' > "$scratch/a.c"
printf 'package org.example.owner;\n\npublic final class Owner {\n}\n' > "$scratch/Owner.java"
printf 'load("@gate//rules:c.bzl", "c_android_so", "c_apk")\nc_android_so(name = "club", srcs = ["a.c"], exports = ["ANativeActivity_onCreate"])\nc_apk(name = "app", so = ":club", package = "org.example.club", label = "Club", version_code = 1, version_name = "1", java_srcs = ["Owner.java"], java_classes = ["org.example.owner.Owner"])\n' > "$scratch/BUCK"
must_fail_with "c_apk app: .java_classes. must be a class directly in one of the .java_packages. \[.org.example.club.\]" build --target-platforms $AND //selftest/scratch_android:app
echo "  java_classes outside the listed packages: refused at analysis"
printf 'load("@gate//rules:c.bzl", "c_android_so", "c_apk")\nc_android_so(name = "club", srcs = ["a.c"], exports = ["ANativeActivity_onCreate"])\nc_apk(name = "app", so = ":club", package = "org.example.club", label = "Club", version_code = 1, version_name = "1", java_srcs = ["Owner.java"], java_classes = ["org.example.club.Owner"])\n' > "$scratch/BUCK"
must_fail_with "Owner.java is in the package org.example.owner, which is not in java_packages" build --target-platforms $AND //selftest/scratch_android:app
echo "  a source whose package line is not listed: refused by the build action"
rm -rf "$scratch"

begin "javac runs with -Werror: a Java source with an unchecked warning fails the APK build"
mkdir -p "$scratch"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_android_so", "c_apk")
c_android_so(name = "club", srcs = ["a.c"], exports = ["ANativeActivity_onCreate"])
c_apk(name = "app", so = ":club", package = "org.example.club", label = "Club", version_code = 1, version_name = "1",
      java_srcs = ["Warn.java"], java_classes = ["org.example.club.Warn"])
BUCK
printf '#include <stddef.h>\nvoid ANativeActivity_onCreate(void *a, void *b, size_t c) { (void)a; (void)b; (void)c; }\n' > "$scratch/a.c"
printf 'package org.example.club;\n\npublic final class Warn {\n    @SuppressWarnings("rawtypes")\n    public static void ok() { java.util.List l = new java.util.ArrayList(); l.size(); }\n    public static void bad() { java.util.List l = new java.util.ArrayList(); l.add(1); }\n}\n' > "$scratch/Warn.java"
must_fail_with "warnings found and -Werror specified" build --target-platforms $AND //selftest/scratch_android:app
rm -rf "$scratch"

begin "c_apk takes no signing argument, validates every attribute, and refuses a private or foreign shared object"
for bad in 'signing = "release"' 'keystore = "k.jks"' 'min_sdk = 21' 'java_flags = ["-nowarn"]' 'processors = ["p.Proc"]' 'raw_manifest = "<x/>"' 'manifest_xml = "<receiver/>"'; do
  mkdir -p "$scratch"; : > "$scratch/a.c"
  printf 'load("@gate//rules:c.bzl", "c_android_so", "c_apk")\nc_android_so(name = "club", srcs = ["a.c"], exports = ["ANativeActivity_onCreate"])\nc_apk(name = "app", so = ":club", package = "org.example.club", label = "Club", version_code = 1, version_name = "1", %s)\n' "$bad" > "$scratch/BUCK"
  python3 -I -B gate/rigor buckfiles --root "$scratch" > "$out/bf_bad.txt" 2>&1 && fail "$CUR: buckfiles accepted c_apk with $bad" "$out/bf_bad.txt"
  grep -q "bad-argument" "$out/bf_bad.txt" || fail "$CUR: buckfiles refused $bad for another reason" "$out/bf_bad.txt"
  must_fail_with "extra named|Extra named|unexpected|Unexpected|Found .* named parameter|not a valid parameter" build --target-platforms $AND //selftest/scratch_android:app
  rm -rf "$scratch"
done
echo "  signing, keystore, SDK-level, javac-flag, processor and raw-manifest keywords: refused by buckfiles and by the macro"
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
java_srcs|["../other/X.java"]|c_apk app: `java_srcs` and `res_xml` entries must be plain file names of this package
java_srcs|["sub/X.java"]|c_apk app: `java_srcs` and `res_xml` entries must be plain file names of this package
java_srcs|["X.kt"]|c_apk: `java_srcs` entries must be plain file names ending in .java
java_srcs|["X.java"]|c_apk app: `java_classes` must list the classes of `java_srcs`
java_classes|["org.example.club.X"]|c_apk app: `java_classes` must list the classes of `java_srcs`
res_xml|["x/a.xml"]|c_apk app: `java_srcs` and `res_xml` entries must be plain file names of this package
res_xml|["A.xml"]|c_apk app: `res_xml` names must be lower-case
application_class|"org.example.club.X"|c_apk app: `application_class`
java_packages|["org.example.*"]|c_apk app: `java_packages`
java_packages|["java.util"]|`java_packages` entry .java.util. is a platform or runtime package
java_packages|["javax.x"]|`java_packages` entry .javax.x. is a platform or runtime package
java_packages|["android.app"]|`java_packages` entry .android.app. is a platform or runtime package
java_packages|["androidx.core"]|`java_packages` entry .androidx.core. is a platform or runtime package
java_packages|["dalvik.system"]|`java_packages` entry .dalvik.system. is a platform or runtime package
java_packages|["kotlin.io"]|`java_packages` entry .kotlin.io. is a platform or runtime package
java_packages|["com.android.x"]|`java_packages` entry .com.android.x. is a platform or runtime package
java_packages|["org"]|`java_packages` entry .org. must be a dotted
receivers|[{"name": "org.example.club.X"}]|c_apk app: the receiver
receivers|[{"name": "org.example.club.X", "raw": "<a/>"}]|c_apk app: a receiver is a dict
launch_mode|"fast"|c_apk app: `launch_mode`
lock_task_mode|"always"|c_apk app: `lock_task_mode`
soft_input_mode|"x"|c_apk app: `soft_input_mode`
exclude_from_recents|"yes"|c_apk app: `exclude_from_recents`
categories|["LAUNCHER"]|c_apk app: `categories`
permissions|["BIND_DEVICE_ADMIN"]|c_apk app: `permissions`
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
