/* ctest CHECK_TRAPS: the expression runs in a child of the test process and passes only if the child dies by
 * SIGILL (what __builtin_trap() raises). See ctest.h and docs/ctest.md. */
#define _GNU_SOURCE
#include "traps.h"
#include "sanlog.h"

#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

enum {
    TRAP_TIMEOUT_MS = 3000, /* one expression; the whole test still has the runner's 10 s */
    WHY_CAP = 200,
    SAN_CAP = 1 << 14,
    SUM_CAP = 120
};

static const char *g_prefix;
static char g_san_text[SAN_CAP];
static char g_san_sum[SUM_CAP];
static char g_why[WHY_CAP];
static volatile unsigned char *g_flag; /* shared with the child: set only when the expression returned */

void ctest_traps_set_san_log(const char *prefix) {
    g_prefix = prefix;
}

static long now_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return -1;
    }
    return (long)ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

/* 0 = reaped, 1 = timeout, -1 = error. */
static int wait_for(pid_t pid, int *status) {
    long deadline = now_ms() + TRAP_TIMEOUT_MS;
    for (;;) {
        pid_t r = waitpid(pid, status, WNOHANG);
        long now;
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

/* A sanitizer report of the child, if any: the child's log file is "<prefix>.<pid>". */
static int sanitizer_why(pid_t pid) {
    size_t n;
    if (g_prefix == NULL) {
        return 0;
    }
    n = sanlog_take(g_prefix, (long)pid, g_san_text, sizeof g_san_text);
    if (n == 0) {
        return 0;
    }
    n = sanlog_normalize(g_san_text, n);
    sanlog_summary(g_san_text, n, g_san_sum, sizeof g_san_sum);
    (void)snprintf(g_why, sizeof g_why, "the expression made a sanitizer report instead: %s", g_san_sum);
    return 1;
}

/* 1 when the child died by the trap; otherwise g_why says what happened instead. */
static int judge(pid_t pid, int waited, int status) {
    int report = sanitizer_why(pid);
    if (waited == 1) {
        (void)snprintf(g_why, sizeof g_why, "timeout after %d ms, the expression did not trap", TRAP_TIMEOUT_MS);
        return 0;
    }
    if (report) {
        return 0;
    }
    if (WIFSIGNALED(status)) {
        if (WTERMSIG(status) == SIGILL) {
            return 1;
        }
        (void)snprintf(g_why, sizeof g_why, "the expression died by signal %d (%s), not by the trap", WTERMSIG(status),
                       strsignal(WTERMSIG(status)));
    } else if (*g_flag != 0) {
        (void)snprintf(g_why, sizeof g_why, "the expression returned, it did not trap");
    } else {
        (void)snprintf(g_why, sizeof g_why, "the expression exited with status %d, it did not trap", WEXITSTATUS(status));
    }
    return 0;
}

/* 1 = the child died by the trap, 0 = it did not (g_why says what happened), -1 = cannot wait. */
static int run_parent(pid_t pid) {
    int status = 0;
    int waited = wait_for(pid, &status);
    if (waited != 0) {
        if (kill(pid, SIGKILL) != 0 && errno != ESRCH) {
            return -1;
        }
        while (waitpid(pid, &status, 0) != pid) {
            if (errno != EINTR) {
                return -1;
            }
        }
    }
    return waited < 0 ? -1 : judge(pid, waited, status);
}

int ctest_trap_begin(ctest_t *t, const char *file, int line, const char *expr) {
    pid_t pid;
    int ok;
    void *page = mmap(NULL, 1, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (page == MAP_FAILED) {
        ctest_check_traps(t, 0, file, line, expr, "cannot map the flag page");
        return 0;
    }
    g_flag = page;
    *g_flag = 0;
    (void)fflush(NULL); /* the child must not inherit unflushed output */
    pid = fork();
    if (pid < 0) {
        ctest_check_traps(t, 0, file, line, expr, "fork failed");
        (void)munmap(page, 1);
        return 0;
    }
    if (pid == 0) {
        /* The sanitizer runtime handles SIGILL in the `san` mode; the trap must stay the signal it is. */
        if (signal(SIGILL, SIG_DFL) == SIG_ERR) {
            _exit(4);
        }
        return 1;
    }
    ok = run_parent(pid);
    ctest_check_traps(t, ok == 1, file, line, expr, ok < 0 ? "cannot wait for the expression" : g_why);
    (void)munmap(page, 1);
    return 0;
}

_Noreturn void ctest_trap_returned(void) {
    *g_flag = 1;
    _exit(0);
}
