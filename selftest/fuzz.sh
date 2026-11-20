#!/usr/bin/env bash
# Self-test of c_fuzz (T024): the fuzz run is an RE action with a symbolized report and the crash
# input as a declared output. Needs only bash, python3 (stdlib) and tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
RIGOR=(gate/rigor)
RPLAT=toolchains//:linux_release
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

# ---- T126: corpus replay, the budget, and the judge (`rigor fuzz`) ------------------------------------------------
P=//selftest/scratch_fuzz
M_BUG="$P/lib:parse"; M_FIX="$P/libfixed:parse"; M_LONE="$P/lone:other"
# fuzz_out <var> <pkg> <sub>: path of $pkg:fz[sub] after building it in the fuzz mode
fuzz_out() {
  local var="$1" pkg="$2" sub="$3" log="$out/fo.$2.$3.log" fp
  run "$log" build --target-platforms "$PLAT" "$P/$pkg:fz[$sub]" --show-output || fail "$CUR: build $pkg[$sub]" "$log"
  fp="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"; [ -f "$fp" ] || fail "$CUR: no output for $pkg[$sub]" "$log"
  printf -v "$var" '%s' "$fp"
}
# collect <dir> <pkg>...: the results directory of the judge for those fuzz packages
collect() {
  local dir="$1" pkg sub cpath sep="" idx="{"; shift; mkdir -p "$dir"
  for pkg in "$@"; do
    for sub in stats verdict report replayed crash; do
      fuzz_out cpath "$pkg" "$sub"
      case "$sub" in stats) cp -f "$cpath" "$dir/$pkg.stats.json";; *) cp -f "$cpath" "$dir/$pkg.$sub";; esac
    done
    idx="$idx$sep\"$P/$pkg:fz\":\"$pkg\""; sep=","
  done
  printf '%s}\n' "$idx" > "$dir/index.json"
}
# facts <dir> <target>...: the facts files (release mode) of those targets, copied into <dir>
facts() {
  local dir="$1" t n=0 p log="$out/facts.log"; shift; mkdir -p "$dir"
  for t in "$@"; do
    run "$log" build --target-platforms "$RPLAT" "$t" --show-output || fail "$CUR: facts build $t" "$log"
    p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"; [ -f "$p" ] || fail "$CUR: no facts for $t" "$log"
    n=$((n + 1)); cp -f "$p" "$dir/f$n.json"
  done
}
# judge <case> <expected-exit> <facts-dir> <results-dir> <policy> [regressions]: runs the judge twice; same bytes
judge() {
  local name="$1" want="$2" fd="$3" rd="$4" pol="$5" reg="${6:-}" rc args
  args=(fuzz --results "$rd" --policy "$pol" --facts "$fd")
  [ -n "$reg" ] && args+=(--regressions "$reg")
  for n in 1 2; do
    "${RIGOR[@]}" "${args[@]}" --out "$out/$name.$n.json" > "$out/$name.$n.txt" 2>&1; rc=$?
    [ "$rc" = "$want" ] || fail "$CUR: $name run $n exited $rc, wanted $want" "$out/$name.$n.txt"
  done
  cmp -s "$out/$name.1.json" "$out/$name.2.json" || fail "$CUR: $name: two judge runs differ"
  cmp -s "$out/$name.1.txt" "$out/$name.2.txt" || fail "$CUR: $name: two judge console outputs differ"
}
expect_rule() { grep -q "\"rule\":\"$2\"" "$out/$1.1.json" || fail "$CUR: $1: no finding $2" "$out/$1.1.txt"; }
expect_no_rule() { ! grep -q "\"rule\":\"$2\"" "$out/$1.1.json" || fail "$CUR: $1: unexpected finding $2" "$out/$1.1.txt"; }
policy() { printf '[module."%s"]\nfuzz = true\n' "$2" > "$1"; }

begin "corpus and budget: stats.json is exact for a pass, a budget crash and a replay crash"
build_out bb_stats "$P/bug_budget:fz[stats]"
grep -Eq '^\{"corpus_files":0,"phase":"budget","replayed":0,"reproducer_sha256":"[0-9a-f]{64}","runs_done":[0-9]+\}$' "$bb_stats" || fail "$CUR: bug_budget stats: $(cat "$bb_stats")"
build_out br_stats "$P/bug_replay:fz[stats]"
grep -Eq '^\{"corpus_files":2,"phase":"replay","replayed":[01],"reproducer_sha256":"[0-9a-f]{64}","runs_done":0\}$' "$br_stats" || fail "$CUR: bug_replay stats: $(cat "$br_stats")"
build_out fc_stats "$P/fixed_corpus:fz[stats]"
[ "$(cat "$fc_stats")" = '{"corpus_files":2,"phase":"budget","replayed":2,"reproducer_sha256":"","runs_done":200000}' ] || fail "$CUR: fixed_corpus stats: $(cat "$fc_stats")"
build_out fx_stats "$P/fixed:fz[stats]"
[ "$(cat "$fx_stats")" = '{"corpus_files":0,"phase":"budget","replayed":0,"reproducer_sha256":"","runs_done":200000}' ] || fail "$CUR: fixed stats: $(cat "$fx_stats")"
build_out br_report "$P/bug_replay:fz[report]"
grep -q "^replay: .* of 2 corpus files" "$br_report" && grep -q "heap-buffer-overflow" "$br_report" || fail "$CUR: bug_replay report: $(head -5 "$br_report")"
sha_regress="$(sha256sum "$scratch/bug_replay/corpus/regress-oob" | cut -d' ' -f1)"
grep -q "\"reproducer_sha256\":\"$sha_regress\"" "$br_stats" || fail "$CUR: the replay reproducer is not the corpus file"

begin "judge: the same bug found by the budget is fuzz-crash in phase budget"
collect "$out/r_budget" bug_budget
facts "$out/f_budget" "$P/lib:parse_facts" "$P/bug_budget:fz_facts"
policy "$out/p_bug.toml" "$M_BUG"
judge budget 1 "$out/f_budget" "$out/r_budget" "$out/p_bug.toml"
expect_rule budget fuzz-crash
grep -q '"phase":"budget"' "$out/budget.1.json" && grep -q '"top_frame":"parse_run selftest/scratch_fuzz/lib/parse.c:15:' "$out/budget.1.json" || fail "$CUR: crash finding lacks phase/top frame" "$out/budget.1.txt"

begin "judge: the same bug with its reproducer in the corpus is fuzz-crash in phase replay"
collect "$out/r_replay" bug_replay
facts "$out/f_replay" "$P/lib:parse_facts" "$P/bug_replay:fz_facts"
judge replay 1 "$out/f_replay" "$out/r_replay" "$out/p_bug.toml"
expect_rule replay fuzz-crash
grep -q '"phase":"replay"' "$out/replay.1.json" && grep -q "\"reproducer_sha256\":\"$sha_regress\"" "$out/replay.1.json" || fail "$CUR: replay finding lacks phase/sha" "$out/replay.1.txt"

begin "judge: the fixed parser passes (info for the empty corpus); with its old reproducer in the corpus it passes too"
collect "$out/r_fixed" fixed
facts "$out/f_fixed" "$P/libfixed:parse_facts" "$P/fixed:fz_facts"
policy "$out/p_fix.toml" "$M_FIX"
judge fixed 0 "$out/f_fixed" "$out/r_fixed" "$out/p_fix.toml"
expect_rule fixed fuzz-empty-corpus
collect "$out/r_fc" fixed_corpus
facts "$out/f_fc" "$P/libfixed:parse_facts" "$P/fixed_corpus:fz_facts"
printf '{"%s/fixed_corpus:fz":["%s"]}\n' "$P" "$sha_regress" > "$out/reg_ok.json"
judge fc 0 "$out/f_fc" "$out/r_fc" "$out/p_fix.toml" "$out/reg_ok.json"
expect_no_rule fc fuzz-empty-corpus

begin "judge: a regression list naming an input that is not in the replayed corpus is fuzz-regression-missing"
absent="$(printf 'absent' | sha256sum | cut -d' ' -f1)"
printf '{"%s/fixed_corpus:fz":["%s","%s"]}\n' "$P" "$sha_regress" "$absent" > "$out/reg_bad.json"
judge regress 1 "$out/f_fc" "$out/r_fc" "$out/p_fix.toml" "$out/reg_bad.json"
expect_rule regress fuzz-regression-missing
grep -q "\"sha256\":\"$absent\"" "$out/regress.1.json" && ! grep -q "\"sha256\":\"$sha_regress\"" "$out/regress.1.json" || fail "$CUR: wrong input named" "$out/regress.1.txt"

begin "judge: a harness that returns at once is fuzz-harness-no-call"
collect "$out/r_nocall" nocall
facts "$out/f_nocall" "$P/libfixed:parse_facts" "$P/nocall:fz_facts"
judge nocall 1 "$out/f_nocall" "$out/r_nocall" "$out/p_fix.toml"
expect_rule nocall fuzz-harness-no-call
expect_no_rule nocall fuzz-crash

begin "judge: a module with fuzz = true and no target is fuzz-missing; a required target without results is fuzz-not-run"
facts "$out/f_lone" "$P/lone:other_facts"
policy "$out/p_lone.toml" "$M_LONE"
mkdir -p "$out/r_none"; printf '{}\n' > "$out/r_none/index.json"
judge missing 1 "$out/f_lone" "$out/r_none" "$out/p_lone.toml"
expect_rule missing fuzz-missing
judge notrun 1 "$out/f_fixed" "$out/r_none" "$out/p_fix.toml"
expect_rule notrun fuzz-not-run

begin "two cold runs (fresh action keys) give byte-identical stats, verdicts and reports, for the budget and replay crashes"
for k in bug_budget bug_replay fixed_corpus; do
  for sub in stats report crash replayed; do fuzz_out cp_path "$k" "$sub"; cp -f "$cp_path" "$out/cold1.$k.$sub"; done
  printf 'const char fuzz_scratch_nonce[] = "%s";\n' "$(date +%s%N)-$$-$k" >> "$scratch/$k/fz_fuzz.c"
done
for k in bug_budget bug_replay fixed_corpus; do
  for sub in stats report crash replayed; do
    fuzz_out cp_path "$k" "$sub"
    cmp -s "$out/cold1.$k.$sub" "$cp_path" || fail "$CUR: $k[$sub] differs between cold runs: $(diff "$out/cold1.$k.$sub" "$cp_path" | head -5)"
  done
done
echo "  cold/cold: stats, reports, reproducers and replayed lists byte-identical"

echo "elapsed ${SECONDS}s"
echo "fuzz selftest: all $step steps passed"
