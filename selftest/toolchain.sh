#!/usr/bin/env bash
# Self-test of the hermetic C toolchain. Runs every acceptance check, stops at the first
# failure and names it. Needs only bash, python3 (stdlib) and tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
PLAT=toolchains//:linux_
scratch="selftest/scratch"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "selftest/scratch_x11" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
# run <logfile> <args...>: runs buck2, stores ANSI-stripped combined output, returns buck2's status
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
must_pass() { local log="$out/$step.log"; run "$log" "$@" || fail "$CUR: buck2 $* failed" "$log"; }
must_fail_with() { # <regex> <args...>
  local re="$1"; shift; local log="$out/$step.log"
  if run "$log" "$@"; then fail "$CUR: buck2 $* unexpectedly succeeded" "$log"; fi
  grep -Eq "$re" "$log" || fail "$CUR: failed, but not for the right reason (wanted /$re/)" "$log"
}

begin "hello builds on RE (release)"
must_pass build //examples/hello:hello

begin "hello tests pass: release"
must_pass test //examples/hello/...
begin "hello tests pass: san"
must_pass test --target-platforms ${PLAT}san //examples/hello/...
begin "hello tests pass: cov"
must_pass test --target-platforms ${PLAT}cov //examples/hello/...

begin "coverage report from the fetched llvm-cov / llvm-profdata (line, branch, MC/DC)"
log="$out/$step.log"
run "$log" build --target-platforms ${PLAT}cov //examples/hello:hello_test_coverage --show-output || fail "$CUR" "$log"
rep="$(awk '/hello_test_coverage/ && /buck-out/ {print $2}' "$log" | tail -1)"
[ -f "$rep" ] || fail "$CUR: no report file" "$log"
grep -q "MC/DC" "$rep" && grep -q "Branches" "$rep" && grep -Eq "^(examples/hello/)?hello\.c +[0-9]+ +0 +100\.00%" "$rep" || fail "$CUR: report lacks expected content: $(cat "$rep")"
grep -q "MC/DC" "$(dirname "$rep")/detail.txt" || true

begin "sealed flags: bad/warn fails to build for -Werror (unused variable)"
must_fail_with "unused variable.*-Werror|-Werror.*unused variable" build //examples/bad/warn:warn

begin "sealed flags: warn also fails in every mode"
for m in release san cov fuzz; do
  must_fail_with "unused variable" build --target-platforms ${PLAT}$m //examples/bad/warn:warn
done

begin "san: bad/ubsan fails with an UndefinedBehaviorSanitizer report"
must_fail_with "runtime error: signed integer overflow" test --target-platforms ${PLAT}san //examples/bad/ubsan:ubsan
begin "san: bad/asan fails with heap-buffer-overflow"
must_fail_with "AddressSanitizer: heap-buffer-overflow" test --target-platforms ${PLAT}san //examples/bad/asan:asan
begin "san: bad/leak fails with LeakSanitizer"
must_fail_with "LeakSanitizer: detected memory leaks" test --target-platforms ${PLAT}san //examples/bad/leak:leak

begin "fuzz: fuzzme finds its planted crash with -seed=1 -runs=200000 (3 times, same crash)"
sums=""
for i in 1 2 3; do
  log="$out/fuzz$i.log"
  if run "$log" test --target-platforms ${PLAT}fuzz //examples/bad/fuzzme:fuzzme; then fail "$CUR: fuzzme did not fail" "$log"; fi
  grep -q "fuzz: -seed=1 -runs=200000 verdict: fail" "$log" || fail "$CUR: seed/runs not reported" "$log"
  grep -q "AddressSanitizer: heap-buffer-overflow" "$log" || fail "$CUR: wrong crash kind" "$log"
  grep -q "reproducer: crash-" "$log" || fail "$CUR: no crash artifact named in the report" "$log"
  grep -Eq "in LLVMFuzzerTestOneInput examples/bad/fuzzme/fuzzme\.c:[0-9]+" "$log" || fail "$CUR: crash not symbolized" "$log"
  sums="$sums $(grep -o 'crash-[0-9a-f]*' "$log" | head -1)"
done
[ "$(echo $sums | tr ' ' '\n' | sort -u | wc -l)" = 1 ] || fail "$CUR: crash input differs between runs:$sums"

begin "sealed flags: macros reject every flag argument"
mkdir -p "$scratch"
for macro in c_library c_binary c_test c_fuzz; do
  for kw in compiler_flags preprocessor_flags linker_flags copts cflags exported_linker_flags exported_preprocessor_flags; do
    cat > "$scratch/BUCK" <<BUCK
load("@gate//rules:c.bzl", "$macro")
$macro(name = "x", srcs = ["x.c"], $kw = ["-Wno-error"])
BUCK
    log="$out/neg.log"
    if run "$log" build //selftest/scratch:x; then fail "$CUR: $macro accepted $kw" "$log"; fi
    grep -Eq "$kw" "$log" && grep -Eq "[Ee]xtra named|unexpected|no parameter" "$log" || fail "$CUR: $macro/$kw rejected for the wrong reason" "$log"
  done
done
rm -rf "$scratch"

begin "sealed flags: srcs/headers cannot carry per-file flags (tuple src, non-.c src, dict or non-.h headers)"
mkdir -p "$scratch"
reject() { # <regex> <macro-call-args>
  local re="$1" macro="$2" args="$3" log="$out/rej.log"
  printf 'load("@gate//rules:c.bzl", "%s")\n%s(name = "x", %s)\n' "$macro" "$macro" "$args" > "$scratch/BUCK"
  if run "$log" build //selftest/scratch:x; then fail "$CUR: $macro($args) was accepted" "$log"; fi
  grep -Eq "$re" "$log" || fail "$CUR: $macro($args) rejected for the wrong reason (wanted /$re/)" "$log"
}
for macro in c_library c_binary c_test c_fuzz; do
  reject "entries must be plain strings, got tuple" "$macro" 'srcs = [("a.c", ["-Wno-error"])]'
  reject "entries must be plain strings, got list" "$macro" 'srcs = [["a.c", "-Wno-error"]]'
  reject "must be plain file names ending in .c" "$macro" 'srcs = ["a.cpp"]'
  reject "must be plain file names ending in .c" "$macro" 'srcs = ["//other:gen"]'
  reject "must be a list of plain file names, got dict" "$macro" 'srcs = {"a.c": ["-Wno-error"]}'
done
reject "must be a list of plain file names, got dict" c_library 'srcs = ["a.c"], headers = {"a.h": "a.h"}'
reject "entries must be plain strings, got tuple" c_library 'srcs = ["a.c"], headers = [("a.h", ["-Wno-error"])]'
reject "must be plain file names ending in .h" c_library 'srcs = ["a.c"], headers = ["a.hpp"]'
rm -rf "$scratch"

begin "X11 from the pinned sysroot (T117): system_libs = [\"X11\"] links libX11 and a test calls XOpenDisplay(\":99999\") in release and san"
xs="selftest/scratch_x11"
mkdir -p "$xs/ok" "$xs/bare"
cp selftest/x11_product/xlink.h selftest/x11_product/xlink.c selftest/x11_product/xlink_test.c "$xs/ok/"
cp selftest/x11_product/xlink.h selftest/x11_product/xlink.c selftest/x11_product/xlink_test.c "$xs/bare/"
sed -i 's|scratch_x11/ok|scratch_x11/bare|' "$xs/bare/xlink_test.c"
cat > "$xs/ok/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_library", "c_test")
c_library(name = "xlink", srcs = ["xlink.c"], headers = ["xlink.h"], system_libs = ["X11"])
c_test(name = "xlink_test", srcs = ["xlink_test.c"], deps = [":xlink"])
BUCK
cat > "$xs/bare/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_library", "c_test")
c_library(name = "xlink", srcs = ["xlink.c"], headers = ["xlink.h"])
c_test(name = "xlink_test", srcs = ["xlink_test.c"], deps = [":xlink"])
BUCK
for m in release san; do
  must_pass build --target-platforms ${PLAT}$m //selftest/scratch_x11/ok:xlink_test_results --show-output
  res="$(awk '/xlink_test_results/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
  [ -f "$res" ] || fail "$CUR: no results file ($m)" "$out/$step.log"
  python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
tests, summary = rows[:-1], rows[-1]["summary"]
assert sorted(r["id"] for r in tests) == ["x11/keysym", "x11/no_display"], tests
assert all(r["status"] == "pass" and r["asserts"] > 0 for r in tests), tests
assert summary == {"total": 2, "passed": 2}, summary
' "$res" || fail "$CUR: results are not two passing tests ($m)"
  echo "  $m: x11/no_display and x11/keysym pass"
done

begin "X11 is opt-in: the same code without system_libs does not link (undefined XOpenDisplay), in release and san"
for m in release san; do
  must_fail_with "undefined symbol: XOpenDisplay" build --target-platforms ${PLAT}$m //selftest/scratch_x11/bare:xlink_test
  echo "  $m: bare link fails on XOpenDisplay"
done
rm -rf "$xs"

begin "hardened release profile (T139): automatic variables start zeroed; an array overrun is NOT trapped"
mkdir -p "$scratch"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_test")
c_test(name = "hx", srcs = ["hx.c"])
BUCK
cat > "$scratch/hx.c" <<'C'
#include <stddef.h>
#include <string.h>
#include "ctest/ctest.h"

static volatile size_t g_idx = 4;
struct box { int a[4]; int b; };

/* An index that is one past a fixed array inside a struct: written through, it lands in the neighbour. */
__attribute__((noinline)) static void t_overrun(ctest_t *t) {
    struct box s;
    s.b = 0;
    memset(s.a, 0, sizeof s.a);
    s.a[g_idx] = 7;
    CHECK_EQ_I64(t, s.b, 0);
}

__attribute__((noinline)) static void dirty(void) {
    unsigned char junk[256];
    size_t i;
    for (i = 0; i < sizeof junk; i++) { junk[i] = 0xA5; }
    __asm__ volatile("" : : "r"(junk) : "memory");
}
__attribute__((noinline)) static void leave(unsigned char *p) { __asm__ volatile("" : : "r"(p) : "memory"); }
__attribute__((noinline)) static long sum_uninit(void) {
    unsigned char buf[256];
    long s = 0;
    size_t i;
    leave(buf);
    for (i = 0; i < sizeof buf; i++) { s += buf[i]; }
    return s;
}
/* Reads an automatic array nobody wrote, right after a call left 0xA5 on that part of the stack. */
static void t_uninit(ctest_t *t) { dirty(); CHECK_EQ_I64(t, sum_uninit(), 0); }

CTEST_SUITE("hx", { "overrun", t_overrun }, { "uninit", t_uninit })
C
log="$out/$step.log"
run "$log" build //selftest/scratch:hx_results --show-output || fail "$CUR: build failed" "$log"
res="$(awk '/hx_results/ && /buck-out/ {print $2}' "$log" | tail -1)"
[ -f "$res" ] || fail "$CUR: no results file" "$log"
python3 -I -c '
import json, sys
rows = {r["id"]: r for r in (json.loads(l) for l in open(sys.argv[1])) if "id" in r}
assert sorted(rows) == ["hx/overrun", "hx/uninit"], rows
assert rows["hx/uninit"]["status"] == "pass", rows["hx/uninit"]  # -ftrivial-auto-var-init=zero
# not covered: -fsanitize=bounds is not in the release profile (docs/toolchain.md), so the write lands in the neighbour
assert rows["hx/overrun"]["status"] == "fail" and "signal" not in rows["hx/overrun"]["reason"] and "s.b" in rows["hx/overrun"]["reason"], rows["hx/overrun"]
' "$res" || fail "$CUR: results are not the expected two" "$res"
rm -rf "$scratch"

begin "remote: compile, link and test all execute on RE (fresh, uncached sources)"
mkdir -p "$scratch"
nonce="$(date +%s%N)-$$"
cat > "$scratch/BUCK" <<'BUCK'
load("@gate//rules:c.bzl", "c_library", "c_test")
c_library(name = "l", srcs = ["l.c"], headers = ["l.h"])
c_test(name = "t", srcs = ["t.c"], deps = [":l"])
BUCK
printf 'int scratch_one(void);\n' > "$scratch/l.h"
# The nonce lands in the object file, so compile, archive and link cannot be cache hits.
printf '#include "l.h"\nconst char scratch_nonce[] = "%s";\nint scratch_one(void) { return 1; }\n' "$nonce" > "$scratch/l.c"
printf '#include "l.h"\nconst char scratch_nonce_t[] = "%s";\nint main(void) { return scratch_one() == 1 ? 0 : 1; }\n' "$nonce" > "$scratch/t.c"
must_pass test //selftest/scratch:t
"${B[@]}" log what-ran 2>/dev/null | strip_ansi > "$out/whatran.txt"
for want in "(c_compile l.c)" "(c_compile t.c)" "(archive " "(cxx_link_executable)"; do
  grep -qF "$want" "$out/whatran.txt" || fail "$CUR: no $want action in what-ran" "$out/whatran.txt"
done
grep -q '^test.run' "$out/whatran.txt" || fail "$CUR: no test.run in what-ran" "$out/whatran.txt"
# Fresh-nonce actions (the scratch targets and their test run) must have executed on RE. Dependency actions (the
# fetched toolchain, the sysroot, ctest) are not nonce-stamped, so a cache hit on them is legitimate and depends on
# farm and daemon history; they may be `cache` or `re`. Nothing may be `local`.
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' '
    NF >= 3 && ($1 == "test.run" || $2 ~ /^root\/\/selftest\/scratch:/) && $3 !~ /^re\(/ { bad = 1 }
    END { exit !bad }'; then
  fail "$CUR: a fresh-nonce action did not run on RE" "$out/whatran.txt"
fi
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' 'NF >= 3 && $3 !~ /^(re\(|cache)/ { bad = 1 } END { exit !bad }'; then
  fail "$CUR: an action ran locally or on an unknown executor" "$out/whatran.txt"
fi
grep -q "local: 0)" "$out/$step.log" || fail "$CUR: local executions reported" "$out/$step.log"
rm -rf "$scratch"

begin "hermetic: no action command references host paths or the host clang"
python3 - "$root" <<'PY' || fail "$CUR"
import json, re, subprocess, sys
root = sys.argv[1]
bad = re.compile(r'(^|[\s=:\'"])/(usr/include|usr/lib|usr/local|usr/bin|lib|lib64|opt)(/|\b)')
seen = 0
for plat in ("release", "san", "cov", "fuzz"):
    targets = "deps(//examples/hello:hello_test)" if plat != "fuzz" else "deps(//examples/bad/fuzzme:fuzzme)"
    p = subprocess.run(["tools/buck2", "aquery", "--target-platforms", "toolchains//:linux_" + plat,
                        targets, "--output-attribute=cmd"], cwd=root, capture_output=True, text=True)
    if p.returncode:
        sys.exit("aquery failed: " + p.stderr[-500:])
    for key, val in json.loads(p.stdout).items():
        cmd = val.get("cmd")
        if not cmd:
            continue
        seen += 1
        for tok in re.split(r'[\s,\[\]]+', cmd):
            if tok.startswith("/") and tok != "/bin/sh":
                sys.exit("absolute host path %r in %s" % (tok, key))
            if re.search(r'(^|/)(gcc|cc|c\+\+|ld|clang|clang\+\+|clang-\d+)$', tok) and not tok.startswith("buck-out/"):
                sys.exit("host tool %r in %s" % (tok, key))
        if bad.search(cmd):
            sys.exit("host path in %s: %s" % (key, cmd[:400]))
        if "clang" in cmd and "buck-out/v2/art/toolchains/" not in cmd:
            sys.exit("clang not from the fetched archive in " + key)
print("checked %d action commands" % seen)
PY

begin "warm: a second build executes 0 actions"
must_pass build //examples/hello:hello
must_pass build //examples/hello:hello
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the second build"

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
