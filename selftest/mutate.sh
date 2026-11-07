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

c_library(name = "macro", srcs = ["macro.c"], headers = ["macro.h"])
c_test(name = "macro_test", srcs = ["macro_test.c"], deps = [":macro"])
c_mutants(name = "macro_mutants", module = ":macro", tests = [":macro_test"])

c_library(name = "hidden", srcs = ["hidden.c"], headers = ["hidden.h"])
c_test(name = "hidden_test", srcs = ["hidden_test.c"], deps = [":hidden"])
c_mutants(name = "hidden_mutants", module = ":hidden", tests = [":hidden_test"])

c_library(name = "attr", srcs = ["attr.c"], headers = ["attr.h"])
c_test(name = "attr_test", srcs = ["attr_test.c"], deps = [":attr"])
c_mutants(name = "attr_mutants", module = ":attr", tests = [":attr_test"])

# T034: a test kit that is only headers (a library without sources has no archive), and a mutant that reads
# uninitialised memory (its failure reason carries garbage that must not reach the report)
c_library(name = "uninit", srcs = ["uninit.c"], headers = ["uninit.h"])
c_library(name = "uninit_kit", headers = ["uninit_kit.h"], deps = [":uninit"])
c_test(name = "uninit_test", srcs = ["uninit_test.c"], deps = [":uninit", ":uninit_kit"])
c_mutants(name = "uninit_mutants", module = ":uninit", tests = [":uninit_test"], deps = [":uninit_kit"])

# T064: the same modules with batches of 1 (the old shape: one mutant per action) and of 3; the reports must be
# byte-identical to the default build's (checked below)
load("@gate//rules:mutate.bzl", "c_mutants_rule")
[
    c_mutants_rule(
        name = "{}_b{}".format(m, n),
        module = ":" + m,
        module_src = ":{}_mutsrc".format(m),
        test_targets = [":{}_test".format(m)],
        deps = [":uninit_kit"] if m == "uninit" else [],
        link_flags = [],
        batch = n,
        target_compatible_with = ["toolchains//:release"],
    )
    for m in ["pinned", "weak", "multi", "uninit"]
    for n in [1, 3]
]

# a dependency that provides neither a library nor a header is an error
c_library(name = "bare_kit")
c_mutants(name = "bare_mutants", module = ":uninit", tests = [":uninit_test"], deps = [":bare_kit", ":uninit_kit"])
EOF
cat > macro.h <<'EOF'
#ifndef MACRO_H
#define MACRO_H
int macro_sign(int x);
int macro_over(int x);
#endif
EOF
cat > macro.c <<'EOF'
#include "macro.h"

#define IS_NEG(x) ((x) < 0)
#define LIMIT 10

int macro_sign(int x)
{
    if (IS_NEG(x))
        return -1;
    return 1;
}

int macro_over(int x)
{
    if (x > LIMIT)
        return 1;
    return 0;
}
EOF
cat > macro_test.c <<'EOF'
#include "ctest/ctest.h"
#include "macro.h"

static void t_sign(ctest_t *t)
{
    CHECK_EQ_I64(t, macro_sign(-5), -1);
    CHECK_EQ_I64(t, macro_sign(0), 1);
    CHECK_EQ_I64(t, macro_sign(7), 1);
}

static void t_over(ctest_t *t)
{
    CHECK_EQ_I64(t, macro_over(11), 1);
    CHECK_EQ_I64(t, macro_over(10), 0);
    CHECK_EQ_I64(t, macro_over(0), 0);
}

CTEST_SUITE("macro", { "sign", t_sign }, { "over", t_over })
EOF
cat > pinned.h <<'EOF'
#ifndef PINNED_H
#define PINNED_H
int in_range(int x, int lo, int hi);
int count_below(const int *a, int n, int limit);
int sign(int x);
int times_one(int x);
int unit(void);
#endif
EOF
cat > pinned.c <<'EOF'
#include "pinned.h"

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
    if (x < 0)
        return -1;
    return 1;
}

int times_one(int x)
{
    return x;
}

/* T051: `1 * 1` -> `1 / 1` is the same constant at -O2 and at -O0 (the front end folds it): an equivalent mutant
   that stays equivalent when it is compiled again without the optimiser. (`x * 1` -> `x / 1` is equal at -O2
   only: an `imul` against an `idiv` at -O0, so it is live.) */
int unit(void)
{
    return 1 * 1;
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
    CHECK_EQ_I64(t, unit(), 1);
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
int add_three(int x);
int not_zero(int x);
int record(int v);
#endif
EOF
cat > multi_a.c <<'EOF'
#include "multi.h"

int add_wrap(int a, int b)
{
    return (a + b) % 7;
}

int add_three(int x)
{
    x += 3;
    return x;
}

int not_zero(int x)
{
    return !x;
}

static void note(int *log, int v)
{
    *log = v;
}

int record(int v)
{
    int log; /* T051: not `= 0`: a dead store is an equivalent mutant that -O2 hides and -O0 shows */
    note(&log, v);
    return log;
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

static void t_more(ctest_t *t)
{
    CHECK_EQ_I64(t, add_three(4), 7);
    CHECK_EQ_I64(t, add_three(-3), 0);
    CHECK_EQ_I64(t, not_zero(0), 1);
    CHECK_EQ_I64(t, not_zero(9), 0);
    CHECK_EQ_I64(t, not_zero(-1), 0);
    CHECK_EQ_I64(t, record(5), 5);
    CHECK_EQ_I64(t, record(-2), -2);
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

CTEST_SUITE("multi", { "add_wrap", t_add_wrap }, { "is_zero", t_is_zero }, { "hi_bit", t_hi_bit }, { "more", t_more })
EOF
cat > hidden.h <<'EOF'
#ifndef HIDDEN_H
#define HIDDEN_H
static inline int inl(int x)
{
    return x + 1;
}
int plain(int x);
int twice(int x);
#endif
EOF
cat > hidden.c <<'EOF'
#include "hidden.h"

#define MAKE(n) int n(int x) { return x * 2; }

MAKE(twice)

int plain(int x)
{
    return inl(x) + 2;
}
EOF
cat > hidden_test.c <<'EOF'
#include "ctest/ctest.h"
#include "hidden.h"

static void t_hidden(ctest_t *t)
{
    CHECK_EQ_I64(t, plain(1), 4);
    CHECK_EQ_I64(t, plain(-5), -2);
    CHECK_EQ_I64(t, twice(3), 6);
}

CTEST_SUITE("hidden", { "hidden", t_hidden })
EOF
cat > attr.h <<'EOF'
#ifndef ATTR_H
#define ATTR_H
int attr_strong(int x);
int attr_weak(int x);
int attr_macro(int x);
#endif
EOF
# B19: clang lists the only attribute of these functions after their body
cat > uninit.h <<'EOF'
#ifndef UNINIT_H
#define UNINIT_H
int uninit_slot(int i);
#endif
EOF
cat > uninit.c <<'EOF'
#include "uninit.h"

int uninit_slot(int i)
{
    int buf[4];
    for (int k = 0; k < 4; k++) {
        buf[k] = k * 10;
    }
    return buf[i];
}
EOF
cat > uninit_kit.h <<'EOF'
#ifndef UNINIT_KIT_H
#define UNINIT_KIT_H
#include "ctest/ctest.h"
#include "uninit.h"
#define CHECK_SLOT(t, i, want) CHECK_EQ_I64((t), uninit_slot(i), (want))
#endif
EOF
cat > uninit_test.c <<'EOF'
#include "uninit_kit.h"

static void t_slots(ctest_t *t)
{
    CHECK_SLOT(t, 0, 0);
    CHECK_SLOT(t, 1, 10);
    CHECK_SLOT(t, 2, 20);
    CHECK_SLOT(t, 3, 30);
}

CTEST_SUITE("uninit", { "slots", t_slots })
EOF
cat > attr.c <<'EOF'
#include "attr.h"

__attribute__((noinline)) int attr_strong(int x)
{
    return x + 2;
}

__attribute__((cold, noinline)) int attr_weak(int x)
{
    return x + x;
}

/* ... and a macro that starts the function's range without being its body (B19, found on annas-c) */
#define NOINLINE __attribute__((noinline))
NOINLINE int attr_macro(int x)
{
    return x - 4;
}
EOF
cat > attr_test.c <<'EOF'
#include "ctest/ctest.h"
#include "attr.h"

static void t_strong(ctest_t *t)
{
    CHECK_EQ_I64(t, attr_strong(0), 2);
    CHECK_EQ_I64(t, attr_strong(5), 7);
}

static void t_weak(ctest_t *t)
{
    CHECK_EQ_I64(t, attr_weak(0), 0);
}

static void t_macro(ctest_t *t)
{
    CHECK_EQ_I64(t, attr_macro(10), 6);
    CHECK_EQ_I64(t, attr_macro(0), -4);
}

CTEST_SUITE("attr", { "strong", t_strong }, { "weak", t_weak }, { "macro", t_macro })
EOF
cd "$root"
if [ -n "${MUTATE_COLD:-}" ]; then
  nonce="$(date +%s%N)-$$"
  for f in "$scratch"/m/*.c "$scratch"/m/sub/*.c; do sed -i "1i /* nonce $nonce */" "$f"; done
fi

# build_all <log>: build the three modules and refresh $RES/<name>.json
build_all() {
  local log="$1" name
  run "$log" build "$pkg:pinned_mutants" "$pkg:weak_mutants" "$pkg:equiv_mutants" "$pkg:multi_mutants" "$pkg:macro_mutants" "$pkg:hidden_mutants" "$pkg:attr_mutants" "$pkg:uninit_mutants" --show-full-output || return 1
  mkdir -p "$RES"
  for name in pinned weak equiv multi macro hidden attr uninit; do
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
# MUTATE_SAVE_RES=<dir>: keep the raw reports, to compare two versions of the rules byte for byte (T064)
if [ -n "${MUTATE_SAVE_RES:-}" ]; then mkdir -p "$MUTATE_SAVE_RES"; cp "$RES"/*.json "$MUTATE_SAVE_RES/"; fi
"${PY[@]}" - "$RES" <<'PY'
import glob, json, os, sys
operators, verdicts = {}, {}
for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    d = json.load(open(path))
    here = {}
    for m in d["mutants"]:
        operators[m["operator"]] = operators.get(m["operator"], 0) + 1
        if m["compile"]["status"] == "unviable":
            v = "unviable"
        elif m["compile"]["hash"] == d["sources"][[s["file"] for s in d["sources"]].index(m["file"])]["baseline"]["hash"]:
            v = "equivalent"
        else:
            v = "run" if m["runs"] else "duplicate"
        here[v] = here.get(v, 0) + 1
        verdicts[v] = verdicts.get(v, 0) + 1
    print("    %-8s %3d mutants  %s" % (os.path.basename(path)[:-5], len(d["mutants"]), dict(sorted(here.items()))))
print("    all      %3d mutants  %s" % (sum(operators.values()), dict(sorted(verdicts.items()))))
print("    per operator:", dict(sorted(operators.items())))
PY

begin "batches change nothing: batch sizes 1 and 3 give byte-identical reports to the default 16 (T064)"
run "$out/build_b.log" build "$pkg:pinned_b1" "$pkg:pinned_b3" "$pkg:weak_b1" "$pkg:weak_b3" "$pkg:multi_b1" "$pkg:multi_b3" "$pkg:uninit_b1" "$pkg:uninit_b3" --show-full-output || fail "$CUR: buck2 build failed" "$out/build_b.log"
echo "    executed $(executed "$out/build_b.log") actions"
# `uninit` reads uninitialised memory on purpose: which of its checks fails first depends on the stack layout, which
# depends on the environment of the action (it carries the target name), so its reports are compared by verdict
verdicts() { "${PY[@]}" - "$1" "$root/gate" <<'PY'
import shutil, sys, tempfile
sys.path.insert(0, sys.argv[2])
from rigor_lib import mutants_report, mutants_verdict
with tempfile.TemporaryDirectory() as d:
    shutil.copy(sys.argv[1], d)
    ((label, report),) = mutants_report.load_reports_dir(d).items()
    base, ids = mutants_verdict.baseline_findings(report, "L3")
    verdicts, found = mutants_verdict.derive(report, ids)
    for v in verdicts:
        print(v.mutant.id, v.verdict)
    print(sorted(map(str, base + found)))
PY
}
for name in pinned weak multi uninit; do
  for n in 1 3; do
    p="$(awk -v t="$pkg:${name}_b${n}" 'index($1, t) {print $2}' "$out/build_b.log" | tail -1)"
    [ -f "$p" ] || fail "$CUR: no report for ${name}_b${n}"
    if [ "$name" = uninit ]; then
      cmp -s <(verdicts "$p") <(verdicts "$RES/$name.json") || fail "$CUR: ${name} with batch $n has other verdicts than the default build"
      echo "    ${name}_b${n}: $(verdicts "$p" | wc -l) verdict lines, identical to the default"
    else
      # the report names its target; everything else must be the same
      cmp -s <(sed 's/_mutants//g; s/_b'"$n"'//g' "$p") <(sed 's/_mutants//g' "$RES/$name.json") || fail "$CUR: ${name} with batch $n differs from the default build" <(diff <("${PY[@]}" -m json.tool "$p") <("${PY[@]}" -m json.tool "$RES/$name.json") | head -40)
      echo "    ${name}_b${n}: $(wc -c < "$p") bytes, identical to the default"
    fi
  done
done

begin "RED: the known survivors of the weak tests are reported as survivors, precisely"
mkdir -p "$out/only_weak"; cp "$RES/weak.json" "$out/only_weak/"
printf '[module."%s:weak_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_weak"
[ "$GATE_CODE" = 1 ] || fail "$CUR: expected exit 1, got $GATE_CODE" "$out/gate.log"
got="$(json '"\n".join(sorted("%s|%s|%s" % (f["function"], f["operator"], f["replacement"]) for f in r["findings"] if f["rule"] == "survived-mutant"))')"
# T051: `x + x` -> `x - x` has the object of the function-body mutant at -O2 (a duplicate), but not at -O0, so it runs (and survives)
want='double_it|arithmetic|-
double_it|function-body|{ (void)x; return 0; }
find|condition|!(a[i] == v)
find|increment|--
find|integer-literal|1
find|relational|<=
find|return-value|((void)(0), (int *)1)
store|function-body|{ (void)slot; (void)v; }'
[ "$got" = "$want" ] || fail "$CUR: survivors differ from the expected list" <(printf 'got:\n%s\nwant:\n%s\n' "$got" "$want")
[ "$(json '[f["rule"] for f in r["findings"]].count("survived-mutant")')" = 8 ] || fail "$CUR: not exactly 8 findings"
echo "    8 survivors, exit 1, as expected"
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
[ "$(rules)" = "['no-mutants', 'unaccounted-function']" ] || fail "$CUR: unexpected rules $(rules)" "$out/gate.log"
echo "    exit 1, rules $(rules): the same blindness found twice, independently"

begin "GREEN: functions whose only attribute follows the body are mutated, killed or surviving as their tests dictate (B19)"
mkdir -p "$out/only_attr"; cp "$RES/attr.json" "$out/only_attr/"
printf '[module."%s:attr_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_attr"
[ "$GATE_CODE" = 1 ] || fail "$CUR: expected the weak attributed function to leave survivors (exit $GATE_CODE)" "$out/gate.log"
[ "$(rules)" = "['survived-mutant']" ] || fail "$CUR: unexpected rules $(rules)" "$out/gate.log"
[ "$(json 'sorted({f["function"] for f in r["findings"]})')" = "['attr_weak']" ] || fail "$CUR: survivors outside attr_weak" "$out/gate.log"
"${PY[@]}" - "$RES/attr.json" <<'PY' || fail "$CUR: bad attr report"
import json, sys
d = json.load(open(sys.argv[1]))
s = d["sources"][0]
assert s["definitions"] == 3 and [f["name"] for f in s["functions"]] == ["attr_strong", "attr_weak", "attr_macro"], s
assert not any("reason" in f for f in s["functions"]) and s["skipped"] == [], s
by = {}
for m in d["mutants"]:
    by[m["function"]] = by.get(m["function"], 0) + 1
assert by.get("attr_strong", 0) >= 3 and by.get("attr_weak", 0) >= 3 and by.get("attr_macro", 0) >= 3, by
print("    definitions 3, functions", [f["name"] for f in s["functions"]], "mutants per function", by)
PY
echo "    attr_strong: no survivor; attr_weak: $(json 'len(r["findings"])') survivors"

begin "RED: a generator that loses a function fails closed, in the generator (exit 2) and again in the gate"
"${PY[@]}" - "$root" "$out" <<'PY' || fail "$CUR: the broken generator was not refused"
import importlib.util, json, os, subprocess, sys
root, out = sys.argv[1], sys.argv[2]
fix = os.path.join(root, "gate/tests/fixtures/mutate")
runner = os.path.join(out, "broken_gen.py")
with open(runner, "w") as handle:
    handle.write("""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("gen", sys.argv[1])
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)
def broken(self, node, ctx):  # gen.py as it was before B19: the body is the last child
    body = node["inner"][-1] if node.get("inner") else None
    if not body or body.get("kind") != "CompoundStmt" or node.get("isImplicit"):
        return ctx
    return gen.Walker.fixed_enter_function(self, node, ctx)
gen.Walker.fixed_enter_function = gen.Walker.enter_function
gen.Walker.enter_function = broken
gen.main(sys.argv[2:])
""")
common = ["--src", "attributes.c", "--ast", os.path.join(fix, "attributes.ast.json")]
gen_py = os.path.join(root, "mutate/gen.py")
good = subprocess.run([sys.executable, "-I", "-B", gen_py] + common + ["--out", os.path.join(out, "good.json")],
                      cwd=fix, capture_output=True, text=True)
assert good.returncode == 0, good.stderr
bad = subprocess.run([sys.executable, "-I", "-B", runner, gen_py] + common + ["--out", os.path.join(out, "bad.json")],
                     cwd=fix, capture_output=True, text=True)
assert bad.returncode == 2, (bad.returncode, bad.stderr)
assert not os.path.exists(os.path.join(out, "bad.json"))
assert "after_noinline" in bad.stderr and "accounting failed" in bad.stderr, bad.stderr
print("    fixed generator: exit 0 with %d definitions; broken generator: exit 2, writes nothing" %
      json.load(open(os.path.join(out, "good.json")))["definitions"])
print("   ", bad.stderr.strip()[:200])
PY
# the gate's own cross-check: a report whose generator dropped a function (and lied about nothing else)
mkdir -p "$out/lost"
"${PY[@]}" - "$RES/attr.json" "$out/lost/attr.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
s = d["sources"][0]
s["functions"] = [f for f in s["functions"] if f["name"] != "attr_weak"]
d["mutants"] = [m for m in d["mutants"] if m["function"] != "attr_weak"]
json.dump(d, open(sys.argv[2], "w"))
PY
printf '[module."%s:attr_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/lost"
[ "$GATE_CODE" = 1 ] || fail "$CUR: a report that lost a function passed (exit $GATE_CODE)" "$out/gate.log"
[ "$(rules)" = "['unaccounted-function']" ] || fail "$CUR: unexpected rules $(rules)" "$out/gate.log"
echo "    gate: exit 1, $(json 'r["findings"][0]["definitions"]') definitions but $(json 'r["findings"][0]["listed"]') listed -> $(rules)"
printf '[module."%s:pinned_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"

begin "GREEN: the strongly pinned module has no survivor and has equivalents (TCE)"
mkdir -p "$out/only_pinned"; cp "$RES/pinned.json" "$out/only_pinned/"
gate "$out/only_pinned"
[ "$GATE_CODE" = 0 ] || fail "$CUR: expected exit 0, got $GATE_CODE" "$out/gate.log"
v="$(json 'r["metadata"]["modules"].popitem()[1]["verdicts"]')"
echo "    $v"
"${PY[@]}" - "$RES/pinned.json" <<'PY' || fail "$CUR: bad pinned report"
import json, sys
d = json.load(open(sys.argv[1]))
ops = {m["operator"] for m in d["mutants"]}
assert {"relational", "arithmetic", "logical", "condition", "integer-literal", "return-value",
        "increment", "function-body"} <= ops, ops
kinds = {}
for m in d["mutants"]:
    s = m["compile"]["status"]
    kinds[s] = kinds.get(s, 0) + 1
print("    compile statuses:", kinds)
PY
"${PY[@]}" - "$out/result.json" <<'PY' || fail "$CUR: counts"
import json, sys
m = json.load(open(sys.argv[1]))["metadata"]["modules"].popitem()[1]
assert m["verdicts"]["survived"] == 0 and m["verdicts"]["equivalent"] >= 1 and m["verdicts"]["killed-assert"] >= 10, m
PY

begin "RED: code a macro of the product writes is a finding (L3 error, L2 info); the constant macro next to an operator is not"
mkdir -p "$out/only_macro"; cp "$RES/macro.json" "$out/only_macro/"
printf '[module."%s:macro_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_macro"
[ "$GATE_CODE" = 1 ] || fail "$CUR: macro-hidden code passed L3 (exit $GATE_CODE)" "$out/gate.log"
[ "$(rules)" = "['macro-hidden-code']" ] || fail "$CUR: unexpected rules $(rules)" "$out/gate.log"
"${PY[@]}" - "$out/result.json" "$RES/macro.json" "$scratch/m/macro.c" <<'PY' || fail "$CUR: bad macro findings"
import json, sys
r = json.load(open(sys.argv[1]))
d = json.load(open(sys.argv[2]))
src = open(sys.argv[3]).read().split("\n")
use = next(i + 1 for i, l in enumerate(src) if "if (IS_NEG(x))" in l)
define = next(i + 1 for i, l in enumerate(src) if l.startswith("#define IS_NEG"))
limit = next(i + 1 for i, l in enumerate(src) if "if (x > LIMIT)" in l)
found = [(f["function"], f["macro"], f["line"], f["file"].rsplit("/", 1)[-1]) for f in r["findings"]]
assert found == [("macro_sign", "IS_NEG", use, "macro.c")], found
bad = [m for m in d["mutants"] if m["line"] in (use, define)]
assert not bad, "mutants inside the macro expansion: %r" % bad
assert [m["replacement"] for m in d["mutants"] if m["line"] == limit and m["operator"] == "relational"] == ["<=", ">="], \
    "the operator next to the constant macro was not mutated"
hidden = d["sources"][0]["hidden"]
assert [(h["function"], h["macro"], h["line"]) for h in hidden] == [("macro_sign", "IS_NEG", use)], hidden
print("    macro-hidden-code at line", use, "(IS_NEG); no mutant on lines", define, use, "; x > LIMIT (line", limit, ") mutated")
PY
printf '[module."%s:macro_mutants"]\nlevel = "L2"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_macro"
[ "$GATE_CODE" = 0 ] || fail "$CUR: the macro finding must be info at L2 (exit $GATE_CODE)" "$out/gate.log"
[ "$(json 'sorted({(f["rule"], f["severity"]) for f in r["findings"]})')" = "[('macro-hidden-code', 'info')]" ] \
  || fail "$CUR: L2 findings: $(json 'r["findings"]')" "$out/gate.log"
echo "    L2: exit 0, info"
printf '[module."%s:pinned_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"

# T051: the condition and return-value mutants of lit_get had the function-body mutant's object at -O2 (duplicates); at -O0
# they differ, so they run, and the weak test leaves them alive too.
begin "RED: a toolchain NULL in a condition, enumerators, strings and characters are mutated, and weak tests leave exactly their survivors (T035)"
cat >> "$scratch/m/BUCK" <<'EOF'

c_library(name = "lit", srcs = ["lit.c"], headers = ["lit.h"])
c_test(name = "lit_test", srcs = ["lit_test.c"], deps = [":lit"])
c_mutants(name = "lit_mutants", module = ":lit", tests = [":lit_test"])
EOF
cat > "$scratch/m/lit.h" <<'EOF'
#ifndef LIT_H
#define LIT_H
typedef enum { LIT_OK = 0, LIT_ERR_LOW = 1, LIT_ERR_HIGH = 2 } lit_status;
int lit_get(const int *p);
lit_status lit_check(int v);
const char *lit_name(void);
char lit_letter(void);
#endif
EOF
cat > "$scratch/m/lit.c" <<'EOF'
#include "lit.h"

#include <stddef.h>

int lit_get(const int *p)
{
    int v = 0;
    if (p != NULL) {
        v = *p;
    }
    return v;
}

lit_status lit_check(int v)
{
    if (v < 0) {
        return LIT_ERR_LOW;
    }
    if (v > 9) {
        return LIT_ERR_HIGH;
    }
    return LIT_OK;
}

const char *lit_name(void) { return "lit"; }

char lit_letter(void) { return 'q'; }
EOF
cat > "$scratch/m/lit_test.c" <<'EOF'
#include "ctest/ctest.h"
#include "lit.h"

static void t_lit(ctest_t *t)
{
    int zero = 0;
    CHECK_EQ_I64(t, lit_get(&zero), 0);
    CHECK_EQ_I64(t, lit_check(0), LIT_OK);
    CHECK_EQ_I64(t, lit_check(5), LIT_OK);
    CHECK_EQ_I64(t, lit_check(9), LIT_OK);
    CHECK(t, lit_check(-1) != LIT_OK);
    CHECK(t, lit_check(10) != LIT_OK);
    CHECK(t, lit_name() != NULL);
    CHECK(t, lit_letter() != 0);
}

CTEST_SUITE("lit", { "lit", t_lit })
EOF
run "$out/build_lit.log" build "$pkg:lit_mutants" --show-full-output || fail "$CUR: buck2 build failed" "$out/build_lit.log"
p="$(awk -v t="$pkg:lit_mutants" 'index($1, t) {print $2}' "$out/build_lit.log" | tail -1)"
[ -f "$p" ] || fail "$CUR: no report for lit"
mkdir -p "$out/only_lit"; cp "$p" "$out/only_lit/lit.json"
printf '[module."%s:lit_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_lit"
[ "$GATE_CODE" = 1 ] || fail "$CUR: expected exit 1, got $GATE_CODE" "$out/gate.log"
got="$(json '"\n".join(sorted("%s|%s|%s|%s" % (f["function"], f["operator"], f["line"], f["replacement"]) for f in r["findings"] if f["rule"] == "survived-mutant"))')"
want="$(cat <<'EOF'
lit_check|enum-constant|17|LIT_ERR_HIGH
lit_get|condition|8|!(p != NULL)
lit_get|function-body|6|{ (void)p; return 0; }
lit_get|integer-literal|7|1
lit_get|return-value|11|((void)(v), (int)0)
lit_letter|char-literal|27|('q' + 1)
lit_name|string-literal|25|""
lit_name|string-literal|25|m
EOF
)"
[ "$got" = "$want" ] || fail "$CUR: survivors differ from the expected list" <(printf 'got:\n%s\nwant:\n%s\n' "$got" "$want")
"${PY[@]}" - "$out/only_lit/lit.json" <<'PY' || fail "$CUR: bad lit report"
import json, sys
d = json.load(open(sys.argv[1]))
ops = {}
for m in d["mutants"]:
    ops.setdefault(m["operator"], set()).add(m["function"])
assert ops["condition"] >= {"lit_get"}, "the condition with NULL has no condition mutant"
assert ops["enum-constant"] == {"lit_check"} and ops["string-literal"] == {"lit_name"} and ops["char-literal"] == {"lit_letter"}, ops
assert not d["sources"][0]["hidden"], "a toolchain macro was reported as hidden code"
print("    new operators:", {k: sorted(v) for k, v in sorted(ops.items()) if k in ("condition", "enum-constant", "string-literal", "char-literal")})
PY
# (the condition and return-value mutants of `p != NULL` compile to the function-body mutant's object at -O2 but not at -O0)
echo "    survivors exactly as expected: $(printf '%s\n' "$got" | wc -l)"
printf '[module."%s:pinned_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"

begin "GREEN: struct returns, direct and through typedefs, get mutants that all compile, and a strong test kills them all (T050)"
cat >> "$scratch/m/BUCK" <<'EOF'

c_library(name = "rec", srcs = ["rec.c"], headers = ["rec.h"])
c_test(name = "rec_test", srcs = ["rec_test.c"], deps = [":rec"])
c_mutants(name = "rec_mutants", module = ":rec", tests = [":rec_test"])
EOF
cat > "$scratch/m/rec.h" <<'EOF'
#ifndef REC_H
#define REC_H
typedef struct { int a; int b; } rec_box_t;
typedef struct rec_span { int ptr; int len; } rec_span_t;
typedef rec_span_t rec_span2_t;
struct rec_pair { int lo; int hi; };
rec_box_t rec_box(int x, int y);
rec_span_t rec_span(int len);
rec_span2_t rec_span2(int len);
struct rec_pair rec_pair(int x, int y);
#endif
EOF
cat > "$scratch/m/rec.c" <<'EOF'
#include "rec.h"

rec_box_t rec_box(int x, int y)
{
    rec_box_t r;
    r.a = x;
    r.b = y;
    return r;
}

rec_span_t rec_span(int len)
{
    rec_span_t r;
    r.ptr = 7;
    r.len = len;
    return r;
}

rec_span2_t rec_span2(int len)
{
    rec_span2_t r;
    r.ptr = 9;
    r.len = len;
    return r;
}

struct rec_pair rec_pair(int x, int y)
{
    struct rec_pair r;
    r.lo = x;
    r.hi = y;
    return r;
}
EOF
cat > "$scratch/m/rec_test.c" <<'EOF'
#include "ctest/ctest.h"
#include "rec.h"

static void t_rec(ctest_t *t)
{
    rec_box_t b = rec_box(3, 4);
    rec_span_t s = rec_span(5);
    rec_span2_t s2 = rec_span2(6);
    struct rec_pair p = rec_pair(1, 2);
    CHECK_EQ_I64(t, b.a, 3);
    CHECK_EQ_I64(t, b.b, 4);
    CHECK_EQ_I64(t, s.ptr, 7);
    CHECK_EQ_I64(t, s.len, 5);
    CHECK_EQ_I64(t, s2.ptr, 9);
    CHECK_EQ_I64(t, s2.len, 6);
    CHECK_EQ_I64(t, p.lo, 1);
    CHECK_EQ_I64(t, p.hi, 2);
}

CTEST_SUITE("rec", { "rec", t_rec })
EOF
run "$out/build_rec.log" build "$pkg:rec_mutants" --show-full-output || fail "$CUR: buck2 build failed" "$out/build_rec.log"
p="$(awk -v t="$pkg:rec_mutants" 'index($1, t) {print $2}' "$out/build_rec.log" | tail -1)"
[ -f "$p" ] || fail "$CUR: no report for rec"
mkdir -p "$out/only_rec"; cp "$p" "$out/only_rec/rec.json"
printf '[module."%s:rec_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_rec"
[ "$GATE_CODE" = 0 ] || fail "$CUR: expected exit 0, got $GATE_CODE" "$out/gate.log"
"${PY[@]}" - "$out/only_rec/rec.json" <<'PY' || fail "$CUR: bad rec report"
import json, sys
d = json.load(open(sys.argv[1]))
assert all(f.get("reason") is None for f in d["sources"][0]["functions"]), "a struct-returning function has no mutants"
for fn in ("rec_box", "rec_span", "rec_span2", "rec_pair"):
    ops = {m["operator"] for m in d["mutants"] if m["function"] == fn}
    assert ops >= {"function-body", "return-value"}, (fn, ops)
bad = [m["id"] for m in d["mutants"] if m["compile"]["status"] == "unviable"]
assert not bad, "mutants that do not compile: %s" % bad
print("    %d mutants, none unviable" % len(d["mutants"]))
PY
echo "    gate green: no unviable mutant, no no-assert-kill-function, no survivor"

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

begin "RED: code no mutant can reach (a function made by a macro, an inline function in a header) fails L3"
mkdir -p "$out/only_hidden"; cp "$RES/hidden.json" "$out/only_hidden/"
printf '[module."%s:hidden_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_hidden"
[ "$GATE_CODE" = 1 ] || fail "$CUR: unreachable functions passed (exit $GATE_CODE)" "$out/gate.log"
[ "$(rules)" = "['unmutated-function']" ] || fail "$CUR: unexpected rules $(rules)" "$out/gate.log"
got="$(json '"\n".join(sorted("%s:%s" % (f["function"], f["reason"]) for f in r["findings"]))')"
[ "$got" = "inl:header
twice:macro" ] || fail "$CUR: unexpected functions: $got"
echo "    $(echo $got | tr '\n' ' ')- and plain() was mutated: $(json 'r["metadata"]["modules"].popitem()[1]["verdicts"]')"

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
    run = d["baseline_runs"]["selftest_scratch_mut_m__pinned_test"]
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
run "$out/build_ids.log" build "$pkg:equiv_mutants" "$pkg:multi_mutants" "$pkg:hidden_mutants" --show-full-output || fail "$CUR: build" "$out/build_ids.log"
p="$(awk -v t="$pkg:equiv_mutants" 'index($1, t) {print $2}' "$out/build_ids.log" | tail -1)"
mkdir -p "$out/shifted"; cp "$p" "$out/shifted/equiv.json"
gate "$out/shifted"
[ "$(json '[f["id"] for f in r["findings"] if f["rule"] == "survived-mutant"][0]')" = "$id" ] || fail "$CUR: the survivor id changed"
[ "$(json '[f["line"] for f in r["findings"] if f["rule"] == "survived-mutant"][0]')" = $((old_line + 1)) ] || fail "$CUR: the line did not move"
echo "    same id $id, line moved $old_line -> $((old_line + 1))"
sed -i '1d' "$scratch/m/equiv.c"

# T058 / B18 (R001 R6): ids are bound to the mutated token and to the body of the function. The approved `<=` -> `<`
# of twice_pos is rewritten so that the same group and ordinal now names a mutation that changes the result for
# n = 100 and that no test checks. The old approval must not cover it. (This is a step here and not a canary because
# the canary pack carries no signed approvals.)
begin "approval drift: after the function body changes, the old equivalent-mutant approval covers nothing"
cp "$scratch/m/equiv.c" "$out/equiv.c.orig"
cat > "$scratch/m/equiv.c" <<'EOF'
#include "equiv.h"

int twice_pos(int n)
{
    if (n > 0 && n <= 100) {
        return n * 2;
    }
    return 0;
}
EOF
run "$out/build_drift.log" build "$pkg:equiv_mutants" --show-full-output || fail "$CUR: build" "$out/build_drift.log"
p="$(awk -v t="$pkg:equiv_mutants" 'index($1, t) {print $2}' "$out/build_drift.log" | tail -1)"
mkdir -p "$out/drift"; cp "$p" "$out/drift/equiv.json"
gate "$out/drift" --approvals "$out/approvals" "${AP[@]}"
[ "$GATE_CODE" = 1 ] || fail "$CUR: the old approval covered the drifted function (exit $GATE_CODE)" "$out/gate.log"
[ "$(json '[f["id"] for f in r["findings"] if f["rule"] == "survived-mutant" and f["original"] == "<=" and f["replacement"] == "<"] != []')" = True ] || fail "$CUR: the untested <= -> < mutant is not a survivor" "$out/gate.log"
[ "$(json '[f for f in r["findings"] if f.get("id") == "'"$id"'"]')" = "[]" ] || fail "$CUR: the old id still names a mutant of the edited function" "$out/gate.log"
[ "$(json 'r["metadata"]["approvals_used"]')" = "[]" ] || fail "$CUR: the old approval was used" "$out/gate.log"
echo "    old id $id names nothing now; no approval used; the same-ordinal <= -> < survives"
cp "$out/equiv.c.orig" "$scratch/m/equiv.c"

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
echo "    executed $n actions; the weak module has $live live mutants"
# T064: the live mutants of the weak module run in batches of at most 16 (one action per batch and test), plus the
# test's compile, the baseline run and the report; before batching this was one action per live mutant
[ "$n" -ge 3 ] && [ "$n" -le 8 ] || fail "$CUR: expected 3 to 8 actions for $live live mutants (batched), got $n" "$out/build3.log"
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

begin "GREEN: tests that use a header-only kit are mutated (no archive of the kit is linked), failures carry normalised reasons only (T034)"
mkdir -p "$out/only_uninit"; cp "$RES/uninit.json" "$out/only_uninit/"
"${PY[@]}" - "$RES/uninit.json" <<'PY' || fail "$CUR: bad uninit report"
import json, re, sys
d = json.load(open(sys.argv[1]))
runs = [(m["id"], t, r) for m in d["mutants"] for t, r in m["runs"].items()]
assert runs, "no mutant of the kit's module ran"
normal = re.compile(r"0 of 0 checks failed; first: \S+:\d+: CHECK_EQ_I64\(uninit_slot\([0-3]\), \([0-9]+\)\)")
asserted = 0
for mid, test, run in runs:
    assert run["rc"] in (0, 1, -1, -9), (mid, run["rc"])
    for raw in (run["results"] or "").splitlines():
        line = json.loads(raw)
        if "id" not in line:
            continue
        assert line["asserts"] in (0, 1), (mid, line)
        if line["status"] != "fail":
            continue
        if line["reason"].startswith("0 of 0"):
            assert normal.fullmatch(line["reason"]), (mid, line["reason"])  # the check is named, no observed value
            asserted += 1
        else:
            assert not re.search(r"[0-9]", line["reason"]), (mid, line["reason"])
assert asserted, "no mutant was killed by a failed check"
print("    %d runs of %d live mutants, %d killed by a normalised failed check" % (len(runs), len({r[0] for r in runs}), asserted))
PY
printf '[module."%s:uninit_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_uninit"
[ "$GATE_CODE" = 0 ] || [ "$GATE_CODE" = 1 ] || fail "$CUR: the gate did not grade the module (exit $GATE_CODE)" "$out/gate.log"
echo "    graded: $(json 'r["metadata"]["modules"].popitem()[1]["verdicts"]')"

begin "RED: a dependency that provides neither a library nor a header is a build error, not silently dropped (T034)"
if run "$out/bare.log" build "$pkg:bare_mutants"; then fail "$CUR: the build with a bare dependency succeeded" "$out/bare.log"; fi
grep -q "provides neither a library nor headers" "$out/bare.log" || fail "$CUR: the build failed for another reason" "$out/bare.log"
echo "    failed in analysis: $(grep -m1 'provides neither a library nor headers' "$out/bare.log" | sed 's/^ *//' | cut -c1-160)"

begin "DETERMINISM: two cold-keyed grades of the same module give byte-identical reports (T034)"
# A nonce in a string of the test (a comment would not change the object) re-keys every test link and run without
# changing a byte the report records about the module, so every live mutant is run again; the uninit mutants read
# garbage. The count of executed actions printed below shows it.
det_build() {
  local nonce="$1" dest="$2" log="$out/det_$1.log" p
  sed -i "/^const char det_nonce\[\]/d" "$scratch/m/uninit_test.c"
  sed -i "1i const char det_nonce[] = \"$nonce\";" "$scratch/m/uninit_test.c"
  run "$log" build "$pkg:uninit_mutants" --show-full-output || fail "$CUR: buck2 build failed" "$log"
  p="$(awk -v t="$pkg:uninit_mutants" 'index($1, t) {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no report" "$log"
  cp "$p" "$dest"
  echo "    nonce $nonce: executed $(executed "$log") actions"
}
n1="$(date +%s%N)-a"; n2="$(date +%s%N)-b"
det_build "$n1" "$out/det_a.json"
det_build "$n2" "$out/det_b.json"
cmp -s "$out/det_a.json" "$out/det_b.json" || fail "$CUR: the two reports differ" <(diff <("${PY[@]}" -m json.tool "$out/det_a.json") <("${PY[@]}" -m json.tool "$out/det_b.json"))
echo "    reports identical: $(wc -c < "$out/det_a.json") bytes, sha256 $(sha256sum "$out/det_a.json" | cut -c1-16)"

begin "RED/GREEN: a mutation the optimiser folds to the baseline object at -O2 is not equivalent unless it is at -O0 too (T051, B15)"
cat >> "$scratch/m/BUCK" <<'EOF'

c_library(name = "fold", srcs = ["fold.c"], headers = ["fold.h"])
c_test(name = "fold_test", srcs = ["fold_test.c"], deps = [":fold"])
c_mutants(name = "fold_mutants", module = ":fold", tests = [":fold_test"])
EOF
printf '#ifndef FOLD_H\n#define FOLD_H\nint fold_flag(int a);\nint fold_unit(void);\n#endif\n' > "$scratch/m/fold.h"
# `a + 1 < a` is false for every int that is defined: signed overflow is undefined, so the optimiser assumes the branch never
# runs and deletes it. A mutation in that branch (7 -> 8) therefore compiles to the baseline object at -O2. Without the
# optimiser the addition wraps, the branch runs for INT_MAX, and the mutation changes what the function returns.
cat > "$scratch/m/fold.c" <<'EOF'
#include "fold.h"

int fold_flag(int a)
{
    return (a + 1 < a) ? 7 : 3;
}

int fold_unit(void)
{
    return 1 * 1;
}
EOF
cat > "$scratch/m/fold_test.c" <<'EOF'
#include "ctest/ctest.h"
#include "fold.h"

static void t_fold(ctest_t *t)
{
    CHECK_EQ_I64(t, fold_flag(0), 3);
    CHECK_EQ_I64(t, fold_flag(2147483647), 3);
    CHECK_EQ_I64(t, fold_unit(), 1);
}

CTEST_SUITE("fold", { "fold", t_fold })
EOF
run "$out/build_fold.log" build "$pkg:fold_mutants" --show-full-output || fail "$CUR: buck2 build failed" "$out/build_fold.log"
p="$(awk -v t="$pkg:fold_mutants" 'index($1, t) {print $2}' "$out/build_fold.log" | tail -1)"
[ -f "$p" ] || fail "$CUR: no report for fold"
echo "    built, executed $(executed "$out/build_fold.log") actions"
mkdir -p "$out/only_fold"; cp "$p" "$out/only_fold/fold.json"
if [ -n "${MUTATE_SAVE_RES:-}" ]; then cp "$p" "$MUTATE_SAVE_RES/fold.json"; cp "$out/det_a.json" "$MUTATE_SAVE_RES/det_a.json"; fi
"${PY[@]}" - "$out/only_fold/fold.json" <<'PY' || fail "$CUR: bad fold report"
import json, sys
d = json.load(open(sys.argv[1]))
base, base0 = d["sources"][0]["baseline"]["hash"], d["sources"][0]["baseline_o0"]["hash"]
folded = [m for m in d["mutants"] if m["function"] == "fold_flag" and m["original"] == "7" and m["replacement"] == "8"][0]
assert folded["compile"]["hash"] == base, "the -O2 optimiser no longer folds the mutation to the baseline object"
assert folded["compile"]["o0"]["hash"] != base0 and folded["runs"], "the folded mutation was not compiled and run at -O0"
unit = [m for m in d["mutants"] if m["function"] == "fold_unit" and m["operator"] == "arithmetic"][0]
assert unit["compile"]["hash"] == base and unit["compile"]["o0"]["hash"] == base0 and not unit["runs"], unit["compile"]
print("    fold_flag 7 -> 8: -O2 object == baseline, -O0 object differs, ran;  fold_unit 1 * 1 -> 1 / 1: identical at both, no run")
count = sum(1 for m in d["mutants"] if "o0" in m["compile"])
print("    -O0 compiles in this report: %d of %d mutants, plus %d baseline" % (count, len(d["mutants"]), len(d["sources"])))
PY
printf '[module."%s:fold_mutants"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
gate "$out/only_fold"
[ "$GATE_CODE" = 1 ] || fail "$CUR: expected exit 1, got $GATE_CODE" "$out/gate.log"
got="$(json '"\n".join(sorted("%s|%s|%s" % (f["function"], f["operator"], f["replacement"]) for f in r["findings"]))')"
want='fold_flag|integer-literal|0'
[ "$got" = "$want" ] || fail "$CUR: findings differ from the expected list" <(printf 'got:\n%s\nwant:\n%s\n' "$got" "$want")
"${PY[@]}" - "$out/result.json" <<'PY' || fail "$CUR: tce metadata"
import json, sys
m = json.load(open(sys.argv[1]))["metadata"]["modules"].popitem()[1]
t = m["tce"]
assert 0 < t["equivalent_o0"] < t["equivalent_o2"] and m["verdicts"]["equivalent"] == t["equivalent_o0"], m
assert m["verdicts"]["killed-assert"] >= 2 and m["verdicts"]["survived"] == 1, m
print("    tce:", t, " verdicts:", {k: v for k, v in m["verdicts"].items() if v})
PY
echo "    the folded mutants ran at -O0: the INT_MAX check kills the ones that change the result, 1 -> 0 survives (it returns 3 like the optimised build); fold_unit stays equivalent"

echo "elapsed ${SECONDS}s"
echo "selftest/mutate.sh: all checks passed in $SECONDS s"
