#!/usr/bin/env bash
# Self-test of `system_libs` (T095): a module that starts a real pthread, a c_library with system_libs = ["pthread"],
# links into its c_test (release and san), a c_binary, and every mutant binary of its c_mutants; a module without the
# declaration does not link. Needs bash, python3 (stdlib), tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
PLAT=toolchains//:linux_
scratch="selftest/scratch_sl"
pkg="//selftest/scratch_sl/m"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
must_pass() { local log="$out/$step.log"; run "$log" "$@" || fail "$CUR: buck2 $* failed" "$log"; }

mkdir -p "$scratch/m"
cd "$scratch/m"
cat > BUCK <<'EOF'
load("@gate//rules:c.bzl", "c_binary", "c_library", "c_mutants", "c_test")

c_library(name = "thread", srcs = ["thread.c"], headers = ["thread.h"], system_libs = ["pthread"], visibility = ["PUBLIC"])
c_test(name = "thread_test", srcs = ["thread_test.c"], deps = [":thread"])
c_binary(name = "thread_bin", srcs = ["thread_bin.c"], deps = [":thread"])
c_mutants(name = "thread_mutants", module = ":thread", tests = [":thread_test"])

# a library one level up: the tests of `outer` link `thread` through it, and the mutants name it in `deps`
c_library(name = "outer", srcs = ["outer.c"], headers = ["outer.h"], deps = [":thread"], visibility = ["PUBLIC"])
c_test(name = "outer_test", srcs = ["outer_test.c"], deps = [":outer"])
c_mutants(name = "outer_mutants", module = ":outer", tests = [":outer_test"], deps = [":thread"])

# the same code without the declaration does not link: the flag is what links libpthread
c_library(name = "bare", srcs = ["thread.c"], headers = ["thread.h"])
c_test(name = "bare_test", srcs = ["thread_test.c"], deps = [":bare"])
EOF
cat > thread.h <<'EOF'
#ifndef THREAD_H
#define THREAD_H
int thread_sum(int n, int *out);
#endif
EOF
cat > thread.c <<'EOF'
#include <pthread.h>
#include "thread.h"

struct job {
    int n;
    int sum;
};

static void *job_run(void *arg)
{
    struct job *job = arg;
    int i;

    job->sum = 0;
    for (i = 1; i <= job->n; i++) {
        job->sum += i;
    }
    return arg;
}

int thread_sum(int n, int *out)
{
    pthread_t th;
    struct job job;
    void *ret = 0;

    job.n = n;
    job.sum = 0;
    if (pthread_create(&th, 0, job_run, &job) != 0) {
        return -1;
    }
    if (pthread_join(th, &ret) != 0) {
        return -1;
    }
    *out = job.sum;
    return 0;
}
EOF
cat > thread_test.c <<'EOF'
#include "ctest/ctest.h"
#include "thread.h"

static void t_sum(ctest_t *t)
{
    int out = -1;

    CHECK_EQ_I64(t, thread_sum(4, &out), 0);
    CHECK_EQ_I64(t, out, 10);
    CHECK_EQ_I64(t, thread_sum(0, &out), 0);
    CHECK_EQ_I64(t, out, 0);
    CHECK_EQ_I64(t, thread_sum(1, &out), 0);
    CHECK_EQ_I64(t, out, 1);
}

CTEST_SUITE("thread", { "sum", t_sum })
EOF
cat > thread_bin.c <<'EOF'
#include "thread.h"

int main(void)
{
    int out = 0;

    if (thread_sum(3, &out) != 0) {
        return 1;
    }
    return out == 6 ? 0 : 2;
}
EOF
cat > outer.h <<'EOF'
#ifndef OUTER_H
#define OUTER_H
int outer_double_sum(int n);
#endif
EOF
cat > outer.c <<'EOF'
#include "outer.h"
#include "thread.h"

int outer_double_sum(int n)
{
    int out = -1;

    if (thread_sum(n, &out) != 0) {
        return -1;
    }
    return out + out;
}
EOF
cat > outer_test.c <<'EOF'
#include "ctest/ctest.h"
#include "outer.h"

static void t_double(ctest_t *t)
{
    CHECK_EQ_I64(t, outer_double_sum(4), 20);
    CHECK_EQ_I64(t, outer_double_sum(0), 0);
}

CTEST_SUITE("outer", { "double", t_double })
EOF
cd "$root"

begin "release and san: the c_test starts a real pthread and passes (libpthread comes from the declaration)"
for m in release san; do
  must_pass build --target-platforms ${PLAT}$m "$pkg:thread_test_results" "$pkg:outer_test_results"
  echo "  $m: thread_test and outer_test (through a dependent library) pass"
done

begin "a c_binary that links the library links in release and san"
for m in release san; do
  must_pass build --target-platforms ${PLAT}$m "$pkg:thread_bin"
  echo "  $m: thread_bin links"
done

begin "without the declaration the same code does not link (undefined pthread_create)"
if run "$out/bare.log" build "$pkg:bare_test"; then fail "$CUR: bare_test linked" "$out/bare.log"; fi
grep -q "pthread_create" "$out/bare.log" || fail "$CUR: failed for the wrong reason" "$out/bare.log"
echo "  bare_test: link fails on pthread_create"

begin "c_mutants: the baseline and every mutant binary link and run (release)"
run "$out/mut.log" build "$pkg:thread_mutants" "$pkg:outer_mutants" --show-full-output || fail "$CUR: build failed" "$out/mut.log"
for name in thread outer; do
  report="$(awk -v t="$pkg:${name}_mutants" 'index($1, t) {print $2}' "$out/mut.log" | tail -1)"
  [ -f "$report" ] || fail "$CUR: no report for $name '$report'" "$out/mut.log"
  python3 -I -B - "$report" "$name" <<'PY' || fail "$CUR: report of $name"
import json, sys
d = json.load(open(sys.argv[1]))
base = d["baseline_runs"]
assert base and all(r["rc"] == 0 and not r["timed_out"] and r["results"] for r in base.values()), "baseline run did not pass: %r" % base
runs = [r for m in d["mutants"] for r in m["runs"].values()]
assert runs, "no mutant was run"
assert all(r["results"] is not None for r in runs), "a mutant binary did not link or crashed before results"
killed = sum(1 for r in runs if r["rc"] != 0)
assert killed > 0, "no mutant was killed"
print("    %s: baseline passes, %d mutant runs, %d killed, every one linked" % (sys.argv[2], len(runs), killed))
PY
done

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
