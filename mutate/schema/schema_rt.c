/* Runtime of the schema mutation engine: the active mutant, the reach bitmap and the `main` wrapper.
 *
 * Linked with `-Wl,--wrap=main`, so the C runtime start code calls __wrap_main, which calls the test's own main
 * (__real_main) with the arguments that are not ours:
 *
 *   (none of ours)                                   run the real main once, nothing active
 *   --rigor-mode reach --rigor-reach FILE            run it once with no mutant active; the sites that ran are
 *                                                    written to FILE, one index per line (the bitmap is shared memory,
 *                                                    because ctest runs every test in a forked child)
 *   --rigor-mode kill --rigor-list FILE --rigor-dir DIR
 *                                                    FILE has one "INDEX NAME" per line. A baseline run with no
 *                                                    mutant first fixes the limit clamp(20 x its wall time, 5 s,
 *                                                    180 s) (a baseline that timed out: 180 s, T122); then for each
 *                                                    line: fork, activate INDEX in the child, run the real main with
 *                                                    `--out DIR/NAME.res`, wait under the limit, write "RC TIMEDOUT"
 *                                                    to DIR/NAME.st (RC is the exit status, -1 if it died of a signal;
 *                                                    TIMEDOUT is 1 when the process group was killed at the limit).
 *
 * The ctest resource limits (RLIMIT_FSIZE, RLIMIT_CPU, RLIMIT_NOFILE, scratch quota) are set by the real main in each
 * child. No allocation: static buffers, and one anonymous shared mapping in reach mode.
 */
#define _GNU_SOURCE
#include "schema_rt.h"

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

int __real_main(int argc, char **argv);
int __wrap_main(int argc, char **argv);

enum {
    ARGS_MAX = 32,
    PATH_MAX_LEN = 4096,
    LIST_CAP = 1 << 22,
    BASE_MS_PER_RUN = 20,
    LIMIT_MIN_MS = 5000,
    LIMIT_MAX_MS = 180000,
    POLL_MIN_US = 100,
    POLL_MAX_US = 4000,
    EXIT_RT = 2
};

typedef struct {
    const char *mode;
    const char *reach;
    const char *list;
    const char *dir;
} rt_opts_t;

static unsigned char g_idle_map[RIGOR_SCHEMA_MAX]; /* where hits go when nobody reads them */
static char g_list[LIST_CAP];
static char g_res[PATH_MAX_LEN];  /* path buffers are static: the sealed frame limit is 512 bytes */
static char g_st[PATH_MAX_LEN];
static char *g_rest[ARGS_MAX + 3];
static int g_nrest;

unsigned char *rigor_reach = g_idle_map;
int rigor_active = 0;

static int take_option(char **argv, int argc, int *i, rt_opts_t *o) {
    const char **slot = NULL;
    if (strcmp(argv[*i], "--rigor-mode") == 0) {
        slot = &o->mode;
    } else if (strcmp(argv[*i], "--rigor-reach") == 0) {
        slot = &o->reach;
    } else if (strcmp(argv[*i], "--rigor-list") == 0) {
        slot = &o->list;
    } else if (strcmp(argv[*i], "--rigor-dir") == 0) {
        slot = &o->dir;
    } else {
        return 0;
    }
    if (*i + 1 >= argc || *slot != NULL) {
        return -1;
    }
    *slot = argv[*i + 1];
    *i += 1;
    return 1;
}

static int split_args(int argc, char **argv, rt_opts_t *o) {
    g_nrest = 0;
    g_rest[g_nrest++] = argv[0];
    for (int i = 1; i < argc; i++) {
        int taken = take_option(argv, argc, &i, o);
        if (taken < 0) {
            return -1;
        }
        if (taken == 0) {
            if (g_nrest >= ARGS_MAX) {
                return -1;
            }
            g_rest[g_nrest++] = argv[i];
        }
    }
    g_rest[g_nrest] = NULL;
    return 0;
}

static long now_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return -1;
    }
    return (long)ts.tv_sec * 1000L + (long)(ts.tv_nsec / 1000000L);
}

static int write_reach(const char *path, const unsigned char *map) {
    FILE *f = fopen(path, "w");
    if (f == NULL) {
        return -1;
    }
    int bad = 0;
    for (int i = 1; i < RIGOR_SCHEMA_MAX; i++) {
        if (map[i] != 0 && fprintf(f, "%d\n", i) < 0) {
            bad = 1;
        }
    }
    if (fclose(f) != 0) {
        bad = 1;
    }
    return bad ? -1 : 0;
}

static int run_reach(const rt_opts_t *o) {
    void *map;
    int rc;
    if (o->reach == NULL) {
        return EXIT_RT;
    }
    map = mmap(NULL, RIGOR_SCHEMA_MAX, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (map == MAP_FAILED) {
        return EXIT_RT;
    }
    rigor_reach = (unsigned char *)map;
    rigor_active = 0;
    rc = __real_main(g_nrest, g_rest);
    return write_reach(o->reach, (const unsigned char *)map) != 0 ? EXIT_RT : rc;
}

static int out_path(char *buf, size_t cap, const char *dir, const char *name, const char *ext) {
    int n = snprintf(buf, cap, "%s/%s.%s", dir, name, ext);
    return (n < 0 || (size_t)n >= cap) ? -1 : 0;
}

/* The child: activate the mutant and become the test run. Never returns. */
_Noreturn static void child_run(int index, char *res) {
    char *args[ARGS_MAX + 3];
    int n = 0;
    for (int i = 0; i < g_nrest; i++) {
        args[n++] = g_rest[i];
    }
    args[n++] = (char *)"--out";
    args[n++] = res;
    args[n] = NULL;
    if (setpgid(0, 0) != 0) {
        _exit(EXIT_RT);
    }
    rigor_active = index;
    exit(__real_main(n, args));
}

static void nap(long us) {
    struct timespec ts;
    ts.tv_sec = 0;
    ts.tv_nsec = us * 1000L;
    (void)nanosleep(&ts, NULL); /* an interrupted sleep only makes the next poll earlier */
}

/* Wait for pid until limit_ms; kill its process group at the limit. 0 when reaped, -1 on a wait error. */
static int wait_limit(pid_t pid, long limit_ms, int *status, int *timed_out) {
    long start = now_ms();
    long us = POLL_MIN_US;
    *timed_out = 0;
    for (;;) {
        pid_t r = waitpid(pid, status, WNOHANG);
        if (r == pid) {
            return 0;
        }
        if (r < 0 && errno != EINTR) {
            return -1;
        }
        if (start < 0 || now_ms() - start >= limit_ms) {
            *timed_out = 1;
            if (kill(-pid, SIGKILL) != 0 && kill(pid, SIGKILL) != 0) {
                return -1;
            }
            return waitpid(pid, status, 0) == pid ? 0 : -1;
        }
        nap(us);
        us = us * 2 > POLL_MAX_US ? POLL_MAX_US : us * 2;
    }
}

/* One run of the real main with mutant `index` active (0: none). rc: exit status or -1; wall in ms. */
static int run_one(int index, char *res, long limit_ms, int *rc, int *timed_out, long *wall) {
    int status = 0;
    long start = now_ms();
    pid_t pid = fork();
    if (pid < 0) {
        return -1;
    }
    if (pid == 0) {
        child_run(index, res);
    }
    if (setpgid(pid, pid) != 0 && errno != EACCES && errno != ESRCH) {
        return -1;
    }
    if (wait_limit(pid, limit_ms, &status, timed_out) != 0) {
        return -1;
    }
    *rc = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    *wall = now_ms() - start;
    return 0;
}

static int write_status(const char *dir, const char *name, int rc, int timed_out) {
    FILE *f;
    int bad;
    if (out_path(g_st, sizeof g_st, dir, name, "st") != 0 || (f = fopen(g_st, "w")) == NULL) {
        return -1;
    }
    bad = fprintf(f, "%d %d\n", rc, timed_out) < 0;
    return (fclose(f) != 0 || bad) ? -1 : 0;
}

static int baseline_limit(const char *dir, long *limit_ms) {
    int rc = 0;
    int timed_out = 0;
    long wall = 0;
    if (out_path(g_res, sizeof g_res, dir, "baseline", "res") != 0 ||
        run_one(0, g_res, LIMIT_MAX_MS, &rc, &timed_out, &wall) != 0) {
        return -1;
    }
    *limit_ms = BASE_MS_PER_RUN * wall;
    if (timed_out) {
        *limit_ms = LIMIT_MAX_MS;
    }
    if (*limit_ms < LIMIT_MIN_MS) {
        *limit_ms = LIMIT_MIN_MS;
    }
    if (*limit_ms > LIMIT_MAX_MS) {
        *limit_ms = LIMIT_MAX_MS;
    }
    return 0;
}

static int load_list(const char *path, size_t *len) {
    FILE *f = fopen(path, "r");
    size_t n;
    if (f == NULL) {
        return -1;
    }
    n = fread(g_list, 1, sizeof g_list - 1, f);
    if (ferror(f) != 0 || !feof(f)) {
        (void)fclose(f);
        return -1; /* unreadable or too long */
    }
    if (fclose(f) != 0) {
        return -1;
    }
    g_list[n] = '\0';
    *len = n;
    return 0;
}

static int valid_name(const char *s) {
    size_t n = strlen(s);
    if (n == 0 || n > 64) {
        return 0;
    }
    for (size_t i = 0; i < n; i++) {
        if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'z') || s[i] == '_')) {
            return 0;
        }
    }
    return 1;
}

/* Runs the mutant of one list line "INDEX NAME". */
static int kill_line(char *line, const char *dir, long limit_ms) {
    char *end = NULL;
    char *name;
    long index = strtol(line, &end, 10);
    int rc = 0;
    int timed_out = 0;
    long wall = 0;
    if (end == line || *end != ' ' || index < 1 || index >= RIGOR_SCHEMA_MAX) {
        return -1;
    }
    name = end + 1;
    if (!valid_name(name) || out_path(g_res, sizeof g_res, dir, name, "res") != 0) {
        return -1;
    }
    if (run_one((int)index, g_res, limit_ms, &rc, &timed_out, &wall) != 0) {
        return -1;
    }
    return write_status(dir, name, rc, timed_out);
}

static int run_kill(const rt_opts_t *o) {
    long limit_ms = 0;
    size_t len = 0;
    char *line;
    if (o->list == NULL || o->dir == NULL || load_list(o->list, &len) != 0 || baseline_limit(o->dir, &limit_ms) != 0) {
        return EXIT_RT;
    }
    line = g_list;
    while (*line != '\0') {
        char *nl = strchr(line, '\n');
        if (nl != NULL) {
            *nl = '\0';
        }
        if (*line != '\0' && kill_line(line, o->dir, limit_ms) != 0) {
            return EXIT_RT;
        }
        if (nl == NULL) {
            break;
        }
        line = nl + 1;
    }
    return 0;
}

int __wrap_main(int argc, char **argv) {
    rt_opts_t o = {NULL, NULL, NULL, NULL};
    if (split_args(argc, argv, &o) != 0) {
        return EXIT_RT;
    }
    if (o.mode == NULL) {
        return __real_main(g_nrest, g_rest);
    }
    if (strcmp(o.mode, "reach") == 0) {
        return run_reach(&o);
    }
    return strcmp(o.mode, "kill") == 0 ? run_kill(&o) : EXIT_RT;
}
