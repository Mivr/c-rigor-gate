#!/usr/bin/env bash
# Self-test of the Android shared object rule `c_android_so` (T-G2) and the NDK twins of the Linux facts (T-G1).
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

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
