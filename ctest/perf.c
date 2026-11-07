/* perf harness. See ctest/perf.h and docs/perf.md. */
#define _GNU_SOURCE
#include "ctest/perf.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include <linux/perf_event.h>

#define REPS 7
#define GUARD 64
#define TIMEOUT_S 100
#define MAX_SIZES 8

/* ---- libc bulk-byte counters: the rule links with -Wl,--wrap=<each of these> ---- */
void *__real_memcpy(void *d, const void *s, size_t n);
void *__real_memmove(void *d, const void *s, size_t n);
void *__real_memset(void *d, int c, size_t n);
int __real_memcmp(const void *a, const void *b, size_t n);
size_t __real_strlen(const char *s);
size_t __real_strnlen(const char *s, size_t n);

static int g_on;
static uint64_t g_bytes;

void *__wrap_memcpy(void *d, const void *s, size_t n) {
    if (g_on) { g_bytes += n; }
    return __real_memcpy(d, s, n);
}
void *__wrap_memmove(void *d, const void *s, size_t n) {
    if (g_on) { g_bytes += n; }
    return __real_memmove(d, s, n);
}
void *__wrap_memset(void *d, int c, size_t n) {
    if (g_on) { g_bytes += n; }
    return __real_memset(d, c, n);
}
int __wrap_memcmp(const void *a, const void *b, size_t n) {
    if (g_on) { g_bytes += n; }
    return __real_memcmp(a, b, n);
}
size_t __wrap_strlen(const char *s) {
    size_t r = __real_strlen(s);
    if (g_on) { g_bytes += r; }
    return r;
}
size_t __wrap_strnlen(const char *s, size_t n) {
    size_t r = __real_strnlen(s, n);
    if (g_on) { g_bytes += r; }
    return r;
}

/* ---- measurement of one size, in a forked child ---- */
enum { ST_OK = 0, ST_GEN_OVERFLOW = 1, ST_RUN_ERROR = 2 };

typedef struct {
    int status;
    int counter_ok; /* 1: instructions valid */
    int counter_errno;
    int multiplexed;
    int measured; /* the counter was attempted */
    uint64_t len, instructions, bytes, result, wall_median;
} rec_t;

static char g_in[PERF_INPUT_CAP + GUARD];

static uint64_t now_ns(void) {
    struct timespec t;
    (void)clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000u + (uint64_t)t.tv_nsec;
}

static int open_counter(void) {
    struct perf_event_attr a;
    (void)memset(&a, 0, sizeof a);
    a.type = PERF_TYPE_HARDWARE;
    a.size = sizeof a;
    a.config = PERF_COUNT_HW_INSTRUCTIONS;
    a.disabled = 1;
    a.exclude_kernel = 1;
    a.exclude_hv = 1;
    a.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
    return (int)syscall(SYS_perf_event_open, &a, 0, -1, -1, 0);
}

static void sort7(uint64_t *v) {
    for (int i = 1; i < REPS; i++) {
        uint64_t x = v[i];
        int j = i - 1;
        while (j >= 0 && v[j] > x) { v[j + 1] = v[j]; j--; }
        v[j + 1] = x;
    }
}

static int generate(rec_t *r, uint64_t seed, size_t n) {
    (void)memset(g_in + PERF_INPUT_CAP, 0xA5, GUARD);
    r->len = perf_gen(seed, n, g_in, PERF_INPUT_CAP);
    for (int i = 0; i < GUARD; i++) {
        if ((unsigned char)g_in[PERF_INPUT_CAP + (size_t)i] != 0xA5u) { r->len = PERF_ERR; }
    }
    if (r->len > PERF_INPUT_CAP) { r->status = ST_GEN_OVERFLOW; return 0; }
    return 1;
}

typedef struct { uint64_t instr, bytes, wall, result; int counter_errno, multiplexed; } rep_t;

/* One counted perf_run. The counter is read right after the run; any problem is recorded in the rep. */
static void one_rep(int fd, rep_t *p, uint64_t len) {
    uint64_t rd[3] = {0, 0, 0};
    uint64_t t0 = now_ns();
    if (fd >= 0) { (void)ioctl(fd, PERF_EVENT_IOC_RESET, 0); (void)ioctl(fd, PERF_EVENT_IOC_ENABLE, 0); }
    g_bytes = 0;
    g_on = 1;
    p->result = perf_run(g_in, (size_t)len);
    g_on = 0;
    if (fd >= 0) { (void)ioctl(fd, PERF_EVENT_IOC_DISABLE, 0); }
    p->wall = now_ns() - t0;
    p->bytes = g_bytes;
    if (fd < 0) { return; }
    if (read(fd, rd, sizeof rd) != (ssize_t)sizeof rd) { p->counter_errno = EIO; }
    else if (rd[1] != rd[2] || rd[1] == 0) { p->multiplexed = 1; }
    else { p->instr = rd[0]; }
}

/* The record holds the median of REPS counted runs, each with its own counter window. Rep 0 is cold
 * (lazy symbol binding, first page touches: ~1.5e3 more instructions) and is therefore never the median;
 * the warm reps differ by at most 1 (counter skid). The median is robust to both. */
static void measure(rec_t *r, uint64_t seed, size_t n) {
    rep_t reps[REPS];
    uint64_t v[REPS];
    int fd;
    int bad = 0;
    int nreps = 0;
    if (!generate(r, seed, n)) { return; }
    fd = open_counter();
    r->counter_errno = fd < 0 ? errno : 0;
    (void)memset(reps, 0, sizeof reps);
    for (; nreps < REPS; nreps++) {
        one_rep(fd, &reps[nreps], r->len);
        if (reps[nreps].result == PERF_ERR) { r->status = ST_RUN_ERROR; r->result = PERF_ERR; nreps++; break; }
    }
    if (fd >= 0) { (void)close(fd); }
    for (int i = 0; i < nreps; i++) {
        if (reps[i].counter_errno != 0) { r->counter_errno = reps[i].counter_errno; bad = 1; }
        if (reps[i].multiplexed) { r->multiplexed = 1; bad = 1; }
    }
    r->counter_ok = fd >= 0 && !bad;
    r->measured = 1;
    if (r->status != ST_OK) { return; }
    r->result = reps[0].result;
    for (int i = 0; i < REPS; i++) { v[i] = reps[i].instr; }
    sort7(v);
    r->instructions = v[REPS / 2];
    for (int i = 0; i < REPS; i++) { v[i] = reps[i].bytes; }
    sort7(v);
    r->bytes = v[REPS / 2];
    for (int i = 0; i < REPS; i++) { v[i] = reps[i].wall; }
    sort7(v);
    r->wall_median = v[REPS / 2];
}

static int child_main(int wfd, uint64_t seed, size_t n) {
    rec_t r;
    (void)memset(&r, 0, sizeof r);
    (void)alarm(TIMEOUT_S);
    measure(&r, seed, n);
    return write(wfd, &r, sizeof r) == (ssize_t)sizeof r ? 0 : 3;
}

/* ---- records ---- */
typedef struct { const char *name; uint64_t seed; FILE *out; } ctx_t;

static void emit(const ctx_t *c, size_t n, const char *status, const rec_t *r, int sig, int code) {
    (void)fprintf(c->out, "{\"name\":\"%s\",\"seed\":%llu,\"n\":%zu,\"status\":\"%s\"", c->name,
                  (unsigned long long)c->seed, n, status);
    if (sig != 0) { (void)fprintf(c->out, ",\"signal\":%d", sig); }
    if (code != 0) { (void)fprintf(c->out, ",\"exit_code\":%d", code); }
    if (r != NULL && (!r->measured || r->status != ST_OK)) {
        /* No counts: a status without numbers, never a silent zero. */
        (void)fprintf(c->out, ",\"input_len\":%llu", (unsigned long long)(r->len == PERF_ERR ? 0 : r->len));
    } else if (r != NULL) {
        if (r->counter_ok) { (void)fprintf(c->out, ",\"counter\":\"perf_event_open\",\"errno\":0"); }
        else { (void)fprintf(c->out, ",\"counter\":\"unavailable\",\"errno\":%d%s", r->counter_errno, r->multiplexed ? ",\"why\":\"multiplexed\"" : ""); }
        (void)fprintf(c->out, ",\"input_len\":%llu", (unsigned long long)(r->len == PERF_ERR ? 0 : r->len));
        if (r->counter_ok) { (void)fprintf(c->out, ",\"instructions\":%llu", (unsigned long long)r->instructions); }
        else { (void)fprintf(c->out, ",\"instructions\":null"); }
        (void)fprintf(c->out, ",\"libc_bytes\":%llu,\"result\":%llu,\"wall_ns_median\":%llu",
                      (unsigned long long)r->bytes, (unsigned long long)r->result, (unsigned long long)r->wall_median);
    }
    (void)fprintf(c->out, "}\n");
}

static void one_size(const ctx_t *c, size_t n) {
    int p[2];
    int st = 0;
    rec_t r;
    pid_t pid;
    if (pipe(p) != 0) { emit(c, n, "crash", NULL, 0, 4); return; }
    (void)fflush(NULL);
    pid = fork();
    if (pid == 0) { (void)close(p[0]); _exit(child_main(p[1], c->seed, n)); }
    (void)close(p[1]);
    if (pid < 0 || waitpid(pid, &st, 0) != pid) { emit(c, n, "crash", NULL, 0, 5); (void)close(p[0]); return; }
    if (WIFSIGNALED(st)) { emit(c, n, WTERMSIG(st) == SIGALRM ? "timeout" : "crash", NULL, WTERMSIG(st), 0); }
    else if (WEXITSTATUS(st) != 0 || read(p[0], &r, sizeof r) != (ssize_t)sizeof r) { emit(c, n, "crash", NULL, 0, WEXITSTATUS(st) != 0 ? WEXITSTATUS(st) : 6); }
    else { emit(c, n, r.status == ST_OK ? "ok" : r.status == ST_GEN_OVERFLOW ? "gen-overflow" : "run-error", &r, 0, 0); }
    (void)close(p[0]);
}

static int parse_sizes(const char *s, size_t *v) {
    int k = 0;
    while (*s != '\0' && k < MAX_SIZES) {
        char *end = NULL;
        unsigned long long x = strtoull(s, &end, 10);
        if (end == s || x == 0) { return 0; }
        v[k++] = (size_t)x;
        s = *end == ',' ? end + 1 : end;
        if (*end != ',' && *end != '\0') { return 0; }
    }
    return *s == '\0' ? k : 0;
}

int main(int argc, char **argv) {
    ctx_t c = {NULL, 0, NULL};
    const char *out = NULL;
    size_t sizes[MAX_SIZES];
    int k = 0;
    for (int i = 1; i + 1 < argc; i += 2) {
        if (strcmp(argv[i], "--name") == 0) { c.name = argv[i + 1]; }
        else if (strcmp(argv[i], "--seed") == 0) { c.seed = strtoull(argv[i + 1], NULL, 10); }
        else if (strcmp(argv[i], "--sizes") == 0) { k = parse_sizes(argv[i + 1], sizes); }
        else if (strcmp(argv[i], "--out") == 0) { out = argv[i + 1]; }
        else { return 2; }
    }
    if (c.name == NULL || out == NULL || k == 0 || (argc % 2) == 0) { return 2; }
    c.out = fopen(out, "w");
    if (c.out == NULL) { return 2; }
    for (int i = 0; i < k; i++) { one_size(&c, sizes[i]); }
    return fclose(c.out) == 0 ? 0 : 2;
}
