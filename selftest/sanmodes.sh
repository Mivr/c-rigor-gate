#!/usr/bin/env bash
# Self-test of the msan and tsan build modes (T125). Fixtures: selftest/sanmodes/**, copied into a scratch package per
# case. Needs only bash, python3 (stdlib) and tools/buck2. Every case runs twice (the second time with a fresh nonce in
# the test source, so the results action really executes again) and the verdicts and reports must be identical.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
PLAT=toolchains//:linux_
scratch="selftest/scratch_sanmodes"
pkg="//selftest/scratch_sanmodes"
fx="selftest/sanmodes"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
checks=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
ok() { checks=$((checks + 1)); echo "  ok: $1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }

# mkpkg <name> <BUCK text> <file...>: a scratch package; each file is <fixture>:<name in the package>
mkpkg() {
  local name="$1" buck="$2" spec; shift 2
  mkdir -p "$scratch/$name"
  for spec in "$@"; do
    cp "$fx/${spec%%:*}" "$scratch/$name/${spec##*:}"
    sed -i "s|@PKG@|$name|g" "$scratch/$name/${spec##*:}"
  done
  printf '%s\n' "$buck" > "$scratch/$name/BUCK"
}

# build_res <mode> <package> <target>: builds `<target>_results` in the mode; sets RES (results.jsonl), REP (san report)
build_res() {
  local mode="$1" name="$2" target="$3" log="$out/b.$mode.$name.$target.log"
  run "$log" build --target-platforms "${PLAT}$mode" "$pkg/$name:${target}_results" "$pkg/$name:${target}_results[san_report]" --show-output \
    || fail "$CUR: build $name:${target}_results ($mode) failed" "$log"
  RES="$(awk -v t="${target}_results " 'index($1, t) && !index($1, "[") && /buck-out/ {print $2}' "$log" | tail -1)"
  REP="$(awk 'index($1, "[san_report]") && /buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$RES" ] || fail "$CUR: no results file for $name:$target ($mode): '$RES'" "$log"
  [ -f "$REP" ] || fail "$CUR: no san report for $name:$target ($mode): '$REP'" "$log"
}

# verdict <results.jsonl>: "pass" or "fail: <reason>" of the single test, after a check of the summary line
verdict() {
  python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
tests, summary = rows[:-1], rows[-1]["summary"]
assert len(tests) == 1, tests
t = tests[0]
assert summary == {"total": 1, "passed": 1 if t["status"] == "pass" else 0}, summary
print("pass" if t["status"] == "pass" else "fail: " + t["reason"])
' "$1"
}

# nonce <package> <test file>: a fresh constant at the end of the test source: the test binary, hence its results
# action, is new
nonce() { printf 'const char sanmodes_nonce[] = "%s";\n' "$(date +%s%N)-$$-$RANDOM" >> "$scratch/$1/$2"; }

# expect_fail <mode> <package> <target> <needle-regex> <file:line regex>: results FAIL with a symbolized report
expect_fail() {
  local mode="$1" name="$2" target="$3" needle="$4" loc="$5" v1 v2 r1 r2
  build_res "$mode" "$name" "$target"; v1="$(verdict "$RES")" || fail "$CUR: bad results file ($name, $mode)"
  cp "$RES" "$out/res.1"; cp "$REP" "$out/rep.1"
  [[ "$v1" == fail:* ]] || fail "$CUR: $name:$target passed in $mode: $v1" "$RES"
  [[ "$v1" =~ $loc ]] || fail "$CUR: the failure reason has no '$loc': $v1"
  grep -Eq "$needle" "$REP" || fail "$CUR: the report has no '$needle'" "$REP"
  grep -Eq "$loc" "$REP" || fail "$CUR: the report does not name '$loc'" "$REP"
  if grep -Eq '/var/tmp|/home/|/data/|/tmp/|/worker|/execroot' "$REP"; then fail "$CUR: absolute path in the report" "$REP"; fi
  echo "  $mode verdict: $v1"
  echo "  --- report (first lines) ---"; head -n 14 "$REP" | sed 's/^/  | /'
  ok "$name:$target FAILS in $mode, symbolized, naming $loc"
  nonce "$name" "$6"
  build_res "$mode" "$name" "$target"; v2="$(verdict "$RES")"
  [ "$v1" = "$v2" ] || fail "$CUR: the verdict changed between runs: '$v1' vs '$v2'"
  cmp -s "$out/res.1" "$RES" || fail "$CUR: results differ between runs"
  cmp -s "$out/rep.1" "$REP" || fail "$CUR: the report differs between runs: $(diff "$out/rep.1" "$REP" | head -5)"
  ok "$name:$target ($mode): second run identical (verdict, results, report)"
}

# expect_pass <mode> <package> <target> <test file>
expect_pass() {
  local mode="$1" name="$2" target="$3" v1 v2
  build_res "$mode" "$name" "$target"; v1="$(verdict "$RES")" || fail "$CUR: bad results file ($name, $mode)"
  cp "$RES" "$out/res.1"; cp "$REP" "$out/rep.1"
  [ "$v1" = pass ] || fail "$CUR: $name:$target did not pass in $mode: $v1" "$REP"
  [ "$(cat "$REP")" = "" ] || fail "$CUR: a passing run has a sanitizer report" "$REP"
  nonce "$name" "$4"
  build_res "$mode" "$name" "$target"; v2="$(verdict "$RES")"
  [ "$v2" = pass ] || fail "$CUR: second run: $v2"
  cmp -s "$out/res.1" "$RES" || fail "$CUR: results differ between runs"
  ok "$name:$target passes in $mode (twice, empty report)"
}

# no_target <mode> <package> <target> <regex>: `<target>_results` does not exist in the mode
no_target() {
  local mode="$1" name="$2" target="$3" log="$out/nt.$mode.$name.$target.log"
  if run "$log" build --target-platforms "${PLAT}$mode" "$pkg/$name:${target}_results"; then
    fail "$CUR: $name:${target}_results was built in $mode" "$log"
  fi
  grep -Eq "incompatible|not compatible" "$log" || fail "$CUR: the build failed, but not as an incompatible target" "$log"
  ok "$name:${target}_results does not exist in $mode"
}

BUCK_UNINIT='load("@gate//rules:c.bzl", "c_library", "c_test")
c_library(name = "pair", srcs = ["pair.c"], headers = ["pair.h"])
c_test(name = "pair_test", srcs = ["pair_test.c"], deps = [":pair"])'
BUCK_RACE='load("@gate//rules:c.bzl", "c_library", "c_test")
c_library(name = "counter", srcs = ["counter.c"], headers = ["counter.h"], system_libs = ["pthread"])
c_test(name = "counter_test", srcs = ["counter_test.c"], deps = [":counter"], threads = True)
c_test(name = "plain_test", srcs = ["counter_test.c"], deps = [":counter"])'
BUCK_X11='load("@gate//rules:c.bzl", "c_library", "c_test")
c_library(name = "xlink", srcs = ["xlink.c"], headers = ["xlink.h"], system_libs = ["X11"])
c_test(name = "xlink_test", srcs = ["xlink_test.c"], deps = [":xlink"])'

rm -rf "$scratch"
mkpkg uninit "$BUCK_UNINIT" uninit/pair.h:pair.h uninit/pair.c:pair.c uninit/pair_test.c:pair_test.c
mkpkg uninit_fixed "$BUCK_UNINIT" uninit/pair.h:pair.h uninit/pair_fixed.c:pair.c uninit/pair_test.c:pair_test.c
mkpkg race "$BUCK_RACE" race/counter.h:counter.h race/counter.c:counter.c race/counter_test.c:counter_test.c
mkpkg race_fixed "$BUCK_RACE" race/counter.h:counter.h race/counter_locked.c:counter.c race/counter_test.c:counter_test.c
mkpkg x11 "$BUCK_X11" ../x11_product/xlink.h:xlink.h ../x11_product/xlink.c:xlink.c ../x11_product/xlink_test.c:xlink_test.c
sed -i 's|scratch_x11/ok|scratch_sanmodes/x11|' "$scratch/x11/xlink_test.c"
bugline="$(grep -n 'if (p->b > 0)' "$scratch/uninit/pair.c" | cut -d: -f1)"
raceline="$(grep -n 'g_count += 1;' "$scratch/race/counter.c" | cut -d: -f1)"

begin "msan: a read of an uninitialised struct field that decides a branch FAILS, symbolized, naming the line"
expect_fail msan uninit pair_test "MemorySanitizer: use-of-uninitialized-value" "selftest/scratch_sanmodes/uninit/pair\.c:$bugline" pair_test.c

begin "msan: the fixed twin passes"
expect_pass msan uninit_fixed pair_test pair_test.c

begin "the same bug passes in release and san: the reason the mode exists"
for m in release san; do
  build_res "$m" uninit pair_test
  v="$(verdict "$RES")" || fail "$CUR: bad results file"
  [ "$v" = pass ] || fail "$CUR: the uninitialised read was reported in $m: $v" "$REP"
  ok "uninit:pair_test PASSES in $m although it reads uninitialised memory (only msan sees it)"
done

begin "tsan: two pthreads writing one variable without a lock FAIL, symbolized, naming the line"
expect_fail tsan race counter_test "ThreadSanitizer: data race" "selftest/scratch_sanmodes/race/counter\.c:$raceline" counter_test.c

begin "tsan: the mutex twin passes"
expect_pass tsan race_fixed counter_test counter_test.c

begin "the same race passes in release and san, and msan has nothing to say about it"
for m in release san msan; do
  build_res "$m" race counter_test
  v="$(verdict "$RES")" || fail "$CUR: bad results file"
  [ "$v" = pass ] || fail "$CUR: the race was reported in $m: $v" "$REP"
  ok "race:counter_test PASSES in $m"
done

begin "which tests have which results target"
no_target tsan race_fixed plain_test
no_target tsan uninit pair_test
build_res msan race_fixed plain_test; [ "$(verdict "$RES")" = pass ] || fail "$CUR: plain_test msan"
ok "race_fixed:plain_test (threads = False) has an msan result and no tsan result"
for m in release san; do
  build_res "$m" x11 xlink_test
  ok "x11:xlink_test has a $m result"
done
no_target msan x11 xlink_test
no_target tsan x11 xlink_test

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($checks)"
