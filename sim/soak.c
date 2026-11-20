#include "sim/soak.h"

#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#include "sim/checks.h"
#include "sim/sha256.h"
#include "sim/trace_fmt.h"
#include "sim/workload.h"

#define SOAK_MAGIC 0x73696d2d736f616bULL
#define SOAK_FAILURES (SIM_CHECKS + 1U)

typedef struct {
    uint64_t magic;
    int32_t rule;                      /* sim_rule_t: why the run stopped early, SIM_OK when it did not */
    int32_t died;                      /* set by the parent: the child was killed and reported nothing (the day is unknown) */
    uint64_t days_done;
    uint64_t first_day[SIM_CHECKS];    /* 0: never failed */
    uint64_t checked_days[SIM_CHECKS];
    uint64_t uploads;
    uint64_t trace_hash;
    uint64_t state_hash;
} soak_result_t;

static void soak_tap(void *ctx, const sim_rec_t *rec) {
    (void)sim_trace_add((sim_trace_t *)ctx, rec);
}

static sim_stats_t g_stats; /* static: larger than the frame limit */

static void checkpoint(world_t *w, uint64_t day, soak_result_t *res) {
    sim_stats_t *stats = &g_stats;
    memset(stats, 0, sizeof *stats);
    if (world_stats(w, stats) != WORLD_OK) {
        res->rule = SIM_WORLD_ERROR;
        return;
    }
    sim_check_t check = sim_check_stats(stats, world_now_ms(w));
    for (unsigned i = 0; i < SIM_CHECKS; i++) {
        res->checked_days[i] += (check.checked >> i) & 1U;
        if (((check.violated >> i) & 1U) != 0 && res->first_day[i] == 0) {
            res->first_day[i] = day;
        }
    }
    res->uploads = stats->uploads;
    res->days_done = day;
}

static int run_to(world_t *w, uint64_t t_ms) {
    int rc = world_run_until(w, t_ms);
    return rc == WORLD_OK && world_now_ms(w) != t_ms ? WORLD_DEADLOCK : rc;
}

static void soak_drive(world_t *w, uint64_t seed, uint64_t days, soak_result_t *res) {
    sim_workload_t wl;
    sim_workload_init(&wl, seed, 0);
    uint64_t t = 0;
    for (uint64_t day = 1; day <= days && res->rule == SIM_OK; day++) {
        while (t < day * SIM_DAY_MS && res->rule == SIM_OK) {
            t += SIM_TICK_MS;
            int rc = sim_workload_tick(w, &wl);
            rc = rc == WORLD_OK ? run_to(w, t) : rc;
            res->rule = (int32_t)sim_rule_of_rc(rc);
        }
        if (res->rule == SIM_OK) {
            checkpoint(w, day, res);
        }
    }
}

static _Noreturn void soak_child(const sim_args_t *a, uint64_t seed, int fd) {
    soak_result_t res;
    memset(&res, 0, sizeof res);
    res.magic = SOAK_MAGIC;
    sim_trace_t trace;
    sim_trace_init(&trace);
    sim_cfg_t cfg;
    cfg.start_ms = 0;
    cfg.step_limit = a->params.step_limit;
    world_t *w = world_init(&cfg, seed, soak_tap, &trace);
    if (w == NULL) {
        res.rule = SIM_INIT_FAILED;
    } else {
        soak_drive(w, seed, a->soak_days, &res);
        res.state_hash = world_state_hash(w);
    }
    res.trace_hash = trace.hash;
    size_t done = 0;
    const char *bytes = (const char *)&res;
    while (done < sizeof res) {
        ssize_t n = write(fd, bytes + done, sizeof res - done);
        if (n <= 0) {
            _exit(3);
        }
        done += (size_t)n;
    }
    _exit(0);
}

static int read_result(int fd, soak_result_t *res) {
    size_t done = 0;
    char *bytes = (char *)res;
    while (done < sizeof *res) {
        ssize_t n = read(fd, bytes + done, sizeof *res - done);
        if (n <= 0) {
            return 0;
        }
        done += (size_t)n;
    }
    return res->magic == SOAK_MAGIC;
}

/* Fork the run; the result of a child that died is `days_done` 0, the rule it died of and `died`. */
static int run_child(const sim_args_t *a, uint64_t seed, soak_result_t *res) {
    int fds[2];
    if (pipe(fds) != 0) {
        return -1;
    }
    pid_t pid = fork();
    if (pid < 0) {
        close(fds[0]);
        close(fds[1]);
        return -1;
    }
    if (pid == 0) {
        close(fds[0]);
        (void)alarm(a->params.real_limit_s);
        soak_child(a, seed, fds[1]);
    }
    close(fds[1]);
    int status = 0;
    pid_t waited = waitpid(pid, &status, 0);
    int have = read_result(fds[0], res);
    close(fds[0]);
    if (waited != pid) {
        return -1;
    }
    if (!have || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        memset(res, 0, sizeof *res);
        res->rule = WIFSIGNALED(status) && WTERMSIG(status) == SIGALRM ? SIM_TIMEOUT : SIM_CRASH;
        res->died = 1;
    }
    return 0;
}

typedef struct {
    const char *assertion;
    uint64_t day;
} soak_failure_t;

/* The failures in day order (ties in I11, I12, I13 order); a world that stopped is one more, on the day it stopped. */
static unsigned collect_failures(const soak_result_t *res, soak_failure_t out[SOAK_FAILURES]) {
    unsigned n = 0;
    for (unsigned i = 0; i < SIM_CHECKS; i++) {
        if (res->first_day[i] != 0) {
            out[n++] = (soak_failure_t){sim_check_name(i), res->first_day[i]};
        }
    }
    if (res->rule != SIM_OK) {
        out[n++] = (soak_failure_t){sim_rule_name((sim_rule_t)res->rule), res->died ? 0 : res->days_done + 1U};
    }
    for (unsigned i = 1; i < n; i++) {
        for (unsigned j = i; j > 0 && out[j - 1U].day > out[j].day; j--) {
            soak_failure_t tmp = out[j];
            out[j] = out[j - 1U];
            out[j - 1U] = tmp;
        }
    }
    return n;
}

static void hex_of(const uint8_t *bytes, size_t len, char *out) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < len; i++) {
        out[2 * i] = digits[bytes[i] >> 4];
        out[2 * i + 1] = digits[bytes[i] & 0xfU];
    }
    out[2 * len] = '\0';
}

static void salt_id(const sim_args_t *a, char out[65]) {
    uint8_t digest[32];
    sha256_t s;
    sha256_init(&s);
    sha256_update(&s, a->salt, a->salt_len);
    sha256_final(&s, digest);
    hex_of(digest, 32, out);
}

static int write_result(const sim_args_t *a, uint64_t seed, const soak_result_t *res) {
    char world[65];
    char salt_sha[65];
    salt_id(a, salt_sha);
    hex_of(a->world_sha256, 32, world);
    FILE *f = fopen(a->soak_path, "w");
    if (f == NULL) {
        return -1;
    }
    (void)fprintf(f, "{\"checked\":{\"I11\":%llu,\"I12\":%llu,\"I13\":%llu},\"days\":%llu,\"failures\":[",
                  (unsigned long long)res->checked_days[0], (unsigned long long)res->checked_days[1],
                  (unsigned long long)res->checked_days[2], (unsigned long long)res->days_done);
    soak_failure_t failures[SOAK_FAILURES];
    unsigned n = collect_failures(res, failures);
    for (unsigned i = 0; i < n; i++) {
        (void)fprintf(f, "%s{\"assertion\":\"%s\",\"day\":%llu}", i == 0 ? "" : ",", failures[i].assertion,
                      (unsigned long long)failures[i].day);
    }
    (void)fprintf(f, "],\"salt_sha256\":\"%s\",\"schema\":\"sim-soak/1\",\"seed\":\"%016llx\",\"state_hash\":\"%016llx\","
                     "\"trace_hash\":\"%016llx\",\"uploads\":%llu,\"world_sha256\":\"%s\"}\n",
                  salt_sha, (unsigned long long)seed, (unsigned long long)res->state_hash,
                  (unsigned long long)res->trace_hash, (unsigned long long)res->uploads, world);
    return fclose(f);
}

int sim_soak_main(const sim_args_t *args) {
    uint64_t seed = sim_seed_of(args->salt, args->salt_len, args->world_sha256, SIM_SOAK_INDEX);
    static soak_result_t res;
    if (run_child(args, seed, &res) != 0) {
        fprintf(stderr, "sim runner: cannot run the soak (fork/pipe failed)\n");
        return 2;
    }
    printf("sim soak: %llu of %llu days, %llu uploads\n", (unsigned long long)res.days_done,
           (unsigned long long)args->soak_days, (unsigned long long)res.uploads);
    if (write_result(args, seed, &res) != 0) {
        fprintf(stderr, "sim runner: cannot write the soak output\n");
        return 2;
    }
    return 0;
}
