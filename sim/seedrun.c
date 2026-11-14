#include "sim/seedrun.h"

#include <signal.h>
#include <stddef.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#include "sim/trace_fmt.h"
#include "sim/workload.h"

#define HIST_CAP 65536U
#define RESULT_MAGIC 0x73696d2d72657331ULL

/* What the child reports through the pipe. */
typedef struct {
    uint64_t magic;
    int32_t rule[2];
    uint64_t trace[2];
    uint64_t state[2];
    uint64_t records[2];
    int64_t first_diff;
} child_result_t;

typedef struct {
    sim_trace_t trace;
    const uint64_t *ref; /* the first pass's rolling hashes, when this is the second pass */
    uint64_t *hist;      /* where the first pass stores them */
    int64_t first_diff;
} tap_ctx_t;

static uint64_t g_hist[HIST_CAP];

const char *sim_rule_name(sim_rule_t rule) {
    static const char *const names[SIM_RULE_COUNT] = {"ok",           "sim-crash",      "sim-timeout",
                                                      "sim-nondeterministic", "sim-deadlock", "sim-init-failed",
                                                      "sim-world-error"};
    return (unsigned)rule < (unsigned)SIM_RULE_COUNT ? names[rule] : "sim-world-error";
}

static void pass_tap(void *ctx, const sim_rec_t *rec) {
    tap_ctx_t *t = (tap_ctx_t *)ctx;
    uint64_t index = t->trace.records;
    if (!sim_trace_add(&t->trace, rec) || index >= HIST_CAP) {
        return;
    }
    if (t->ref != NULL) {
        if (t->first_diff < 0 && t->ref[index] != t->trace.hash) {
            t->first_diff = (int64_t)index;
        }
    } else {
        t->hist[index] = t->trace.hash;
    }
}

static sim_rule_t rule_of_rc(int rc) {
    switch (rc) {
    case WORLD_OK:
        return SIM_OK;
    case WORLD_STEP_LIMIT:
        return SIM_TIMEOUT;
    case WORLD_DEADLOCK:
        return SIM_DEADLOCK;
    default:
        return SIM_WORLD_ERROR;
    }
}

static int drive_to(world_t *w, uint64_t t_ms) {
    int rc = world_run_until(w, t_ms);
    if (rc == WORLD_OK && world_now_ms(w) != t_ms) {
        return WORLD_DEADLOCK; /* returned without getting there: time is stuck */
    }
    return rc;
}

static int drive(world_t *w, const sim_params_t *p, uint64_t seed) {
    sim_rng_t rng;
    sim_rng_seed(&rng, seed);
    for (uint64_t t = SIM_TICK_MS; t <= p->run_ms; t += SIM_TICK_MS) {
        int rc = sim_workload_tick(w, &rng);
        if (rc == WORLD_OK) {
            rc = drive_to(w, t);
        }
        if (rc != WORLD_OK) {
            return rc;
        }
    }
    return drive_to(w, p->run_ms + SIM_DRAIN_MS); /* the quiet drain: no input, no fault */
}

static sim_rule_t run_pass(const sim_params_t *p, uint64_t seed, tap_ctx_t *tap, uint64_t *state) {
    sim_cfg_t cfg;
    cfg.start_ms = 0;
    cfg.step_limit = p->step_limit;
    sim_trace_init(&tap->trace);
    world_t *w = world_init(&cfg, seed, pass_tap, tap);
    if (w == NULL) {
        return SIM_INIT_FAILED;
    }
    int rc = drive(w, p, seed);
    *state = world_state_hash(w);
    return rule_of_rc(rc);
}

static _Noreturn void child_main(const sim_params_t *p, uint64_t seed, int fd) {
    child_result_t res;
    memset(&res, 0, sizeof res);
    res.magic = RESULT_MAGIC;
    res.first_diff = -1;
    tap_ctx_t tap;
    tap.ref = NULL;
    tap.hist = g_hist;
    tap.first_diff = -1;
    res.rule[0] = (int32_t)run_pass(p, seed, &tap, &res.state[0]);
    res.trace[0] = tap.trace.hash;
    res.records[0] = tap.trace.records;
    tap.ref = g_hist;
    tap.first_diff = -1;
    res.rule[1] = (int32_t)run_pass(p, seed, &tap, &res.state[1]);
    res.trace[1] = tap.trace.hash;
    res.records[1] = tap.trace.records;
    res.first_diff = tap.first_diff;
    if (res.first_diff < 0 && res.records[0] != res.records[1]) {
        res.first_diff = (int64_t)(res.records[0] < res.records[1] ? res.records[0] : res.records[1]);
    }
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

static int read_result(int fd, child_result_t *res) {
    size_t done = 0;
    char *bytes = (char *)res;
    while (done < sizeof *res) {
        ssize_t n = read(fd, bytes + done, sizeof *res - done);
        if (n <= 0) {
            return 0;
        }
        done += (size_t)n;
    }
    return res->magic == RESULT_MAGIC;
}

static void classify_exit(int status, int have, const child_result_t *res, sim_seed_out_t *out) {
    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        out->rule = sig == SIGALRM ? SIM_TIMEOUT : SIM_CRASH;
        out->detail = sig;
        return;
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0 || !have) {
        out->rule = SIM_CRASH;
        out->detail = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
        return;
    }
    out->trace_hash = res->trace[0];
    out->state_hash = res->state[0];
    out->records = res->records[0];
    out->first_diff = res->first_diff;
    for (unsigned i = 0; i < 2 && out->rule == SIM_OK; i++) {
        out->rule = (sim_rule_t)res->rule[i];
    }
    if (out->rule == SIM_OK && (res->trace[0] != res->trace[1] || res->state[0] != res->state[1])) {
        out->rule = SIM_NONDETERMINISTIC;
        out->detail = (int)res->first_diff;
    }
}

int sim_run_seed(const sim_params_t *params, uint64_t seed, sim_seed_out_t *out) {
    memset(out, 0, sizeof *out);
    out->first_diff = -1;
    out->detail = -1;
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
        (void)alarm(params->real_limit_s);
        child_main(params, seed, fds[1]);
    }
    close(fds[1]);
    int status = 0;
    pid_t waited = waitpid(pid, &status, 0);
    child_result_t res;
    int have = read_result(fds[0], &res);
    close(fds[0]);
    if (waited != pid) {
        return -1;
    }
    classify_exit(status, have, &res, out);
    return 0;
}
