/* ctest runtime. See ctest.h. Fork per test; the child reports its counts over a pipe. */
#define _GNU_SOURCE
#include "ctest.h"
#include "sanlog.h"
#include "traps.h"

#include <errno.h>
#include <ftw.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <sys/mman.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

enum {
    MSG_CAP = 256,
    REASON_CAP = 512,
    LINE_CAP = 2048,
    OUT_CAP = 1 << 20, /* all result lines; overflow is a framework error */
    MAX_TESTS = 512,
    NAME_CAP = 64,
    TIMEOUT_S = 10, /* fixed; deliberately not configurable by a test file */
    SAN_TEXT_CAP = 1 << 16, /* one test's sanitizer log; longer logs are cut */
    SAN_REPORT_CAP = 1 << 20,
    SAN_SUM_CAP = 200,
    /* Hard resource limits (T097): the same in every mode. See docs/ctest.md "Resource limits". */
    LIM_FSIZE = 64 << 20,   /* RLIMIT_FSIZE: one file; a write past it fails with EFBIG (SIGXFSZ is ignored) */
    LIM_CPU_CHILD_S = 20,   /* RLIMIT_CPU per test process: twice the wall timeout, so 2 busy threads still pass */
    LIM_CPU_PARENT_S = 600, /* RLIMIT_CPU of the runner itself, which only waits */
    LIM_NOFILE = 256,       /* RLIMIT_NOFILE */
    SCRATCH_BYTES = 256 << 20, /* total bytes (apparent size) under one test's private $TMPDIR */
    SCRATCH_ENTRIES = 4096,    /* total entries under it */
    SCRATCH_PATH_CAP = 4096,
    SCRATCH_POLL_MS = 20,
    SCRUB_FRAMES = 64 /* x 256 bytes */
};
#define REPORT_MAGIC 0x43544531U

struct ctest {
    uint64_t asserts;
    uint64_t failed;
    char msg[MSG_CAP]; /* first failure */
};

/* What a child sends to the parent once, after the test function returned. */
typedef struct {
    uint32_t magic;
    uint64_t nonce; /* known to this process image only; a forged report needs it */
    uint64_t asserts;
    uint64_t failed;
    char msg[MSG_CAP];
} report_t;

typedef struct {
    int pass;
    uint64_t asserts;
    char reason[REASON_CAP];
} result_t;

static ctest_t g_t;
static uint64_t g_nonce;
static report_t *g_rep; /* anonymous shared page: the child reports through memory, so no descriptor reaches a test */
static char g_out[OUT_CAP];
static size_t g_out_len;
static result_t g_res;
static char g_line[LINE_CAP];
static size_t g_order[MAX_TESTS];
static const char *g_san_log;    /* --san-log: prefix of the sanitizer log files (<prefix>.<pid>) */
static const char *g_san_report; /* --san-report: where the normalized logs of failing tests go */
static char g_san_text[SAN_TEXT_CAP];
static char g_san_sum[SAN_SUM_CAP]; /* static: keeps the stack frames of the inlined helpers small */
static char g_san_head[2 * NAME_CAP + 16];
static char g_san_out[SAN_REPORT_CAP];
static size_t g_san_out_len;
static char g_scratch[SCRATCH_PATH_CAP]; /* this test's private $TMPDIR; empty = none */
static uint64_t g_scratch_bytes;
static uint64_t g_scratch_entries;

/* ------------------------------------------------------------------ checks (run in the child) */

static void note_fail(ctest_t *t, const char *file, int line, const char *detail) {
    if (t == NULL) {
        abort();
    }
    if (t->failed == 0) {
        (void)snprintf(t->msg, sizeof t->msg, "%s:%d: %s", file, line, detail);
    }
    t->failed++;
}

static void count(ctest_t *t) {
    if (t == NULL) {
        abort();
    }
    t->asserts++;
}

void ctest_check(ctest_t *t, int ok, const char *file, int line, const char *expr) {
    char d[160];
    count(t);
    if (!ok) {
        (void)snprintf(d, sizeof d, "CHECK(%s)", expr);
        note_fail(t, file, line, d);
    }
}

void ctest_check_traps(ctest_t *t, int ok, const char *file, int line, const char *expr, const char *why) {
    char d[240];
    count(t);
    if (!ok) {
        (void)snprintf(d, sizeof d, "CHECK_TRAPS(%.60s): %s", expr, why);
        note_fail(t, file, line, d);
    }
}

void ctest_check_i64(ctest_t *t, int64_t a, int64_t b, const char *file, int line, const char *ea,
                     const char *eb) {
    char d[200];
    count(t);
    if (a != b) {
        (void)snprintf(d, sizeof d, "CHECK_EQ_I64(%s, %s): %" PRId64 " != %" PRId64, ea, eb, a, b);
        note_fail(t, file, line, d);
    }
}

void ctest_check_u64(ctest_t *t, uint64_t a, uint64_t b, const char *file, int line, const char *ea,
                     const char *eb) {
    char d[200];
    count(t);
    if (a != b) {
        (void)snprintf(d, sizeof d, "CHECK_EQ_U64(%s, %s): %" PRIu64 " != %" PRIu64, ea, eb, a, b);
        note_fail(t, file, line, d);
    }
}

static void show_str(char *dst, size_t cap, const char *s) {
    if (s == NULL) {
        (void)snprintf(dst, cap, "(null)");
    } else {
        (void)snprintf(dst, cap, "\"%s\"", s);
    }
}

void ctest_check_str(ctest_t *t, const char *a, const char *b, const char *file, int line,
                     const char *ea, const char *eb) {
    char d[200];
    char sa[48];
    char sb[48];
    int same;
    count(t);
    same = (a == NULL || b == NULL) ? (a == b) : (strcmp(a, b) == 0);
    if (!same) {
        show_str(sa, sizeof sa, a);
        show_str(sb, sizeof sb, b);
        (void)snprintf(d, sizeof d, "CHECK_EQ_STR(%s, %s): %s != %s", ea, eb, sa, sb);
        note_fail(t, file, line, d);
    }
}

void ctest_check_mem(ctest_t *t, const void *a, size_t alen, const void *b, size_t blen,
                     const char *file, int line, const char *ea, const char *eb) {
    char d[200];
    size_t i = 0;
    const unsigned char *pa = a;
    const unsigned char *pb = b;
    count(t);
    if (alen != blen) {
        (void)snprintf(d, sizeof d, "CHECK_EQ_MEM(%s, %s): lengths %zu != %zu", ea, eb, alen, blen);
        note_fail(t, file, line, d);
        return;
    }
    if (alen == 0) {
        return;
    }
    if (pa == NULL || pb == NULL) {
        (void)snprintf(d, sizeof d, "CHECK_EQ_MEM(%s, %s): null pointer", ea, eb);
        note_fail(t, file, line, d);
        return;
    }
    while (i < alen && pa[i] == pb[i]) {
        i++;
    }
    if (i < alen) {
        (void)snprintf(d, sizeof d, "CHECK_EQ_MEM(%s, %s): first difference at offset %zu", ea, eb, i);
        note_fail(t, file, line, d);
    }
}

/* ------------------------------------------------------------------ small io helpers */

static int write_all(int fd, const void *buf, size_t len) {
    const char *p = buf;
    while (len > 0) {
        ssize_t n = write(fd, p, len);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        p += n;
        len -= (size_t)n;
    }
    return 0;
}

static int64_t now_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return -1;
    }
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* ------------------------------------------------------------------ JSON line building */

typedef struct {
    size_t len;
    int bad;
} line_t;

static void put(line_t *l, const char *s, size_t n) {
    if (l->bad || l->len + n >= sizeof g_line) {
        l->bad = 1;
        return;
    }
    memcpy(g_line + l->len, s, n);
    l->len += n;
}

static void put_str(line_t *l, const char *s) {
    put(l, s, strlen(s));
}

static void put_esc(line_t *l, const char *s) {
    static const char hex[] = "0123456789abcdef";
    for (; *s != '\0'; s++) {
        unsigned char c = (unsigned char)*s;
        char u[6] = {'\\', 'u', '0', '0', hex[c >> 4], hex[c & 15U]};
        if (c == '"' || c == '\\') {
            char e[2] = {'\\', (char)c};
            put(l, e, 2);
        } else if (c == '\n' || c == '\r' || c == '\t') {
            char e[2] = {'\\', c == '\n' ? 'n' : (c == '\r' ? 'r' : 't')};
            put(l, e, 2);
        } else if (c < 0x20 || c >= 0x7f) {
            put(l, u, sizeof u);
        } else {
            put(l, s, 1);
        }
    }
}

static void put_u64(line_t *l, uint64_t v) {
    char b[24];
    int n = snprintf(b, sizeof b, "%" PRIu64, v);
    if (n < 0) {
        l->bad = 1;
        return;
    }
    put(l, b, (size_t)n);
}

static int keep_line(const line_t *l) {
    if (l->bad || g_out_len + l->len > sizeof g_out) {
        return -1;
    }
    memcpy(g_out + g_out_len, g_line, l->len);
    g_out_len += l->len;
    return 0;
}

static int emit_result(const char *suite, const char *name, const result_t *r) {
    line_t l = {0, 0};
    put_str(&l, "{\"id\":\"");
    put_esc(&l, suite);
    put_str(&l, "/");
    put_esc(&l, name);
    put_str(&l, r->pass ? "\",\"status\":\"pass\",\"asserts\":" : "\",\"status\":\"fail\",\"asserts\":");
    put_u64(&l, r->asserts);
    put_str(&l, ",\"reason\":\"");
    put_esc(&l, r->reason);
    put_str(&l, "\"}\n");
    return keep_line(&l);
}

static int emit_summary(size_t total, size_t passed) {
    line_t l = {0, 0};
    put_str(&l, "{\"summary\":{\"total\":");
    put_u64(&l, total);
    put_str(&l, ",\"passed\":");
    put_u64(&l, passed);
    put_str(&l, "}}\n");
    return keep_line(&l);
}

/* The results file is opened only here, after every test child is gone, so no test can hold it. */
static int write_file(const char *path, const char *buf, size_t len) {
    int fd = STDOUT_FILENO;
    int rc;
    if (path != NULL) {
        fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
        if (fd < 0) {
            return -1;
        }
    }
    rc = write_all(fd, buf, len);
    if (path != NULL && close(fd) != 0) {
        rc = -1;
    }
    return rc;
}

static int write_out(const char *path) {
    if (write_file(path, g_out, g_out_len) != 0) {
        return -1;
    }
    return g_san_report == NULL ? 0 : write_file(g_san_report, g_san_out, g_san_out_len);
}

/* ------------------------------------------------------------------ running one test */

static int set_limit(__rlimit_resource_t what, rlim_t v) {
    struct rlimit rl;
    rl.rlim_cur = v;
    rl.rlim_max = v;
    return setrlimit(what, &rl);
}

/* ------------------------------------------------------------------ scratch quota (T097) */

static int scratch_visit(const char *path, const struct stat *sb, int type, struct FTW *f) {
    (void)path;
    (void)f;
    (void)type;
    g_scratch_entries++;
    g_scratch_bytes += (uint64_t)sb->st_size;
    return 0;
}

/* 1 when the test's private $TMPDIR holds more than the quota. */
static int scratch_over(void) {
    if (g_scratch[0] == '\0') {
        return 0;
    }
    g_scratch_bytes = 0;
    g_scratch_entries = 0;
    (void)nftw(g_scratch, scratch_visit, 16, FTW_PHYS);
    return g_scratch_bytes > (uint64_t)SCRATCH_BYTES || g_scratch_entries > (uint64_t)SCRATCH_ENTRIES;
}

static int scratch_remove_one(const char *path, const struct stat *sb, int type, struct FTW *f) {
    (void)sb;
    (void)type;
    (void)f;
    return remove(path);
}

static void scratch_make(void) {
    const char *base = getenv("TMPDIR");
    int n;
    g_scratch[0] = '\0';
    if (base == NULL || base[0] == '\0') {
        base = "/tmp";
    }
    n = snprintf(g_scratch, sizeof g_scratch, "%s/ctest.XXXXXX", base);
    if (n < 0 || (size_t)n >= sizeof g_scratch || mkdtemp(g_scratch) == NULL) {
        g_scratch[0] = '\0'; /* no quota; RLIMIT_FSIZE still applies */
    }
}

/* Overwrites the stack below the caller. mkdtemp and nftw leave random directory names (and pids) in dead stack
 * slots; a test (or a mutant) that reads an uninitialised local would see them, so its verdict would change from
 * run to run. After the scrub the dead slots hold zeros, the same every time. */
static void scrub_stack(int depth) {
    volatile char pad[256];
    for (size_t i = 0; i < sizeof pad; i++) {
        pad[i] = 0;
    }
    if (depth > 0) {
        scrub_stack(depth - 1);
    }
    pad[0] = 0;
}

static void scratch_drop(void) {
    if (g_scratch[0] != '\0') {
        (void)nftw(g_scratch, scratch_remove_one, 16, FTW_DEPTH | FTW_PHYS);
        g_scratch[0] = '\0';
    }
}

static void child_main(const ctest_case_t *c) {
    if (setpgid(0, 0) != 0 || dup2(2, 1) < 0) {
        _exit(4);
    }
    if (set_limit(RLIMIT_CPU, LIM_CPU_CHILD_S) != 0) {
        _exit(4);
    }
    if (g_scratch[0] != '\0' && setenv("TMPDIR", g_scratch, 1) != 0) {
        _exit(4);
    }
    c->fn(&g_t); /* a test that exits or crashes never reaches the report below */
    g_rep->nonce = g_nonce;
    g_rep->asserts = g_t.asserts;
    g_rep->failed = g_t.failed;
    memcpy(g_rep->msg, g_t.msg, sizeof g_rep->msg);
    g_rep->magic = REPORT_MAGIC; /* last: a half-written report has no magic */
    exit(0); /* not _exit: runs atexit, so the leak sanitizer can still fail the test */
}

/* Waits for the child to be reaped until the deadline. 0 = reaped, 1 = timeout, 2 = scratch quota exceeded, -1 = error. */
static int wait_child(pid_t pid, int64_t deadline, int *status) {
    int64_t next_scratch = 0;
    for (;;) {
        pid_t r = waitpid(pid, status, WNOHANG);
        int64_t now;
        if (r == pid) {
            return 0;
        }
        if (r < 0 && errno != EINTR) {
            return -1;
        }
        now = now_ms();
        if (now < 0) {
            return -1;
        }
        if (now >= deadline) {
            return 1;
        }
        if (now >= next_scratch) {
            next_scratch = now + SCRATCH_POLL_MS;
            if (scratch_over()) {
                return 2;
            }
        }
        (void)poll(NULL, 0, 1); /* bounded 1 ms wait between reaping attempts */
    }
}

static void kill_tree(pid_t pid) {
    if ((kill(-pid, SIGKILL) != 0 && errno != ESRCH) || (kill(pid, SIGKILL) != 0 && errno != ESRCH)) {
        abort();
    }
}

static void fail_with(result_t *res, uint64_t asserts) {
    res->pass = 0;
    res->asserts = asserts;
}

static void classify(int status, result_t *res) {
    report_t r;
    memset(res, 0, sizeof *res);
    memcpy(&r, g_rep, sizeof r);
    if (WIFSIGNALED(status)) {
        fail_with(res, 0);
        (void)snprintf(res->reason, sizeof res->reason, "killed by signal %d", WTERMSIG(status));
        return;
    }
    if (r.magic == 0) {
        fail_with(res, 0);
        if (WEXITSTATUS(status) == 0) {
            (void)snprintf(res->reason, sizeof res->reason,
                           "exited without reporting (exit() or _exit() before the test returned)");
        } else {
            (void)snprintf(res->reason, sizeof res->reason, "exited with status %d before reporting",
                           WEXITSTATUS(status));
        }
        return;
    }
    if (r.magic != REPORT_MAGIC || r.nonce != g_nonce) {
        fail_with(res, 0);
        (void)snprintf(res->reason, sizeof res->reason, "invalid report from the test process");
        return;
    }
    r.msg[MSG_CAP - 1] = '\0';
    fail_with(res, r.asserts);
    if (WEXITSTATUS(status) != 0) {
        (void)snprintf(res->reason, sizeof res->reason, "exited with status %d after reporting", WEXITSTATUS(status));
    } else if (r.failed > 0) {
        (void)snprintf(res->reason, sizeof res->reason, "%" PRIu64 " of %" PRIu64 " checks failed; first: %s",
                       r.failed, r.asserts, r.msg);
    } else if (r.asserts == 0) {
        (void)snprintf(res->reason, sizeof res->reason, "no checks executed");
    } else {
        res->pass = 1;
    }
}

static void timed_out(result_t *res) {
    memset(res, 0, sizeof *res);
    fail_with(res, 0);
    (void)snprintf(res->reason, sizeof res->reason, "timeout after %d s", TIMEOUT_S);
}

static void over_quota(result_t *res) {
    memset(res, 0, sizeof *res);
    fail_with(res, 0);
    (void)snprintf(res->reason, sizeof res->reason, "scratch quota exceeded (limit %d MiB, %d entries under $TMPDIR)",
                   SCRATCH_BYTES >> 20, SCRATCH_ENTRIES);
}

static void keep_san_text(const char *suite, const char *name, size_t n) {
    int h = snprintf(g_san_head, sizeof g_san_head, "== %s/%s ==\n", suite, name);
    if (h < 0 || g_san_out_len + (size_t)h + n >= sizeof g_san_out) {
        static const char cut[] = "[san report truncated]\n";
        if (g_san_out_len + sizeof cut < sizeof g_san_out) {
            memcpy(g_san_out + g_san_out_len, cut, sizeof cut - 1);
            g_san_out_len += sizeof cut - 1;
        }
        return;
    }
    memcpy(g_san_out + g_san_out_len, g_san_head, (size_t)h);
    memcpy(g_san_out + g_san_out_len + (size_t)h, g_san_text, n);
    g_san_out_len += (size_t)h + n;
}

/* The child's sanitizer log (if any) only ever adds information or turns a pass into a fail. */
static void apply_san(const char *suite, const char *name, pid_t pid, result_t *res) {
    size_t used;
    size_t n = sanlog_take(g_san_log, (long)pid, g_san_text, sizeof g_san_text);
    if (n == 0) {
        return;
    }
    n = sanlog_normalize(g_san_text, n);
    sanlog_summary(g_san_text, n, g_san_sum, sizeof g_san_sum);
    keep_san_text(suite, name, n);
    if (res->pass) {
        res->pass = 0;
        (void)snprintf(res->reason, sizeof res->reason, "sanitizer report in a test that looked passing: %s", g_san_sum);
        return;
    }
    used = strlen(res->reason);
    (void)snprintf(res->reason + used, sizeof res->reason - used, "; %s", g_san_sum);
}

/* 0 = result filled in, -1 = framework error. The child inherits no descriptor of ours. */
static int run_one(const char *suite, const ctest_case_t *c, result_t *res) {
    int status = 0;
    int wt;
    pid_t pid;
    int64_t deadline = now_ms() + (int64_t)TIMEOUT_S * 1000;
    memset(g_rep, 0, sizeof *g_rep);
    scratch_make();
    scrub_stack(SCRUB_FRAMES);
    pid = fork();
    if (pid < 0) {
        scratch_drop();
        return -1;
    }
    if (pid == 0) {
        child_main(c);
    }
    wt = wait_child(pid, deadline, &status);
    if (wt != 0) {
        kill_tree(pid);
        while (waitpid(pid, &status, 0) != pid) {
            if (errno != EINTR) {
                return -1;
            }
        }
    }
    kill_tree(pid); /* stragglers the test left in its process group */
    scratch_drop();
    if (wt < 0) {
        return -1;
    }
    if (wt == 1) {
        timed_out(res);
    } else if (wt == 2) {
        over_quota(res);
    } else {
        classify(status, res);
    }
    if (g_san_log != NULL) {
        apply_san(suite, c->name, pid, res);
    }
    return 0;
}

/* ------------------------------------------------------------------ startup */

typedef struct {
    uint64_t seed;
    const char *out;
    const char *san_log;
    const char *san_report;
} opts_t;

static int parse_u64(const char *s, uint64_t *v) {
    char *end = NULL;
    unsigned long long x;
    if (s[0] < '0' || s[0] > '9') {
        return -1;
    }
    errno = 0;
    x = strtoull(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0') {
        return -1;
    }
    *v = x;
    return 0;
}

static int parse_args(int argc, char **argv, opts_t *o) {
    int seen_seed = 0;
    o->seed = 1;
    o->out = NULL;
    o->san_log = NULL;
    o->san_report = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc && !seen_seed) {
            seen_seed = 1;
            if (parse_u64(argv[++i], &o->seed) != 0) {
                return -1;
            }
        } else if (strcmp(argv[i], "--out") == 0 && i + 1 < argc && o->out == NULL) {
            o->out = argv[++i];
        } else if (strcmp(argv[i], "--san-log") == 0 && i + 1 < argc && o->san_log == NULL) {
            o->san_log = argv[++i];
        } else if (strcmp(argv[i], "--san-report") == 0 && i + 1 < argc && o->san_report == NULL) {
            o->san_report = argv[++i];
        } else {
            return -1;
        }
    }
    return (o->san_log == NULL) == (o->san_report == NULL) ? 0 : -1; /* only together */
}

static int valid_name(const char *s) {
    size_t n = s == NULL ? 0 : strlen(s);
    if (n == 0 || n > NAME_CAP) {
        return 0;
    }
    for (size_t i = 0; i < n; i++) {
        if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= '0' && s[i] <= '9') || s[i] == '_')) {
            return 0;
        }
    }
    return 1;
}

static int validate(const char *suite, const ctest_case_t *cases, size_t n) {
    if (!valid_name(suite) || cases == NULL || n == 0 || n > MAX_TESTS) {
        return -1;
    }
    for (size_t i = 0; i < n; i++) {
        if (!valid_name(cases[i].name) || cases[i].fn == NULL) {
            return -1;
        }
        for (size_t j = 0; j < i; j++) {
            if (strcmp(cases[i].name, cases[j].name) == 0) {
                return -1;
            }
        }
    }
    return 0;
}

static uint64_t splitmix64(uint64_t *state) {
    uint64_t z;
    *state += 0x9E3779B97F4A7C15ULL;
    z = *state;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static void shuffle(size_t n, uint64_t seed) {
    uint64_t state = seed;
    for (size_t i = 0; i < n; i++) {
        g_order[i] = i;
    }
    for (size_t i = n - 1; i > 0; i--) {
        size_t j = (size_t)(splitmix64(&state) % (uint64_t)(i + 1));
        size_t tmp = g_order[i];
        g_order[i] = g_order[j];
        g_order[j] = tmp;
    }
}

static int run_all(const char *suite, const ctest_case_t *cases, size_t n, size_t *passed) {
    *passed = 0;
    for (size_t i = 0; i < n; i++) {
        const ctest_case_t *c = &cases[g_order[i]];
        if (run_one(suite, c, &g_res) != 0 || emit_result(suite, c->name, &g_res) != 0) {
            return -1;
        }
        *passed += g_res.pass ? 1U : 0U;
    }
    return emit_summary(n, *passed);
}

int ctest_run(int argc, char **argv, const char *suite, const ctest_case_t *cases, size_t n) {
    opts_t o;
    int rc;
    size_t passed = 0;
    if (parse_args(argc, argv, &o) != 0 || validate(suite, cases, n) != 0) {
        (void)fputs("ctest: usage: <binary> [--seed N] [--out FILE] [--san-log PREFIX --san-report FILE]; or invalid suite\n", stderr);
        return 2;
    }
    if (getrandom(&g_nonce, sizeof g_nonce, 0) != (ssize_t)sizeof g_nonce) {
        return 2;
    }
    /* Hard limits before any test runs; every test process inherits them. SIGXFSZ is ignored so a write
     * past RLIMIT_FSIZE fails with EFBIG and the test's own check fails, instead of killing the process. */
    if (signal(SIGXFSZ, SIG_IGN) == SIG_ERR || set_limit(RLIMIT_FSIZE, LIM_FSIZE) != 0 ||
        set_limit(RLIMIT_CPU, LIM_CPU_PARENT_S) != 0 || set_limit(RLIMIT_NOFILE, LIM_NOFILE) != 0 ||
        set_limit(RLIMIT_CORE, 0) != 0) {
        (void)fputs("ctest: cannot set resource limits\n", stderr);
        return 2;
    }
    g_rep = mmap(NULL, sizeof *g_rep, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_rep == MAP_FAILED) {
        return 2;
    }
    g_san_log = o.san_log;
    ctest_traps_set_san_log(o.san_log);
    g_san_report = o.san_report;
    shuffle(n, o.seed);
    rc = run_all(suite, cases, n, &passed);
    if (rc == 0) {
        rc = write_out(o.out);
    }
    if (rc != 0) {
        (void)fputs("ctest: framework error\n", stderr);
        return 2;
    }
    return passed == n ? 0 : 1;
}
