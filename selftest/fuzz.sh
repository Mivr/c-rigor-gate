#!/usr/bin/env bash
# Self-test of c_fuzz (T024): the fuzz run is an RE action with a symbolized report and the crash
# input as a declared output. Needs only bash, python3 (stdlib) and tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
PLAT=toolchains//:linux_fuzz
scratch="selftest/scratch_fuzz"
pkg="//selftest/scratch_fuzz"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
# out_of <log> <target-fragment>: path printed by --show-output for that target
out_of() { awk -v t="$2" 'index($1, t) && /buck-out/ {print $2}' "$1" | tail -1; }
# actions executed by the last buck2 command (0 when everything came from a cache)
executed() { "${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$'; }
# build_out <var> <target>: builds [sub]target, sets $var to its output file
build_out() {
  local var="$1" target="$2" log="$out/$step.log" p
  run "$log" build --target-platforms "$PLAT" "$target" --show-output || fail "$CUR: build $target failed" "$log"
  p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}

mkdir -p "$scratch"
cp -R selftest/fuzz_product/. "$scratch/"

begin "heap overflow behind a 4-byte magic prefix: the test fails and the report names file:line function"
log="$out/heap.log"
if run "$log" test --target-platforms "$PLAT" "$pkg/heap:fz"; then fail "$CUR: the crashing target passed" "$log"; fi
grep -q "AddressSanitizer: heap-buffer-overflow" "$log" || fail "$CUR: wrong crash kind" "$log"
grep -Eq "in LLVMFuzzerTestOneInput selftest/scratch_fuzz/heap/fz_fuzz\.c:12:" "$log" || fail "$CUR: the frame is not symbolized as 'in LLVMFuzzerTestOneInput <file>:12'" "$log"
grep -Eq "SUMMARY: AddressSanitizer: heap-buffer-overflow selftest/scratch_fuzz/heap/fz_fuzz\.c:12:[0-9]+ in LLVMFuzzerTestOneInput" "$log" || fail "$CUR: SUMMARY lacks file:line function" "$log"

begin "heap: the crash input is a readable output that starts with the magic and replays the failure"
build_out heap_crash "$pkg/heap:fz[crash]"
build_out heap_report "$pkg/heap:fz[report]"
[ "$(head -c 4 "$heap_crash")" = "HEAP" ] || fail "$CUR: crash input does not start with HEAP: $(head -c 8 "$heap_crash" | od -c | head -1)"
grep -q "^reproducer: crash-" "$heap_report" || fail "$CUR: report does not name the reproducer"
if grep -Eq '/var/tmp|/home/|/data/|/tmp/|/worker|/execroot' "$heap_report"; then fail "$CUR: absolute path in the report: $(grep -E '/var/tmp|/home/|/data/|/tmp/|/worker|/execroot' "$heap_report" | head -3)"; fi
run "$out/bin.log" build --target-platforms "$PLAT" "$pkg/heap:fz__bin" --show-output || fail "$CUR: build binary" "$out/bin.log"
heap_bin="$(out_of "$out/bin.log" fz__bin)"
mkdir -p "$out/replay"
(cd "$out/replay" && "$root/$heap_bin" "$root/$heap_crash") > "$out/replay.log" 2>&1; rc=$?
[ "$rc" -ne 0 ] && grep -q "AddressSanitizer: heap-buffer-overflow" "$out/replay.log" || fail "$CUR: feeding the crash input back did not reproduce (rc $rc)" "$out/replay.log"
echo "  reproducer: $heap_crash"
echo "  --- example symbolized report ($heap_report) ---"; sed 's/^/  | /' "$heap_report"

begin "signed overflow behind a 4-byte magic prefix: UBSan report names file:line function; input replays"
log="$out/ubsan.log"
if run "$log" test --target-platforms "$PLAT" "$pkg/ubsan:fz"; then fail "$CUR: the crashing target passed" "$log"; fi
grep -Eq "selftest/scratch_fuzz/ubsan/fz_fuzz\.c:18:[0-9]+: runtime error: signed integer overflow" "$log" || fail "$CUR: no 'file:18: runtime error: signed integer overflow'" "$log"
grep -Eq "in LLVMFuzzerTestOneInput selftest/scratch_fuzz/ubsan/fz_fuzz\.c:18:" "$log" || fail "$CUR: the frame is not symbolized" "$log"
build_out ub_crash "$pkg/ubsan:fz[crash]"
[ "$(head -c 4 "$ub_crash")" = "OVER" ] || fail "$CUR: crash input does not start with OVER"
run "$out/bin.log" build --target-platforms "$PLAT" "$pkg/ubsan:fz__bin" --show-output || fail "$CUR: build binary" "$out/bin.log"
ub_bin="$(out_of "$out/bin.log" fz__bin)"
(cd "$out/replay" && "$root/$ub_bin" "$root/$ub_crash") > "$out/replay.log" 2>&1; rc=$?
[ "$rc" -ne 0 ] && grep -q "signed integer overflow" "$out/replay.log" || fail "$CUR: feeding the crash input back did not reproduce (rc $rc)" "$out/replay.log"

begin "clean fuzz target passes, with an empty crash output and a report that says so"
must_log="$out/clean.log"
run "$must_log" test --target-platforms "$PLAT" "$pkg/clean:fz" || fail "$CUR: clean target failed" "$must_log"
build_out clean_crash "$pkg/clean:fz[crash]"
build_out clean_report "$pkg/clean:fz[report]"
[ ! -s "$clean_crash" ] || fail "$CUR: a passing run has a non-empty crash output"
[ "$(cat "$clean_report")" = "fuzz: -seed=1 -runs=200000 verdict: pass" ] || fail "$CUR: unexpected clean report: $(cat "$clean_report")"

begin "two cold runs (fresh action keys) give byte-identical reports and crash inputs, for fail and for pass"
cp "$heap_report" "$out/heap.1"; cp "$heap_crash" "$out/heapc.1"
build_out ub_report "$pkg/ubsan:fz[report]"; cp "$ub_report" "$out/ub.1"; cp "$ub_crash" "$out/ubc.1"
cp "$clean_report" "$out/clean.1"; cp "$clean_crash" "$out/cleanc.1"
for k in heap ubsan clean; do printf 'const char fuzz_scratch_nonce[] = "%s";\n' "$(date +%s%N)-$$-$k" >> "$scratch/$k/fz_fuzz.c"; done
build_out heap_report2 "$pkg/heap:fz[report]"
echo "  cold build of heap:fz[report]: $(executed) actions executed (compile, link, fuzz_run)"
"${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -q 'fuzz_run' || fail "$CUR: the second cold run did not execute the fuzz action"
build_out heap_crash2 "$pkg/heap:fz[crash]"
build_out ub_report2 "$pkg/ubsan:fz[report]"; build_out ub_crash2 "$pkg/ubsan:fz[crash]"
build_out clean_report2 "$pkg/clean:fz[report]"; build_out clean_crash2 "$pkg/clean:fz[crash]"
cmp -s "$out/heap.1" "$heap_report2" || fail "$CUR: heap report differs between cold runs: $(diff "$out/heap.1" "$heap_report2" | head -5)"
cmp -s "$out/heapc.1" "$heap_crash2" || fail "$CUR: heap crash input differs between cold runs"
cmp -s "$out/ub.1" "$ub_report2" || fail "$CUR: ubsan report differs between cold runs: $(diff "$out/ub.1" "$ub_report2" | head -5)"
cmp -s "$out/ubc.1" "$ub_crash2" || fail "$CUR: ubsan crash input differs between cold runs"
cmp -s "$out/clean.1" "$clean_report2" || fail "$CUR: clean report differs between cold runs"
cmp -s "$out/cleanc.1" "$clean_crash2" || fail "$CUR: clean crash output differs between cold runs"
echo "  cold/cold: reports and crash inputs byte-identical (heap, ubsan, clean)"

begin "a warm rebuild executes 0 actions"
run "$out/warm.log" build --target-platforms "$PLAT" "$pkg/heap:fz[report]" "$pkg/ubsan:fz[report]" "$pkg/clean:fz[report]" "$pkg/heap:fz[crash]" "$pkg/ubsan:fz[crash]" "$pkg/clean:fz[crash]" || fail "$CUR" "$out/warm.log"
n="$(executed)"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the warm build"
echo "  warm build: $n actions executed"

echo "elapsed ${SECONDS}s"
echo "fuzz selftest: all $step steps passed"
