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
mkdir -p "$scratch"/{basic,checks,order,badname,dup,san,fds,limits}
for d in basic checks order badname dup san fds limits; do
  printf 'load("@gate//rules:c.bzl", "c_test")\nc_test(name = "t", srcs = ["t.c"])\n' > "$scratch/$d/BUCK"
done

cat > "$scratch/basic/t.c" <<'C'
#include <stdlib.h>
#include <unistd.h>
#include "ctest/ctest.h"

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
#include "ctest/ctest.h"

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
#include "ctest/ctest.h"

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
#include "ctest/ctest.h"
static void t_x(ctest_t *t) { CHECK(t, 1); }
CTEST_SUITE("badname", { "ok_name", t_x }, { "Bad-Name", t_x })
C

cat > "$scratch/dup/t.c" <<'C'
#include "ctest/ctest.h"
static void t_x(ctest_t *t) { CHECK(t, 1); }
CTEST_SUITE("dup", { "same", t_x }, { "same", t_x })
C

cat > "$scratch/san/t.c" <<'C'
#include <stdlib.h>
#include <string.h>
#include "ctest/ctest.h"

/* Lines marked BUG:<case> are where the sanitizer must point; the self-test greps for the marker. */
static volatile int g_idx = 4;
static void *volatile g_sink;
static volatile int g_big = 2147483647;
static int *volatile g_bad = (int *)16; /* not NULL, so UBSan stays quiet and the access raises SIGSEGV */

static void t_fine(ctest_t *t) { CHECK(t, 1); }
static void t_heap_overflow(ctest_t *t) {
    char *p = malloc(4);
    CHECK(t, p != NULL);
    if (p != NULL) {
        p[g_idx] = 1; /* BUG:heap_overflow */
        free(p);
    }
}
static void t_use_after_free(ctest_t *t) {
    char *p = malloc(8);
    CHECK(t, p != NULL);
    if (p != NULL) {
        free(p);
        ((volatile char *)p)[0] = 1; /* BUG:use_after_free */
    }
}
static void t_leak(ctest_t *t) {
    g_sink = malloc(16); /* BUG:leak */
    CHECK(t, g_sink != NULL);
    g_sink = NULL;
}
static void t_ub_overflow(ctest_t *t) {
    int v = g_big + 1; /* BUG:ub_overflow */
    CHECK(t, v != 0);
}
static void t_segv(ctest_t *t) {
    CHECK(t, 1);
    *g_bad = 1; /* BUG:segv */
}

CTEST_SUITE("san",
    { "fine", t_fine }, { "heap_overflow", t_heap_overflow },
    { "use_after_free", t_use_after_free }, { "leak", t_leak },
    { "ub_overflow", t_ub_overflow }, { "segv", t_segv })
C

cat > "$scratch/fds/t.c" <<'C'
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include "ctest/ctest.h"

/* A hostile test: tries to write or pwrite junk into every descriptor it can reach, then returns
 * normally. It must not be able to touch the results file, and its own checks decide its status. */
static void t_scan_fds(ctest_t *t) {
    static const char junk[] = "{\"id\":\"fds/fails\",\"status\":\"pass\",\"asserts\":9,\"reason\":\"\"}\n";
    long open_above_stderr = 0;
    for (int fd = 0; fd < 256; fd++) {
        if (fd > 2 && fcntl(fd, F_GETFD) >= 0) {
            open_above_stderr++;
        }
        if (fd != 1 && fd != 2) { /* 1 and 2 are the log; keep them readable */
            ssize_t a = pwrite(fd, junk, sizeof junk - 1, 0);
            ssize_t b = write(fd, junk, sizeof junk - 1);
            (void)a;
            (void)b;
        }
    }
    CHECK_EQ_I64(t, open_above_stderr, 0);
}
static void t_fails(ctest_t *t) { CHECK(t, 0); }
static void t_after(ctest_t *t) { CHECK(t, 1); }

CTEST_SUITE("fds", { "scan_fds", t_scan_fds }, { "fails", t_fails }, { "after", t_after })
C

# T097: runaway tests. Every loop is bounded by the test itself (1 GiB, 16 x 60 MiB, 1000 opens), so even a
# harness without the limits would stop; with them each runaway ends in seconds.
cat > "$scratch/limits/t.c" <<'C'
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "ctest/ctest.h"

static char g_buf[1 << 20];

static int open_in_tmp(const char *name) {
    static char path[512];
    const char *d = getenv("TMPDIR");
    (void)snprintf(path, sizeof path, "%s/%s", d == NULL ? "/tmp" : d, name);
    return open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
}

/* The incident: the same bytes written forever. The bound is 1 GiB; RLIMIT_FSIZE stops it at 64 MiB with EFBIG. */
static void t_write_forever(ctest_t *t) {
    int fd = open_in_tmp("forever");
    int all_written = 1;
    CHECK(t, fd >= 0);
    for (int i = 0; i < 1024 && all_written; i++) {
        all_written = write(fd, g_buf, sizeof g_buf) == (ssize_t)sizeof g_buf;
    }
    CHECK(t, all_written); /* fails: the write that crossed 64 MiB returned -1 */
}

static void t_efbig_is_reported(ctest_t *t) {
    int fd = open_in_tmp("efbig");
    long n = 0;
    ssize_t w = 0;
    CHECK(t, fd >= 0);
    for (int i = 0; i < 1024 && w >= 0; i++) {
        w = write(fd, g_buf, sizeof g_buf);
        n += w > 0 ? (long)w : 0;
    }
    CHECK_EQ_I64(t, n, 64L << 20);
    CHECK_EQ_I64(t, errno, EFBIG);
}

/* Many files, each under the per-file limit: the scratch quota ends it (256 MiB; the bound here is 960 MiB). */
static void t_many_files(ctest_t *t) {
    static char name[32];
    CHECK(t, 1);
    for (int f = 0; f < 16; f++) {
        int fd;
        (void)snprintf(name, sizeof name, "many%d", f);
        fd = open_in_tmp(name);
        for (int i = 0; fd >= 0 && i < 60; i++) {
            (void)!write(fd, g_buf, sizeof g_buf);
        }
        if (fd >= 0) { (void)close(fd); }
    }
}

static void t_many_entries(ctest_t *t) {
    static char name[32];
    CHECK(t, 1);
    for (int f = 0; f < 20000; f++) {
        (void)snprintf(name, sizeof name, "e%d", f);
        (void)close(open_in_tmp(name));
    }
}

static void t_nofile(ctest_t *t) {
    static int fds[1000];
    int opened = 0, last_errno = 0;
    for (int i = 0; i < 1000; i++) {
        fds[i] = open("/dev/null", O_RDONLY);
        if (fds[i] < 0) { last_errno = errno; break; }
        opened++;
    }
    for (int i = 0; i < opened; i++) { (void)close(fds[i]); } /* the sanitizer runtime needs descriptors at exit */
    CHECK_EQ_I64(t, last_errno, EMFILE);
    CHECK(t, opened > 200 && opened < 256);
}

static void t_core_and_cpu(ctest_t *t) {
    char b[64];
    FILE *f = fopen("/proc/self/limits", "r");
    int core_ok = 0, cpu_ok = 0;
    CHECK(t, f != NULL);
    while (f != NULL && fgets(b, sizeof b, f) != NULL) {
        core_ok |= strncmp(b, "Max core file size", 18) == 0 && strstr(b, " 0 ") != NULL;
        cpu_ok |= strncmp(b, "Max cpu time", 12) == 0 && strstr(b, " 20 ") != NULL;
    }
    CHECK(t, core_ok);
    CHECK(t, cpu_ok);
}

/* The private $TMPDIR of the previous runaways is gone: this one starts empty. */
static void t_scratch_is_private_and_empty(ctest_t *t) {
    const char *d = getenv("TMPDIR");
    static char cmd[600];
    FILE *p;
    char line[16];
    CHECK(t, d != NULL && strstr(d, "/ctest.") != NULL);
    (void)snprintf(cmd, sizeof cmd, "ls -A '%s' | wc -l", d);
    p = popen(cmd, "r");
    CHECK(t, p != NULL && fgets(line, sizeof line, p) != NULL && atoi(line) == 0);
    if (p != NULL) { (void)pclose(p); }
}

CTEST_SUITE("limits",
    { "write_forever", t_write_forever },
    { "efbig_is_reported", t_efbig_is_reported },
    { "many_files", t_many_files },
    { "many_entries", t_many_entries },
    { "nofile", t_nofile },
    { "core_and_cpu", t_core_and_cpu },
    { "scratch_is_private_and_empty", t_scratch_is_private_and_empty })
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
    "exit_zero_early": ("fail", 0, r"exited without reporting.*"),
    "raw_exit_zero_early": ("fail", 0, r"exited without reporting.*"),
    "check_then_exit_zero": ("fail", 0, r"exited without reporting.*"),
    "check_then_raw_exit_zero": ("fail", 0, r"exited without reporting.*"),
    "exit_one": ("fail", 0, r"exited with status 1 before reporting"),
    "hang": ("fail", 0, r"timeout after 10 s"),
    "hang_no_checks": ("fail", 0, r"timeout after 10 s"),
  },
  "checks": {
    "i64_ok": ("pass", 1, r""),
    "i64_bad": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_I64\(-5, 7\): -5 != 7"),
    "u64_ok": ("pass", 1, r""),
    "u64_bad": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_U64\(1U, 2U\): 1 != 2"),
    "str_ok": ("pass", 2, r""),
    "str_bad": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_STR\(\"abc\", \"abd\"\): \"abc\" != \"abd\""),
    "str_null": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_STR\(\"abc\", NULL\): \"abc\" != \(null\)"),
    "str_escapes": ("fail", 1, r"(?s)1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_STR.*: \"a\"b\\c\nd\t\x01\u00ff\" != \"x\""),
    "mem_ok": ("pass", 2, r""),
    "mem_bad": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_MEM\(.*\): first difference at offset 3"),
    "mem_len": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK_EQ_MEM\(.*\): lengths 3 != 2"),
    "continues": ("fail", 3, r"2 of 3 checks failed; first: .*t\.c:\d+: CHECK\(0\)"),
  },
  "fds": {
    "scan_fds": ("pass", 1, r""),
    "fails": ("fail", 1, r"1 of 1 checks failed; first: .*t\.c:\d+: CHECK\(0\)"),
    "after": ("pass", 1, r""),
  },
  "limits": {
    "write_forever": ("fail", 2, r"1 of 2 checks failed; first: .*t\.c:\d+: CHECK\(all_written\)"),
    "efbig_is_reported": ("pass", 3, r""),
    "many_files": ("fail", 0, r"scratch quota exceeded \(limit 256 MiB, 4096 entries under \$TMPDIR\)"),
    "many_entries": ("fail", 0, r"scratch quota exceeded \(limit 256 MiB, 4096 entries under \$TMPDIR\)"),
    "nofile": ("pass", 2, r""),
    "core_and_cpu": ("pass", 3, r""),
    "scratch_is_private_and_empty": ("pass", 2, r""),
  },
  "order": None,   # checked separately
  "san": None,     # checked separately: reasons must name file:line function
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
    elif cmd == "san":
        # args: results.jsonl san_report.txt source.c
        rows, _ = load(sys.argv[2])
        report = open(sys.argv[3], encoding="utf-8").read()
        src = open(sys.argv[4], encoding="utf-8").read().split("\n")
        marks = {}
        for n, text in enumerate(src, 1):
            m = re.search(r"BUG:(\w+)", text)
            if m:
                marks[m.group(1)] = n
        func = {k: "t_" + k for k in marks}
        kinds = {"heap_overflow": "AddressSanitizer: heap-buffer-overflow",
                 "use_after_free": "AddressSanitizer: heap-use-after-free",
                 "leak": "LeakSanitizer: detected memory leaks",
                 "ub_overflow": "UBSan: signed integer overflow",
                 "segv": "AddressSanitizer: SEGV"}
        got = {r["id"].split("/", 1)[1]: r for r in rows}
        assert set(got) == set(kinds) | {"fine"}, sorted(got)
        assert got["fine"]["status"] == "pass" and got["fine"]["reason"] == "", got["fine"]
        for name, kind in kinds.items():
            r = got[name]
            assert r["status"] == "fail", r
            want = r"; %s.* at selftest/scratch_ctest/san/t\.c:%d %s$" % (re.escape(kind), marks[name], func[name])
            assert re.search(want, r["reason"]), (name, r["reason"], want)
            assert len(r["reason"]) <= 512, r["reason"]
            assert not re.search(r"0x[0-9a-fA-F]|(?<![\w.'])/[A-Za-z]|==\d+==", r["reason"]), ("address, pid or absolute path", r["reason"])
            assert ("== san/%s ==" % name) in report, ("not in the san report", name)
            print("  %-14s reason: %s" % (name, r["reason"]))
        assert "== san/fine ==" not in report
        assert not re.search(r"0x[0-9a-fA-F]|==\d+==|BuildId|/data/work|/var/tmp|/work/[0-9a-f]{8}-", report), "report holds addresses, pids or worker paths"
        for f in ("t.c:%d" % n for n in marks.values()):
            assert f in report, ("frame missing in the report", f)
        print("  san: 5 sanitizer cases name the right file:line function; report is normalized")
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
build_out fds_res release "$pkg/fds:t_results"
chk suite fds "$fds_res" || fail "$CUR: a test altered the results file or leaked a descriptor"

begin "limits (T097): a test that writes forever, floods $TMPDIR, leaks descriptors fails fast in release and san; the limits are set"
for mode in release san; do
  t0=$SECONDS
  build_out lim_res "$mode" "$pkg/limits:t_results"
  echo "  $mode: results in $((SECONDS - t0)) s"
  chk suite limits "$lim_res" || fail "$CUR: $mode"
  grep -o '"id":"limits/[a-z_]*","status":"[a-z]*"' "$lim_res" | sed 's/^/    /'
done
# a quota overrun ends within seconds even from a cold run of the binary (wall time of the hostile tests alone)
run "$out/bin.log" build --target-platforms ${PLAT}release "$pkg/limits:t" --show-output || fail "$CUR" "$out/bin.log"
lim_bin="$root/$(out_of "$out/bin.log" t)"
limdir="$(mktemp -d)"
t0=$(date +%s.%N)
( cd "$limdir" && "$lim_bin" --seed 1 --out "$out/lim.local.jsonl" >/dev/null 2>&1 )
t1=$(date +%s.%N)
echo "  local run of the whole limits suite (all seven tests): $(python3 -c "print(round($t1-$t0,2))") s"
python3 -c "import sys; sys.exit(0 if $t1-$t0 < 20 else 1)" || fail "$CUR: the limits suite took 20 s or more"
leftover="$(ls -A "${TMPDIR:-/tmp}" | grep -c '^ctest\.' || true)"
[ "$leftover" = 0 ] || fail "$CUR: $leftover ctest.* scratch directories left in ${TMPDIR:-/tmp}"
rm -rf "$limdir"

begin "san: heap overflow, use-after-free, UBSan overflow, leak and SIGSEGV are fails naming file:line function (RE, hermetic llvm-symbolizer)"
build_out san_res san "$pkg/san:t_results"
san_report="$(dirname "$san_res")/san_report.txt"
[ -s "$san_report" ] || fail "$CUR: no san_report.txt next to the results"
chk san "$san_res" "$san_report" "$scratch/san/t.c" || fail "$CUR"
run "$out/sub.log" build --target-platforms ${PLAT}san "$pkg/san:t_results[san_report]" --show-output || fail "$CUR: sub-target t_results[san_report]" "$out/sub.log"
sub="$(awk '/buck-out/ {print $2}' "$out/sub.log" | tail -1)"
cmp -s "$sub" "$san_report" || fail "$CUR: t_results[san_report] is not the report"

begin "san: two cold runs (a fresh action key each; ASLR and addresses differ) give byte-identical results and report"
cp "$san_res" "$out/san.1.jsonl"; cp "$san_report" "$out/san.1.txt"
printf 'const char ctest_scratch_nonce_a[] = "%s";\n' "$(date +%s%N)-$$" >> "$scratch/san/t.c"
build_out san_res2 san "$pkg/san:t_results"
"${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -q 'ctest_results' || fail "$CUR: the second cold run did not execute the results action"
cp "$san_res2" "$out/san.2.jsonl"; cp "$(dirname "$san_res2")/san_report.txt" "$out/san.2.txt"
chk same "$out/san.1.jsonl" "$out/san.2.jsonl" || fail "$CUR: results differ between cold runs"
chk same "$out/san.1.txt" "$out/san.2.txt" || fail "$CUR: san report differs between cold runs"
echo "  cold/cold: results.jsonl and san_report.txt byte-identical"

begin "san: a warm rebuild executes 0 actions"
must_pass build --target-platforms ${PLAT}san "$pkg/san:t_results"
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the warm san build"
echo "  warm san build: $n actions executed"

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
for m in cov fuzz; do
  if run "$out/inc.log" build --target-platforms ${PLAT}$m //examples/hello:hello_test_results; then fail "$CUR: results built in $m" "$out/inc.log"; fi
  grep -q "is incompatible with" "$out/inc.log" || fail "$CUR: $m failed for the wrong reason" "$out/inc.log"
done
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
# Only the fresh-nonce actions (the order package and its results) must have run on RE; unchanged dependencies (toolchain, ctest, other
# facts) may legitimately be cache hits, depending on farm and daemon history. Nothing may run locally.
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' 'NF>=3 && $2 ~ /scratch_ctest\/order:|ctest_results/ && $3 !~ /^re\(/ {bad=1} END{exit !bad}'; then
  fail "$CUR: a fresh-nonce action did not run on RE" "$out/whatran.txt"
fi
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' 'NF>=3 && $3 !~ /^(re\(|cache)/ {bad=1} END{exit !bad}'; then
  fail "$CUR: an action ran locally or on an unknown executor" "$out/whatran.txt"
fi
grep 'ctest_results' "$out/whatran.txt" | head -3

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
