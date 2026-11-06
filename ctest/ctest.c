/* ctest runtime. See ctest.h. Fork per test; the child reports its counts over a pipe. */
#define _GNU_SOURCE
#include "ctest.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <sys/mman.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
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
    TIMEOUT_S = 10 /* fixed; deliberately not configurable by a test file */
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
static int write_out(const char *path) {
    int fd = STDOUT_FILENO;
    int rc;
    if (path != NULL) {
        fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
        if (fd < 0) {
            return -1;
        }
    }
    rc = write_all(fd, g_out, g_out_len);
    if (path != NULL && close(fd) != 0) {
        rc = -1;
    }
    return rc;
}

/* ------------------------------------------------------------------ running one test */

static void child_main(const ctest_case_t *c) {
    if (setpgid(0, 0) != 0 || dup2(2, 1) < 0) {
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

/* Waits for the child to be reaped until the deadline. 0 = reaped, 1 = timeout, -1 = error. */
static int wait_child(pid_t pid, int64_t deadline, int *status) {
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

/* 0 = result filled in, -1 = framework error. The child inherits no descriptor of ours. */
static int run_one(const ctest_case_t *c, result_t *res) {
    int status = 0;
    int wt;
    pid_t pid;
    int64_t deadline = now_ms() + (int64_t)TIMEOUT_S * 1000;
    memset(g_rep, 0, sizeof *g_rep);
    pid = fork();
    if (pid < 0) {
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
    if (wt < 0) {
        return -1;
    }
    if (wt == 1) {
        timed_out(res);
    } else {
        classify(status, res);
    }
    return 0;
}

/* ------------------------------------------------------------------ startup */

typedef struct {
    uint64_t seed;
    const char *out;
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
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc && !seen_seed) {
            seen_seed = 1;
            if (parse_u64(argv[++i], &o->seed) != 0) {
                return -1;
            }
        } else if (strcmp(argv[i], "--out") == 0 && i + 1 < argc && o->out == NULL) {
            o->out = argv[++i];
        } else {
            return -1;
        }
    }
    return 0;
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
        if (run_one(c, &g_res) != 0 || emit_result(suite, c->name, &g_res) != 0) {
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
        (void)fputs("ctest: usage: <binary> [--seed N] [--out FILE]; or invalid suite\n", stderr);
        return 2;
    }
    if (getrandom(&g_nonce, sizeof g_nonce, 0) != (ssize_t)sizeof g_nonce) {
        return 2;
    }
    g_rep = mmap(NULL, sizeof *g_rep, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_rep == MAP_FAILED) {
        return 2;
    }
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
