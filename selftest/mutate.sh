#!/usr/bin/env bash
# Self-test of mutation testing (T006): `c_mutants` on RE, the mutant generator, and `rigor mutants`.
# Red cases come first: a known survivor must be reported as a survivor, and a generator that goes
# blind must fail the gate. Needs bash, python3 (stdlib), git, ssh-keygen, tools/buck2.
# MUTATE_COLD=1 stamps the sources with a fresh nonce so that nothing can come from the RE cache.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
scratch="selftest/scratch_mut"
pkg="//selftest/scratch_mut/m"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT
RIGOR=(gate/rigor)
RES="$out/res"
PY=(python3 -I -B)

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
# executed <log>: remote + local commands buck2 reports (cache hits are not counted)
executed() { awk '/Commands:/ { for (i = 1; i <= NF; i++) { if ($i == "remote:") r = $(i+1); if ($i == "local:") l = $(i+1) } gsub(/[^0-9]/, "", r); gsub(/[^0-9]/, "", l); print r + l; found = 1 } END { if (!found) print 0 }' "$1" | tail -1; }

mkdir -p "$scratch/m"
cd "$scratch/m"
cat > BUCK <<'EOF'
load("@gate//rules:c.bzl", "c_library", "c_mutants", "c_test")

c_library(name = "pinned", srcs = ["pinned.c"], headers = ["pinned.h"])
c_test(name = "pinned_test", srcs = ["pinned_test.c"], deps = [":pinned"])
c_mutants(name = "pinned_mutants", module = ":pinned", tests = [":pinned_test"])

c_library(name = "weak", srcs = ["weak.c"], headers = ["weak.h"])
c_test(name = "weak_test", srcs = ["weak_test.c"], deps = [":weak"])
c_mutants(name = "weak_mutants", module = ":weak", tests = [":weak_test"])

c_library(name = "equiv", srcs = ["equiv.c"], headers = ["equiv.h"])
c_test(name = "equiv_test", srcs = ["equiv_test.c"], deps = [":equiv"])
c_mutants(name = "equiv_mutants", module = ":equiv", tests = [":equiv_test"])

c_library(name = "multi", srcs = ["multi_a.c", "sub/multi_b.c"], headers = ["multi.h", "sub/multi_b.h"])
c_test(name = "multi_test", srcs = ["multi_test.c"], deps = [":multi"])
c_mutants(name = "multi_mutants", module = ":multi", tests = [":multi_test"])
EOF
cat > pinned.h <<'EOF'
#ifndef PINNED_H
#define PINNED_H
int in_range(int x, int lo, int hi);
int count_below(const int *a, int n, int limit);
int sign(int x);
int times_one(int x);
#endif
EOF
cat > pinned.c <<'EOF'
#include "pinned.h"

#define IS_NEG(x) ((x) < 0)

int in_range(int x, int lo, int hi)
{
    return x >= lo && x <= hi;
}

int count_below(const int *a, int n, int limit)
{
    int c = 0;
    for (int i = 0; i < n; i++) {
        if (a[i] < limit) {
            c++;
        }
    }
    return c;
}

int sign(int x)
{
    if (IS_NEG(x))
        return -1;
    return 1;
}

int times_one(int x)
{
    return x * 1;
}
EOF
cat > pinned_test.c <<'EOF'
#include "ctest/ctest.h"
#include "pinned.h"

static void t_in_range(ctest_t *t)
{
    CHECK_EQ_I64(t, in_range(5, 0, 10), 1);
    CHECK_EQ_I64(t, in_range(0, 0, 10), 1);
    CHECK_EQ_I64(t, in_range(10, 0, 10), 1);
    CHECK_EQ_I64(t, in_range(-1, 0, 10), 0);
    CHECK_EQ_I64(t, in_range(11, 0, 10), 0);
    CHECK_EQ_I64(t, in_range(-5, -9, -2), 1);
}

static void t_count(ctest_t *t)
{
    /* a[4] is a sentinel below every limit used: reading it would change the count. */
    const int a[5] = { 1, 5, 3, 9, -100 };
    CHECK_EQ_I64(t, count_below(a, 4, 5), 2);
    CHECK_EQ_I64(t, count_below(a, 4, 6), 3);
    CHECK_EQ_I64(t, count_below(a, 4, 1), 0);
    CHECK_EQ_I64(t, count_below(a, 0, 100), 0);
    CHECK_EQ_I64(t, count_below(a, 1, 2), 1);
    CHECK_EQ_I64(t, count_below(a + 1, 3, 4), 1);
}

static void t_sign(ctest_t *t)
{
    CHECK_EQ_I64(t, sign(-5), -1);
    CHECK_EQ_I64(t, sign(0), 1);
    CHECK_EQ_I64(t, sign(7), 1);
}

static void t_times_one(ctest_t *t)
{
    CHECK_EQ_I64(t, times_one(5), 5);
    CHECK_EQ_I64(t, times_one(-3), -3);
}

CTEST_SUITE("pinned", { "in_range", t_in_range }, { "count", t_count }, { "sign", t_sign },
            { "times_one", t_times_one })
EOF
cat > weak.h <<'EOF'
#ifndef WEAK_H
#define WEAK_H
int *find(int *a, int n, int v);
void store(int *slot, int v);
int double_it(int x);
#endif
EOF
cat > weak.c <<'EOF'
#include "weak.h"

int *find(int *a, int n, int v)
{
    for (int i = 0; i < n; i++) {
        if (a[i] == v) {
            return &a[i];
        }
    }
    return 0;
}

void store(int *slot, int v)
{
    *slot = v;
}

int double_it(int x)
{
    return x + x;
}
EOF
cat > weak_test.c <<'EOF'
#include "ctest/ctest.h"
#include "weak.h"

static void t_find(ctest_t *t)
{
    int a[3] = { 4, 5, 6 };
    CHECK(t, find(a, 3, 5) != 0);
}

static void t_store(ctest_t *t)
{
    int x = 0;
    int *volatile p = &x;
    store(p, 5);
    CHECK(t, p != 0);
}

static void t_double(ctest_t *t)
{
    CHECK_EQ_I64(t, double_it(0), 0);
}

CTEST_SUITE("weak", { "find", t_find }, { "store", t_store }, { "double", t_double })
EOF
cat > equiv.h <<'EOF'
#ifndef EQUIV_H
#define EQUIV_H
int twice_pos(int n);
#endif
EOF
cat > equiv.c <<'EOF'
#include "equiv.h"

int twice_pos(int n)
{
    if (n <= 0) {
        return 0;
    }
    return n * 2;
}
EOF
cat > equiv_test.c <<'EOF'
#include "ctest/ctest.h"
#include "equiv.h"

static void t_twice(ctest_t *t)
{
    CHECK_EQ_I64(t, twice_pos(-3), 0);
    CHECK_EQ_I64(t, twice_pos(0), 0);
    CHECK_EQ_I64(t, twice_pos(1), 2);
    CHECK_EQ_I64(t, twice_pos(4), 8);
}

CTEST_SUITE("equiv", { "twice", t_twice })
EOF
mkdir -p sub
cat > multi.h <<'EOF'
#ifndef MULTI_H
#define MULTI_H
int add_wrap(int a, int b);
#endif
EOF
cat > multi_a.c <<'EOF'
#include "multi.h"

int add_wrap(int a, int b)
{
    return (a + b) % 7;
}
EOF
cat > sub/multi_b.h <<'EOF'
#ifndef MULTI_B_H
#define MULTI_B_H
int is_zero(int x);
int hi_bit(unsigned x);
#endif
EOF
cat > sub/multi_b.c <<'EOF'
#include "multi_b.h"

int is_zero(int x)
{
    return x == 0;
}

int hi_bit(unsigned x)
{
    return (int)((x >> 31) & 1u);
}
EOF
cat > multi_test.c <<'EOF'
#include "ctest/ctest.h"
#include "multi.h"
#include "sub/multi_b.h"

static void t_add_wrap(ctest_t *t)
{
    CHECK_EQ_I64(t, add_wrap(3, 5), 1);
    CHECK_EQ_I64(t, add_wrap(1, 2), 3);
    CHECK_EQ_I64(t, add_wrap(0, 0), 0);
    CHECK_EQ_I64(t, add_wrap(6, 1), 0);
    CHECK_EQ_I64(t, add_wrap(10, 20), 2);
}

static void t_is_zero(ctest_t *t)
{
    CHECK_EQ_I64(t, is_zero(0), 1);
    CHECK_EQ_I64(t, is_zero(1), 0);
    CHECK_EQ_I64(t, is_zero(-4), 0);
}

static void t_hi_bit(ctest_t *t)
{
    CHECK_EQ_I64(t, hi_bit(0x80000000u), 1);
    CHECK_EQ_I64(t, hi_bit(1u), 0);
    CHECK_EQ_I64(t, hi_bit(0u), 0);
    CHECK_EQ_I64(t, hi_bit(0xFFFFFFFFu), 1);
}

CTEST_SUITE("multi", { "add_wrap", t_add_wrap }, { "is_zero", t_is_zero }, { "hi_bit", t_hi_bit })
EOF
cd "$root"
if [ -n "${MUTATE_COLD:-}" ]; then
  nonce="$(date +%s%N)-$$"
  for f in "$scratch"/m/*.c "$scratch"/m/sub/*.c; do sed -i "1i /* nonce $nonce */" "$f"; done
fi

# build_all <log>: build the three modules and refresh $RES/<name>.json
build_all() {
  local log="$1" name
  run "$log" build "$pkg:pinned_mutants" "$pkg:weak_mutants" "$pkg:equiv_mutants" "$pkg:multi_mutants" --show-full-output || return 1
  mkdir -p "$RES"
  for name in pinned weak equiv multi; do
    p="$(awk -v t="$pkg:${name}_mutants" '$1 == "root" t || index($1, t) {print $2}' "$log" | tail -1)"
    [ -f "$p" ] || { echo "no report for $name: '$p'" >&2; return 1; }
    cp "$p" "$RES/$name.json"
  done
}
# gate <results-dir> [extra args]: runs `rigor mutants`; sets GATE_CODE and $out/result.json
gate() {
  local dir="$1"; shift
  "${RIGOR[@]}" mutants --results "$dir" --policy "$out/policy.toml" --out "$out/result.json" "$@" > "$out/gate.log" 2>&1
  GATE_CODE=$?
}
# json <expr>: evaluate a Python expression over `r` (the last gate result)
json() { "${PY[@]}" -c 'import json,sys; r=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$out/result.json" "$1"; }
rules() { json 'sorted({f["rule"] for f in r["findings"]})'; }

# --------------------------------------------------------------------------------------
begin "build the throwaway module's mutants on RE (cold if MUTATE_COLD=1)"
t0=$SECONDS
build_all "$out/build1.log" || fail "$CUR: buck2 build failed" "$out/build1.log"
echo "    built in $((SECONDS - t0)) s, executed $(executed "$out/build1.log") actions"

begin "RED: the known survivors of the weak tests are reported as survivors, precisely"
mkdir -p "$out/only_weak"; cp "$RES/weak.json" "$out/only_weak/"
printf '[module."%s:weak_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_weak"
[ "$GATE_CODE" = 1 ] || fail "$CUR: expected exit 1, got $GATE_CODE" "$out/gate.log"
got="$(json '"\n".join(sorted("%s|%s|%s" % (f["function"], f["operator"], f["replacement"]) for f in r["findings"] if f["rule"] == "survived-mutant"))')"
want='double_it|function-body|{ (void)x; return 0; }
find|condition|!(a[i] == v)
find|increment|--
find|integer-literal|1
find|relational|<=
find|return-value|((void)(0), (int *)1)
store|function-body|{ (void)slot; (void)v; }'
[ "$got" = "$want" ] || fail "$CUR: survivors differ from the expected list" <(printf 'got:\n%s\nwant:\n%s\n' "$got" "$want")
[ "$(json '[f["rule"] for f in r["findings"]].count("survived-mutant")')" = 7 ] || fail "$CUR: not exactly 7 findings"
echo "    7 survivors, exit 1, as expected"
echo "    $(json 'r["metadata"]["modules"].popitem()[1]["verdicts"]')"

begin "RED: a generator gone blind (no mutants although there are functions) fails the gate"
mkdir -p "$out/blind"
"${PY[@]}" - "$RES/pinned.json" "$out/blind/pinned.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["sources"][0]["functions"], "the module has functions"
d["mutants"] = []
json.dump(d, open(sys.argv[2], "w"))
PY
printf '[module."%s:pinned_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/blind"
[ "$GATE_CODE" = 1 ] || fail "$CUR: a blind generator passed (exit $GATE_CODE)" "$out/gate.log"
[ "$(rules)" = "['no-mutants']" ] || fail "$CUR: unexpected rules $(rules)" "$out/gate.log"
echo "    exit 1, rule no-mutants"

begin "GREEN: the strongly pinned module has no survivor, has equivalents (TCE), and skipped the macro"
mkdir -p "$out/only_pinned"; cp "$RES/pinned.json" "$out/only_pinned/"
gate "$out/only_pinned"
[ "$GATE_CODE" = 0 ] || fail "$CUR: expected exit 0, got $GATE_CODE" "$out/gate.log"
v="$(json 'r["metadata"]["modules"].popitem()[1]["verdicts"]')"
echo "    $v"
"${PY[@]}" - "$RES/pinned.json" "$scratch/m/pinned.c" <<'PY' || fail "$CUR: bad pinned report"
import json, sys
d = json.load(open(sys.argv[1]))
src = open(sys.argv[2]).read().split("\n")
macro_use = next(i + 1 for i, l in enumerate(src) if "if (IS_NEG(x))" in l)
macro_def = next(i + 1 for i, l in enumerate(src) if l.startswith("#define IS_NEG"))
bad = [m for m in d["mutants"] if m["line"] in (macro_use, macro_def)]
assert not bad, "mutants inside the macro expansion: %r" % bad
ops = {m["operator"] for m in d["mutants"]}
assert {"relational", "arithmetic", "logical", "condition", "integer-literal", "return-value",
        "increment", "function-body"} <= ops, ops
kinds = {}
for m in d["mutants"]:
    s = m["compile"]["status"]
    kinds[s] = kinds.get(s, 0) + 1
print("    compile statuses:", kinds, "- no mutant on the macro lines", macro_def, macro_use)
PY
"${PY[@]}" - "$out/result.json" <<'PY' || fail "$CUR: counts"
import json, sys
m = json.load(open(sys.argv[1]))["metadata"]["modules"].popitem()[1]
assert m["verdicts"]["survived"] == 0 and m["verdicts"]["equivalent"] >= 1 and m["verdicts"]["killed-assert"] >= 10, m
PY

begin "GREEN: a module of two sources in two directories (the right object is swapped on relink)"
mkdir -p "$out/only_multi"; cp "$RES/multi.json" "$out/only_multi/"
printf '[module."%s:multi_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_multi"
[ "$GATE_CODE" = 0 ] || fail "$CUR: expected exit 0, got $GATE_CODE" "$out/gate.log"
"${PY[@]}" - "$RES/multi.json" <<'PY' || fail "$CUR: bad multi report"
import json, sys
d = json.load(open(sys.argv[1]))
files = sorted({m["file"] for m in d["mutants"]})
assert files == ["selftest/scratch_mut/m/multi_a.c", "selftest/scratch_mut/m/sub/multi_b.c"], files
assert len(d["sources"]) == 2 and all(s["baseline"]["hash"] == s["original"]["hash"] for s in d["sources"])
live = {}
for m in d["mutants"]:
    if m["runs"]:
        live[m["file"]] = live.get(m["file"], 0) + 1
assert len(live) == 2, live
print("    mutants per file with a run:", live)
PY
echo "    $(json 'r["metadata"]["modules"].popitem()[1]["verdicts"]')"

begin "RED: tampered reports fail closed (a live mutant without a run, a red baseline, a harness that is not the real build)"
printf '[module."%s:pinned_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
for case in missing-run baseline-red harness-mismatch; do
  rm -rf "$out/tamper"; mkdir -p "$out/tamper"
  "${PY[@]}" - "$RES/pinned.json" "$out/tamper/pinned.json" "$case" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
case = sys.argv[3]
if case == "missing-run":
    live = next(m for m in d["mutants"] if m["runs"])
    live["runs"] = {}
elif case == "baseline-red":
    run = d["baseline_runs"]["pinned_test"]
    run["results"] = run["results"].replace('"status":"pass"', '"status":"fail"', 1)
else:
    d["sources"][0]["original"]["hash"] = "0" * 64
json.dump(d, open(sys.argv[2], "w"))
PY
  gate "$out/tamper"
  [ "$GATE_CODE" = 1 ] || fail "$CUR: $case passed (exit $GATE_CODE)" "$out/gate.log"
  [ "$(rules)" = "['$case']" ] || fail "$CUR: $case gave $(rules)" "$out/gate.log"
  echo "    $case -> $(rules)"
done

begin "equivalent-mutant approvals: unsigned survivor fails, signed approval of its id passes, other ids do not"
mkdir -p "$out/only_equiv"; cp "$RES/equiv.json" "$out/only_equiv/"
printf '[module."%s:equiv_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_equiv"
[ "$GATE_CODE" = 1 ] || fail "$CUR: the equivalent survivor passed without approval" "$out/gate.log"
id="$(json '[f["id"] for f in r["findings"] if f["rule"] == "survived-mutant"][0]')"
old_line="$(json '[f["line"] for f in r["findings"] if f["rule"] == "survived-mutant"][0]')"
[ "$(json 'len([f for f in r["findings"] if f["rule"] == "survived-mutant"])')" = 1 ] || fail "$CUR: expected one survivor" "$out/gate.log"
ssh-keygen -q -t ed25519 -N "" -C owner -f "$out/key" >/dev/null || fail "$CUR: ssh-keygen"
printf 'owner namespaces="c-rigor-gate" %s\n' "$(cat "$out/key.pub")" > "$out/allowed_signers"
head_sha="$(git rev-parse HEAD)"
mkdir -p "$out/approvals" "$out/approvals_wrong"
"${RIGOR[@]}" approve --kind equivalent-mutant --scope "$id" --reason "n <= 0 and n < 0 agree at 0" \
  --repo-sha "$head_sha" --key "$out/key" --out "$out/approvals" >/dev/null || fail "$CUR: approve"
"${RIGOR[@]}" approve --kind equivalent-mutant --scope "0000000000000000" --reason "wrong id" \
  --repo-sha "$head_sha" --key "$out/key" --out "$out/approvals_wrong" >/dev/null || fail "$CUR: approve"
AP=(--allowed-signers "$out/allowed_signers" --repo . --head "$head_sha")
gate "$out/only_equiv" --approvals "$out/approvals" "${AP[@]}"
[ "$GATE_CODE" = 0 ] || fail "$CUR: a signed approval of the id did not pass (exit $GATE_CODE)" "$out/gate.log"
gate "$out/only_equiv" --approvals "$out/approvals_wrong" "${AP[@]}"
[ "$GATE_CODE" = 1 ] || fail "$CUR: an approval of another id passed" "$out/gate.log"
echo "    survivor $id: fails alone, passes with its signed approval, fails with another id's"

begin "mutant ids do not depend on line numbers (a comment line is inserted at the top of equiv.c)"
sed -i '1i /* an unrelated first line */' "$scratch/m/equiv.c"
run "$out/build_ids.log" build "$pkg:equiv_mutants" "$pkg:multi_mutants" --show-full-output || fail "$CUR: build" "$out/build_ids.log"
p="$(awk -v t="$pkg:equiv_mutants" 'index($1, t) {print $2}' "$out/build_ids.log" | tail -1)"
mkdir -p "$out/shifted"; cp "$p" "$out/shifted/equiv.json"
gate "$out/shifted"
[ "$(json '[f["id"] for f in r["findings"] if f["rule"] == "survived-mutant"][0]')" = "$id" ] || fail "$CUR: the survivor id changed"
[ "$(json '[f["line"] for f in r["findings"] if f["rule"] == "survived-mutant"][0]')" = $((old_line + 1)) ] || fail "$CUR: the line did not move"
echo "    same id $id, line moved $old_line -> $((old_line + 1))"
sed -i '1d' "$scratch/m/equiv.c"

begin "WARM: an unchanged tree executes no action"
build_all "$out/build2.log" || fail "$CUR: buck2 build failed" "$out/build2.log"
n="$(executed "$out/build2.log")"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on an unchanged tree" "$out/build2.log"
echo "    0 actions executed"

begin "a one-line test strengthening kills a survivor and re-runs only the weak module's mutants"
live="$("${PY[@]}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(sum(1 for m in d["mutants"] if m["runs"]))' "$RES/weak.json")"
# (the constant is random, so that the same edit made in an earlier run cannot come from the RE cache)
k=$((RANDOM + 1))
sed -i "s|    CHECK_EQ_I64(t, double_it(0), 0);|    CHECK_EQ_I64(t, double_it(0), 0);\n    CHECK_EQ_I64(t, double_it($k), $((2 * k)));|" "$scratch/m/weak_test.c"
grep -q "double_it($k)" "$scratch/m/weak_test.c" || fail "$CUR: the test edit did not apply"
build_all "$out/build3.log" || fail "$CUR: buck2 build failed" "$out/build3.log"
n="$(executed "$out/build3.log")"
echo "    executed $n actions; the weak module has $live live mutants (a cold build of all four modules is about 200 actions)"
# the live mutants of the weak module (one test each), plus the test's compile, the baseline run and the report
[ "$n" -ge "$live" ] && [ "$n" -le $((live + 6)) ] || fail "$CUR: expected about $live actions" "$out/build3.log"
printf '[module."%s:weak_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
mkdir -p "$out/weak_after"; cp "$RES/weak.json" "$out/weak_after/"
gate "$out/weak_after"
[ "$GATE_CODE" = 1 ] || fail "$CUR: expected survivors to remain" "$out/gate.log"
survivors="$(json '[f["function"] for f in r["findings"] if f["rule"] == "survived-mutant"].count("double_it")')"
[ "$survivors" = 0 ] || fail "$CUR: the double_it survivor is still there"
[ "$(json 'len([f for f in r["findings"] if f["rule"] == "survived-mutant"])')" = 6 ] || fail "$CUR: expected 6 survivors left"
echo "    double_it body survivor killed; 6 survivors left"

begin "WARM again"
build_all "$out/build4.log" || fail "$CUR: buck2 build failed" "$out/build4.log"
[ "$(executed "$out/build4.log")" = 0 ] || fail "$CUR: actions executed on an unchanged tree" "$out/build4.log"
echo "    0 actions executed"

echo "selftest/mutate.sh: all checks passed in $SECONDS s"
