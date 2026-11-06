#!/usr/bin/env bash
# Self-test of the ctest framework and the <name>_results artifact (T003).
# Builds throwaway test packages whose tests cheat or misbehave in every way we know, builds
# their `<name>_results` on RE, and asserts the JSON Lines are exactly right. Needs only bash,
# python3 (stdlib) and tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
PLAT=toolchains//:linux_
scratch="selftest/scratch_ctest"
pkg="//selftest/scratch_ctest"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
must_pass() { local log="$out/$step.log"; run "$log" "$@" || fail "$CUR: buck2 $* failed" "$log"; }
# out_of <log> <target-fragment>: path printed by --show-output for that target
out_of() { awk -v t="$2" 'index($1, t) && /buck-out/ {print $2}' "$1" | tail -1; }
# build_out <var> <platform-mode> <target>: builds, sets $var to the output file
build_out() {
  local var="$1" mode="$2" target="$3" log="$out/$step.log" p
  run "$log" build --target-platforms "${PLAT}$mode" "$target" --show-output || fail "$CUR: build $target ($mode) failed" "$log"
  p="$(out_of "$log" "${target##*:}")"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}

# --------------------------------------------------------------------------------------
# Test sources. Each package is one c_test with one suite.
# --------------------------------------------------------------------------------------
mkdir -p "$scratch"/{basic,checks,order,badname,dup,san}
for d in basic checks order badname dup san; do
  printf 'load("@gate//rules:c.bzl", "c_test")\nc_test(name = "t", srcs = ["t.c"])\n' > "$scratch/$d/BUCK"
done

cat > "$scratch/basic/t.c" <<'C'
#include <stdlib.h>
#include <unistd.h>
#include "ctest.h"

static int *volatile g_null;
static volatile unsigned long g_spin;

static void t_pass_two(ctest_t *t) { CHECK(t, 1 + 1 == 2); CHECK_EQ_I64(t, 3, 3); }
static void t_fail_check(ctest_t *t) { int x = 4; CHECK(t, x == 4); CHECK(t, x == 5); }
static void t_zero_checks(ctest_t *t) { (void)t; }
static void t_segfault(ctest_t *t) { CHECK(t, 1); *g_null = 1; }
static void t_abort(ctest_t *t) { CHECK(t, 1); abort(); }
static void t_exit_zero_early(ctest_t *t) { (void)t; exit(0); }
static void t_raw_exit_zero_early(ctest_t *t) { (void)t; _exit(0); }
static void t_check_then_exit_zero(ctest_t *t) { CHECK(t, 1); exit(0); }
static void t_check_then_raw_exit_zero(ctest_t *t) { CHECK(t, 1); _exit(0); }
static void t_exit_one(ctest_t *t) { CHECK(t, 1); exit(1); }
static void t_hang(ctest_t *t) { CHECK(t, 1); for (;;) { g_spin = g_spin + 1; } }
static void t_hang_no_checks(ctest_t *t) { (void)t; for (;;) { g_spin = g_spin + 1; } }

CTEST_SUITE("basic",
    { "pass_two", t_pass_two },
    { "fail_check", t_fail_check },
    { "zero_checks", t_zero_checks },
    { "segfault", t_segfault },
    { "abort", t_abort },
    { "exit_zero_early", t_exit_zero_early },
    { "raw_exit_zero_early", t_raw_exit_zero_early },
    { "check_then_exit_zero", t_check_then_exit_zero },
    { "check_then_raw_exit_zero", t_check_then_raw_exit_zero },
    { "exit_one", t_exit_one },
    { "hang", t_hang },
    { "hang_no_checks", t_hang_no_checks })
C

cat > "$scratch/checks/t.c" <<'C'
#include "ctest.h"

static void t_i64_ok(ctest_t *t) { CHECK_EQ_I64(t, -5, -5); }
static void t_i64_bad(ctest_t *t) { CHECK_EQ_I64(t, -5, 7); }
static void t_u64_ok(ctest_t *t) { CHECK_EQ_U64(t, 18446744073709551615ULL, 18446744073709551615ULL); }
static void t_u64_bad(ctest_t *t) { CHECK_EQ_U64(t, 1U, 2U); }
static void t_str_ok(ctest_t *t) { CHECK_EQ_STR(t, "abc", "abc"); CHECK_EQ_STR(t, NULL, NULL); }
static void t_str_bad(ctest_t *t) { CHECK_EQ_STR(t, "abc", "abd"); }
static void t_str_null(ctest_t *t) { CHECK_EQ_STR(t, "abc", NULL); }
static void t_str_escapes(ctest_t *t) { CHECK_EQ_STR(t, "a\"b\\c\nd\t\x01\xff", "x"); }
static void t_mem_ok(ctest_t *t) { CHECK_EQ_MEM(t, "ab\0c", 4, "ab\0c", 4); CHECK_EQ_MEM(t, NULL, 0, NULL, 0); }
static void t_mem_bad(ctest_t *t) { CHECK_EQ_MEM(t, "ab\0c", 4, "ab\0d", 4); }
static void t_mem_len(ctest_t *t) { CHECK_EQ_MEM(t, "abc", 3, "abc", 2); }
static void t_continues(ctest_t *t) { CHECK(t, 0); CHECK(t, 1); CHECK_EQ_I64(t, 1, 2); }

CTEST_SUITE("checks",
    { "i64_ok", t_i64_ok }, { "i64_bad", t_i64_bad },
    { "u64_ok", t_u64_ok }, { "u64_bad", t_u64_bad },
    { "str_ok", t_str_ok }, { "str_bad", t_str_bad }, { "str_null", t_str_null },
    { "str_escapes", t_str_escapes },
    { "mem_ok", t_mem_ok }, { "mem_bad", t_mem_bad }, { "mem_len", t_mem_len },
    { "continues", t_continues })
C

cat > "$scratch/order/t.c" <<'C'
#include <stdio.h>
#include "ctest.h"

/* Tests are isolated in forked children; the only way to depend on order is the file system. */
static void t_a_creates(ctest_t *t) {
    FILE *f = fopen("order_marker", "w");
    CHECK(t, f != NULL);
    if (f != NULL) { CHECK(t, fclose(f) == 0); }
}
static void t_b_needs_a(ctest_t *t) {
    FILE *f = fopen("order_marker", "r");
    CHECK(t, f != NULL);
    if (f != NULL) { CHECK(t, fclose(f) == 0); }
}
static void t_c_other(ctest_t *t) { CHECK(t, 1); }
static void t_d_other(ctest_t *t) { CHECK(t, 1); }

CTEST_SUITE("order",
    { "a_creates", t_a_creates }, { "b_needs_a", t_b_needs_a },
    { "c_other", t_c_other }, { "d_other", t_d_other })
C

cat > "$scratch/badname/t.c" <<'C'
#include "ctest.h"
static void t_x(ctest_t *t) { CHECK(t, 1); }
CTEST_SUITE("badname", { "ok_name", t_x }, { "Bad-Name", t_x })
C

cat > "$scratch/dup/t.c" <<'C'
#include "ctest.h"
static void t_x(ctest_t *t) { CHECK(t, 1); }
CTEST_SUITE("dup", { "same", t_x }, { "same", t_x })
C

cat > "$scratch/san/t.c" <<'C'
#include <stdlib.h>
#include <string.h>
#include "ctest.h"

static volatile int g_idx = 4;
static void *volatile g_sink;
static volatile int g_big = 2147483647;

static void t_fine(ctest_t *t) { CHECK(t, 1); }
static void t_heap_overflow(ctest_t *t) {
    char *p = malloc(4);
    CHECK(t, p != NULL);
    if (p != NULL) { p[g_idx] = 1; free(p); }
}
static void t_leak(ctest_t *t) { g_sink = malloc(16); CHECK(t, g_sink != NULL); g_sink = NULL; }
static void t_ub_overflow(ctest_t *t) { int v = g_big + 1; CHECK(t, v != 0); }

CTEST_SUITE("san",
    { "fine", t_fine }, { "heap_overflow", t_heap_overflow },
    { "leak", t_leak }, { "ub_overflow", t_ub_overflow })
C

# --------------------------------------------------------------------------------------
# Expectations, checked by one Python program. Each case: id -> (status, asserts, reason regex)
# --------------------------------------------------------------------------------------
cat > "$out/check.py" <<'PY'
import json, re, sys

EXPECT = {
  "basic": {
    "pass_two": ("pass", 2, r""),
    "fail_check": ("fail", 2, r"1 of 2 checks failed; first: .*t\.c:\d+: CHECK\(x == 5\)"),
    "zero_checks": ("fail", 0, r"no checks executed"),
    "segfault": ("fail", 0, r"killed by signal 11"),
    "abort": ("fail", 0, r"killed by signal 6"),
    "exit_zero_early": ("fail", 0, r"exited without reporting"),
    "raw_exit_zero_early": ("fail", 0, r"exited without reporting"),
    "check_then_exit_zero": ("fail", 0, r"exited without reporting"),
    "check_then_raw_exit_zero": ("fail", 0, r"exited without reporting"),
    "exit_one": ("fail", 0, r"exited with status 1 before reporting"),
    "hang": ("fail", 0, r"timeout after 10 s"),
    "hang_no_checks": ("fail", 0, r"timeout after 10 s"),
  },
  "checks": {
    "i64_ok": ("pass", 1, r""),
    "i64_bad": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_I64\(-5, 7\): -5 != 7"),
    "u64_ok": ("pass", 1, r""),
    "u64_bad": ("fail", 1, r"CHECK_EQ_U64\(1U, 2U\): 1 != 2"),
    "str_ok": ("pass", 2, r""),
    "str_bad": ("fail", 1, r"CHECK_EQ_STR\(\"abc\", \"abd\"\): \"abc\" != \"abd\""),
    "str_null": ("fail", 1, r"CHECK_EQ_STR\(\"abc\", NULL\): \"abc\" != \(null\)"),
    "str_escapes": ("fail", 1, r"CHECK_EQ_STR"),
    "mem_ok": ("pass", 2, r""),
    "mem_bad": ("fail", 1, r"CHECK_EQ_MEM\(.*\): first difference at offset 3"),
    "mem_len": ("fail", 1, r"CHECK_EQ_MEM\(.*\): lengths 3 != 2"),
    "continues": ("fail", 3, r"2 of 3 checks failed; first: .*t\.c:\d+: CHECK\(0\)"),
  },
  "order": None,   # checked separately
  "san": {
    "fine": ("pass", 1, r""),
    "heap_overflow": ("fail", 0, r"exited with status \d+ before reporting|killed by signal"),
    "leak": ("fail", 1, r"exited with status \d+ after reporting"),
    "ub_overflow": ("fail", 0, r"exited with status \d+ before reporting|killed by signal"),
  },
}

def load(path):
    """Parse a results file strictly: exact key order, exact summary, agreement."""
    lines = open(path, "rb").read().decode("utf-8").split("\n")
    assert lines[-1] == "", "file must end with a newline"
    lines = lines[:-1]
    rows = []
    for ln in lines[:-1]:
        o = json.loads(ln, object_pairs_hook=lambda p: p)
        assert [k for k, _ in o] == ["id", "status", "asserts", "reason"], ln
        d = dict(o)
        assert d["status"] in ("pass", "fail"), ln
        assert isinstance(d["asserts"], int) and d["asserts"] >= 0, ln
        assert isinstance(d["reason"], str), ln
        assert (d["status"] == "pass") == (d["reason"] == ""), "pass iff empty reason: " + ln
        rows.append(d)
    summ = json.loads(lines[-1], object_pairs_hook=lambda p: p)
    assert [k for k, _ in summ] == ["summary"], lines[-1]
    assert [k for k, _ in summ[0][1]] == ["total", "passed"], lines[-1]
    s = dict(summ[0][1])
    assert s["total"] == len(rows), (s, len(rows))
    assert s["passed"] == sum(r["status"] == "pass" for r in rows), (s, rows)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids"
    return rows, lines

def check_suite(suite, path):
    rows, lines = load(path)
    exp = EXPECT[suite]
    got = {r["id"].split("/", 1)[1]: r for r in rows}
    assert all(r["id"].startswith(suite + "/") for r in rows)
    assert set(got) == set(exp), (sorted(set(got) ^ set(exp)))
    for name, (status, asserts, rx) in exp.items():
        r = got[name]
        assert r["status"] == status, (name, r)
        assert r["asserts"] == asserts, (name, r)
        assert re.fullmatch(rx, r["reason"]), (name, r["reason"], rx)
    print("  %s: %d cases exactly as expected" % (suite, len(exp)))
    return lines

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "suite":
        check_suite(sys.argv[2], sys.argv[3])
    elif cmd == "same":
        a, b = open(sys.argv[2], "rb").read(), open(sys.argv[3], "rb").read()
        assert a == b, "files differ: %s %s" % (sys.argv[2], sys.argv[3])
    elif cmd == "show":
        sys.stdout.write(open(sys.argv[2]).read())
    elif cmd == "orders":
        # args: files for seeds 1..n (order package). Row order differs; b_needs_a result varies.
        seqs, outcomes = set(), set()
        for p in sys.argv[2:]:
            rows, _ = load(p)
            names = [r["id"] for r in rows]
            seqs.add(tuple(names))
            pos = {n: i for i, n in enumerate(names)}
            b = [r for r in rows if r["id"] == "order/b_needs_a"][0]
            assert (b["status"] == "pass") == (pos["order/a_creates"] < pos["order/b_needs_a"]), (names, b)
            outcomes.add(b["status"])
        assert len(seqs) > 1, "seeds did not change the order"
        assert outcomes == {"pass", "fail"}, "order dependence not visible: %s" % outcomes
        print("  %d seeds -> %d distinct orders; b_needs_a both passed and failed" % (len(sys.argv) - 2, len(seqs)))
PY
chk() { python3 -I "$out/check.py" "$@"; }

# --------------------------------------------------------------------------------------
begin "release: every cheating / failing case in 'basic' and 'checks' is reported exactly (results built on RE)"
build_out basic_res release "$pkg/basic:t_results"
build_out checks_res release "$pkg/checks:t_results"
chk suite basic "$basic_res" || fail "$CUR"
chk suite checks "$checks_res" || fail "$CUR"

begin "san: heap overflow, leak and UB abort are fails; the clean test passes (results built on RE)"
build_out san_res san "$pkg/san:t_results"
chk suite san "$san_res" || fail "$CUR"

begin "the order package: seed 1 on RE equals seed 1 locally, and order dependence shows up under other seeds"
build_out order_res release "$pkg/order:t_results"
run "$out/bin.log" build --target-platforms ${PLAT}release "$pkg/order:t" --show-output || fail "$CUR" "$out/bin.log"
order_bin="$(out_of "$out/bin.log" t)"
[ -x "$order_bin" ] || fail "$CUR: no binary at '$order_bin'"
order_bin="$(cd "$(dirname "$order_bin")" && pwd)/$(basename "$order_bin")"
runlocal() { # <seed> <outfile>: fresh empty cwd
  local d; d="$(mktemp -d)"
  ( cd "$d" && "$order_bin" --seed "$1" --out "$2" ); local rc=$?
  rm -rf "$d"; return $rc
}
files=()
for s in 1 2 3 4 5 6 7 8 9 10 11 12; do
  runlocal "$s" "$out/order.$s.jsonl"; rc=$?
  [ "$rc" = 0 ] || [ "$rc" = 1 ] || fail "$CUR: seed $s exit code $rc"
  files+=("$out/order.$s.jsonl")
done
chk orders "${files[@]}" || fail "$CUR"
chk same "$order_res" "$out/order.1.jsonl" || fail "$CUR: RE seed 1 differs from local seed 1"
runlocal 5 "$out/again.jsonl"; chk same "$out/order.5.jsonl" "$out/again.jsonl" || fail "$CUR: seed 5 not reproducible"

begin "exit codes: 0 when all pass, 1 on any failure, 2 on usage or framework errors"
build_out dummy release "$pkg/checks:t_results"
for want in "checks 1" "badname 2" "dup 2"; do
  set -- $want
  run "$out/bin.log" build --target-platforms ${PLAT}release "$pkg/$1:t" --show-output || fail "$CUR: $1 build" "$out/bin.log"
  b="$(out_of "$out/bin.log" t)"
  d="$(mktemp -d)"; ( cd "$d" && "$root/$b" --out "$out/$1.rc.jsonl" >/dev/null 2>&1 ); rc=$?; rm -rf "$d"
  [ "$rc" = "$2" ] || fail "$CUR: $1 exited $rc, wanted $2"
  if [ "$2" = 2 ] && [ -s "$out/$1.rc.jsonl" ]; then fail "$CUR: $1 wrote results despite a framework error"; fi
done
run "$out/bin.log" build --target-platforms ${PLAT}release "$pkg/basic:t" --show-output || fail "$CUR" "$out/bin.log"
b="$root/$(out_of "$out/bin.log" t)"
for args in "--bogus" "--seed" "--seed x" "--seed -1" "--out" "extra"; do
  "$b" $args >/dev/null 2>&1; rc=$?
  [ "$rc" = 2 ] || fail "$CUR: '$args' exited $rc, wanted 2"
done
hello_bin="$(run "$out/h.log" build //examples/hello:hello_test --show-output && out_of "$out/h.log" hello_test)"
"$root/$hello_bin" >"$out/hello.out" 2>&1; rc=$?
[ "$rc" = 0 ] || fail "$CUR: hello_test (all pass) exited $rc"
grep -q '^{"summary":{"total":1,"passed":1}}$' "$out/hello.out" || fail "$CUR: no summary on stdout" "$out/hello.out"

begin "buck2 test on a ctest c_test still works (hello), and its results artifact exists"
must_pass test //examples/hello/...
build_out hello_res release //examples/hello:hello_test_results
grep -q '"id":"hello/' "$hello_res" || fail "$CUR: hello results lack ids: $(cat "$hello_res")"

begin "cov and fuzz modes: <name>_results is not buildable (incompatible); buck2 test //examples/hello works in cov"
must_pass test --target-platforms ${PLAT}cov //examples/hello/...

begin "cache: rebuilding unchanged results executes 0 actions"
must_pass build "$pkg/basic:t_results" "$pkg/checks:t_results" //examples/hello:hello_test_results
must_pass build "$pkg/basic:t_results" "$pkg/checks:t_results" //examples/hello:hello_test_results
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the second build"
echo "  second build: $n actions executed"

begin "cache: the results actions really ran on RE (fresh nonce source forces execution)"
printf 'const char ctest_scratch_nonce[] = "%s";\n' "$(date +%s%N)-$$" >> "$scratch/order/t.c"
must_pass build "$pkg/order:t_results"
"${B[@]}" log what-ran 2>/dev/null | strip_ansi > "$out/whatran.txt"
grep -q 'ctest_results' "$out/whatran.txt" || fail "$CUR: no ctest_results action ran" "$out/whatran.txt"
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' 'NF>=3 && $3 !~ /^re\(/ {bad=1} END{exit !bad}'; then
  fail "$CUR: an action did not run on RE" "$out/whatran.txt"
fi
grep 'ctest_results' "$out/whatran.txt" | head -3

echo "ALL CHECKS PASSED ($step)"
