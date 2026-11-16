/* The gate-owned `main` of a UI probe binary (P004 4.2; protocol: docs/ui-model.md, "ui-probe/1").
 *
 * Reads one command per line on stdin and writes one reply per command on stdout (a reply is one line, or a header line
 * and the n lines it announces). Strict: a malformed or unknown command, a model that breaks the interface contract,
 * a last line without newline and input after `quit` are protocol errors: an `err` reply, counted, exit status 1.
 * Model failures are ordinary replies (`fail <command>`) that poison the session until the next `open`; a refused
 * input is `ok apply refused`, a missed one `ok apply missed`. The probe owns the time loop (`advance`) and the lvprobe of
 * the session (closed before every `open` and before exit). Static memory only; no recursion. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "ui/model/probe.h"

enum {
    PROBE_LINE_MAX = 640,
    PROBE_TOKENS = 8,
    PROBE_REPLY_MAX = 64 * (2 * 256 + 48) + 64
};

typedef bool (*handler_t)(probe_t *p, char **arg);

typedef struct {
    const char *name;
    size_t argc;            /* the fewest arguments */
    size_t argc_max;        /* the most */
    bool needs_open;
    handler_t run;
} command_t;

static char g_line[PROBE_LINE_MAX + 1];
static size_t g_line_len;
static char g_reply[PROBE_REPLY_MAX];
static char g_payload[UIM_BUF_MAX];
static size_t g_tail_len;   /* bytes of g_payload written after the reply header line */
static uim_input_t g_inputs[UIM_ENV_MAX];
static lvprobe_t g_lv;      /* the lvprobe of the session; its storage is probe_frame.c's */

/* The greeting: the protocol name, `ready` and the capabilities (docs/ui-model.md, "The greeting"); `pointer` last, when
 * the product delivers taps through its own pointer entry (`uim_pointer_supported`). */
static const char GREETING[] = "ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop";

/* ---- replies ------------------------------------------------------------------------------------------------- */

static bool fits(int n)
{
    return n > 0 && (size_t)n < sizeof g_reply;
}

bool probe_reply_err(const char *name, const char *why)
{
    int n = snprintf(g_reply, sizeof g_reply, "err %s %s", name, why);
    g_tail_len = 0;
    if (!fits(n)) {
        memcpy(g_reply, "err ? internal", sizeof "err ? internal");
    }
    return false;
}

bool probe_reply_plain(const char *name, bool good)
{
    return fits(snprintf(g_reply, sizeof g_reply, "%s %s", good ? "ok" : "fail", name)) || probe_reply_err(name, "internal");
}

char *probe_payload(size_t *cap)
{
    *cap = sizeof g_payload;
    return g_payload;
}

static bool reply_number(const char *name, uint64_t value)
{
    return fits(snprintf(g_reply, sizeof g_reply, "ok %s %llu", name, (unsigned long long)value));
}

bool probe_reply_lines(const char *name, size_t lines, size_t bytes)
{
    g_tail_len = bytes;
    return fits(snprintf(g_reply, sizeof g_reply, "ok %s lines %zu", name, lines));
}

/* lvprobe stops observing the display before the model can delete it (`open`) and before exit. */
static void close_lvprobe(probe_t *p)
{
    lvprobe_close(p->lv);
    p->disp = NULL;
    p->framed = false;
    p->tick_set = false;   /* the next session's tick offset is taken at its first frame */
}

/* ---- handlers ------------------------------------------------------------------------------------------------ */

static bool cmd_open(probe_t *p, char **arg)
{
    uint64_t origin = 0;
    uint64_t seed = 0;
    if (!probe_parse_u64(arg[0], &origin) || !probe_parse_u64(arg[1], &seed) || origin > UIM_ORIGIN_MAX_MS) {
        return probe_reply_err("open", "bad-arguments");
    }
    close_lvprobe(p);
    p->opened = uim_open(p->model, origin, seed);
    p->origin = origin;
    p->now = origin;
    return probe_reply_plain("open", p->opened);
}

/* The length of an input's text, or UIM_TEXT_MAX + 1 if it is not terminated within its array. */
static size_t text_len(const char *text)
{
    size_t n = 0;
    while (n <= UIM_TEXT_MAX && text[n] != '\0') {
        n++;
    }
    return n;
}

static bool cmd_env_inputs(probe_t *p, char **arg)
{
    uint16_t n = 0;
    size_t at = 0;
    size_t i = 0;
    (void)arg;
    if (!uim_env_inputs(p->model, g_inputs, (uint16_t)UIM_ENV_MAX, &n)) {
        return probe_reply_plain("env-inputs", false);
    }
    if (n > UIM_ENV_MAX) {
        return probe_reply_err("env-inputs", "model-contract");
    }
    at = (size_t)snprintf(g_reply, sizeof g_reply, "ok env-inputs %u", (unsigned)n);
    for (i = 0; i < n; i++) {
        const uim_input_t *in = &g_inputs[i];
        size_t len = text_len(in->text);
        int w = 0;
        if (in->kind != UIM_IN_ENV || len > UIM_TEXT_MAX) {
            return probe_reply_err("env-inputs", "model-contract");
        }
        w = snprintf(g_reply + at, sizeof g_reply - at, " %u:%lu:%ld:", (unsigned)in->kind, (unsigned long)in->id,
                     (long)in->arg);
        if (!fits(w) || at + (size_t)w + 2u * len + 2u >= sizeof g_reply) {
            return false;
        }
        at += (size_t)w;
        if (len == 0) {
            g_reply[at++] = '-';
            g_reply[at] = '\0';
        } else {
            probe_to_hex((const unsigned char *)in->text, len, g_reply + at);
            at += 2u * len;
        }
    }
    return true;
}

static bool cmd_apply(probe_t *p, char **arg)
{
    uim_input_t in;
    uint64_t kind = 0;
    uint64_t id = 0;
    uim_result_t r = UIM_ERROR;
    memset(&in, 0, sizeof in);
    if (!probe_parse_u64(arg[0], &kind) || kind < UIM_IN_ENV || kind > UIM_IN_INTENT || !probe_parse_u64(arg[1], &id) ||
        id > UINT32_MAX || !probe_parse_i32(arg[2], &in.arg) || !probe_parse_text(arg[3], in.text)) {
        return probe_reply_err("apply", "bad-arguments");
    }
    in.kind = (uint16_t)kind;
    in.id = (uint32_t)id;
    p->framed = false;
    r = uim_apply(p->model, &in);
    if (r == UIM_OK || r == UIM_REFUSED || r == UIM_MISSED) {
        return fits(snprintf(g_reply, sizeof g_reply, "%s",
                             r == UIM_OK ? "ok apply" : r == UIM_REFUSED ? "ok apply refused" : "ok apply missed"));
    }
    p->opened = false;
    return r == UIM_ERROR ? probe_reply_plain("apply", false) : probe_reply_err("apply", "model-contract");
}

static bool cmd_next_due(probe_t *p, char **arg)
{
    uint64_t due = uim_next_due(p->model);
    (void)arg;
    if (due != UIM_NO_DEADLINE && due <= p->now) {   /* a deadline on a stable scene is in the future */
        p->opened = false;
        return probe_reply_err("next-due", "model-contract");
    }
    if (due == UIM_NO_DEADLINE) {
        return fits(snprintf(g_reply, sizeof g_reply, "ok next-due none"));
    }
    return reply_number("next-due", due);
}

static bool cmd_advance(probe_t *p, char **arg)
{
    uint64_t to = 0;
    probe_advance_t r = PROBE_ADV_OK;
    if (!probe_parse_u64(arg[0], &to) || to < p->now || to > UIM_TIME_MAX_MS || to - p->now > UIM_ADVANCE_MAX_MS) {
        return probe_reply_err("advance", "bad-arguments");
    }
    p->framed = false;
    r = probe_advance_to(p, to);
    if (r == PROBE_ADV_CONTRACT) {
        p->opened = false;
        return probe_reply_err("advance", "model-contract");
    }
    if (r == PROBE_ADV_FAILED) {
        p->opened = false;
        return probe_reply_plain("advance", false);
    }
    return reply_number("advance", p->now);
}

static bool cmd_domain_count(probe_t *p, char **arg)
{
    (void)p;
    (void)arg;
    return reply_number("domain-count", uim_domain_count());
}

static bool cmd_domain_at(probe_t *p, char **arg)
{
    uint64_t i = 0;
    if (!probe_parse_u64(arg[0], &i) || i >= uim_domain_count()) {
        return probe_reply_err("domain-at", "bad-arguments");
    }
    p->framed = false;
    if (!uim_domain_at(p->model, (uint16_t)i)) {
        p->opened = false;
        return probe_reply_plain("domain-at", false);
    }
    return probe_reply_plain("domain-at", true);
}

static bool cmd_quit(probe_t *p, char **arg)
{
    (void)arg;
    p->quit = true;
    return fits(snprintf(g_reply, sizeof g_reply, "ok quit"));
}

static const command_t g_commands[] = {
    {"open", 2, 2, false, cmd_open},
    {"env-inputs", 0, 0, true, cmd_env_inputs},
    {"apply", 4, 4, true, cmd_apply},
    {"next-due", 0, 0, true, cmd_next_due},
    {"advance", 1, 1, true, cmd_advance},
    {"frame", 0, 0, true, probe_cmd_frame},
    {"ink", 0, 1, true, probe_cmd_ink},
    {"hit-test", 2, 2, true, probe_cmd_hit_test},
    {"tap", 2, 2, true, probe_cmd_tap},
    {"crop", 4, 4, true, probe_cmd_crop},
    {"semantic", 0, 0, true, probe_cmd_semantic},
    {"patches", 0, 0, true, probe_cmd_patches},
    {"domain-count", 0, 0, false, cmd_domain_count},
    {"domain-at", 1, 1, true, cmd_domain_at},
    {"trace", 0, 0, true, probe_cmd_trace},
    {"quit", 0, 0, false, cmd_quit},
};

/* ---- the loop ------------------------------------------------------------------------------------------------ */

/* Splits g_line in place on single spaces. -1 if it is malformed (empty line, a byte outside 0x20..0x7e, NUL included,
 * an empty token, too many tokens), else the token count. */
static int split(char **tok, size_t max)
{
    size_t n = 0;
    size_t i = 0;
    bool start = true;
    if (g_line_len == 0) {
        return -1;
    }
    for (i = 0; i < g_line_len; i++) {
        unsigned char c = (unsigned char)g_line[i];
        if (c < 0x20 || c > 0x7e) {
            return -1;
        }
    }
    g_line[g_line_len] = '\0';
    for (i = 0; i < g_line_len; i++) {
        if (g_line[i] == ' ') {
            if (start) {
                return -1;
            }
            g_line[i] = '\0';
            start = true;
        } else if (start) {
            if (n == max) {
                return -1;
            }
            tok[n++] = &g_line[i];
            start = false;
        }
    }
    return start ? -1 : (int)n;
}

static bool dispatch(probe_t *p)
{
    char *tok[PROBE_TOKENS + 1];
    size_t i = 0;
    int n = split(tok, PROBE_TOKENS);
    g_tail_len = 0;
    if (n < 0) {
        return probe_reply_err("?", "malformed");
    }
    tok[n] = NULL;   /* the handlers see NULL-terminated arguments */
    for (i = 0; i < sizeof g_commands / sizeof g_commands[0]; i++) {
        const command_t *c = &g_commands[i];
        bool good = false;
        if (strcmp(tok[0], c->name) != 0) {
            continue;
        }
        if ((size_t)n - 1u < c->argc || (size_t)n - 1u > c->argc_max) {
            return probe_reply_err(c->name, "bad-arguments");
        }
        if (c->needs_open && !p->opened) {
            return probe_reply_err(c->name, "not-open");
        }
        p->cmd = c->name;
        good = c->run(p, tok + 1);
        if (!good && strncmp(g_reply, "err ", 4) != 0) {
            return probe_reply_err(c->name, "internal");
        }
        return good;
    }
    return probe_reply_err("?", "unknown-command");
}

static bool emit(void)
{
    if (fputs(g_reply, stdout) < 0 || fputc('\n', stdout) == EOF) {
        return false;
    }
    if (g_tail_len > 0 && fwrite(g_payload, 1, g_tail_len, stdout) != g_tail_len) {
        return false;
    }
    return fflush(stdout) == 0;
}

typedef enum { RL_LINE, RL_EOF, RL_PARTIAL, RL_LONG, RL_ERROR } read_t;

/* Reads one line into g_line / g_line_len (without its LF; any byte, NUL included). RL_PARTIAL: data and then EOF with
 * no LF. RL_LONG: more than PROBE_LINE_MAX bytes (the rest of the line is dropped). */
static read_t read_line(void)
{
    size_t n = 0;
    int c = 0;
    bool too_long = false;
    for (;;) {
        c = fgetc(stdin);
        if (c == EOF || c == '\n') {
            break;
        }
        if (n < PROBE_LINE_MAX) {
            g_line[n++] = (char)c;
        } else {
            too_long = true;
        }
    }
    g_line_len = n;
    if (c == EOF && ferror(stdin) != 0) {
        return RL_ERROR;
    }
    if (too_long) {
        return RL_LONG;
    }
    if (c == '\n') {
        return RL_LINE;
    }
    return n == 0 ? RL_EOF : RL_PARTIAL;
}

/* One reply for a line the loop itself refuses. */
static bool refuse(probe_t *p, const char *why)
{
    p->failed = true;
    (void)probe_reply_err("?", why);
    return emit();
}

/* After `quit`: anything but empty lines until EOF is an error (one reply, every line counted). */
static bool drain(probe_t *p)
{
    bool told = false;
    read_t got = RL_LINE;
    while ((got = read_line()) != RL_EOF) {
        if (got == RL_ERROR) {
            return false;
        }
        if (g_line_len == 0 && got == RL_LINE) {
            continue;
        }
        if (!told) {
            told = true;
            if (!refuse(p, "after-quit")) {
                return false;
            }
        } else {
            p->failed = true;
        }
    }
    return true;
}

static bool serve(probe_t *p)
{
    while (!p->quit) {
        read_t got = read_line();
        if (got == RL_ERROR) {
            return false;
        }
        if (got == RL_EOF || got == RL_PARTIAL) {
            if (got == RL_PARTIAL && !refuse(p, "malformed")) {
                return false;
            }
            return refuse(p, "eof-without-quit");
        }
        if (got == RL_LONG) {
            if (!refuse(p, "line-too-long")) {
                return false;
            }
            continue;
        }
        if (!dispatch(p)) {
            p->failed = true;
        }
        if (!emit()) {
            return false;
        }
    }
    return drain(p);
}

int main(void)
{
    probe_t p;
    bool served = false;
    p.model = uim_instance();
    p.opened = false;
    p.quit = false;
    p.failed = false;
    p.origin = 0;
    p.now = 0;
    p.cmd = "?";
    p.lv = &g_lv;
    p.disp = NULL;
    p.framed = false;
    p.tick_set = false;
    p.tick_offset = 0;
    p.pointer = uim_pointer_supported();   /* a constant of the build: read once */
    g_tail_len = 0;
    if (p.model == NULL || !fits(snprintf(g_reply, sizeof g_reply, "%s%s", GREETING, p.pointer ? " pointer" : "")) ||
        !emit()) {
        return 2;
    }
    served = serve(&p);
    close_lvprobe(&p);
    if (!served) {
        return 2;
    }
    return p.failed ? 1 : 0;
}
