/* The gate-owned `main` of a UI probe binary (P004 4.2; protocol: docs/ui-model.md, "ui-probe/1").
 *
 * Reads one command per line on stdin and writes one reply per command on stdout (a reply is one line, or a header line
 * and the n lines it announces). Strict: a malformed or unknown command, a model that breaks the interface contract,
 * a last line without newline and input after `quit` are protocol errors: an `err` reply, counted, exit status 1.
 * Model failures are ordinary replies (`fail <command>`) that poison the session until the next `open`; a refused
 * input is `ok apply refused`. The probe owns the time loop (`advance`). Static memory only; no recursion. */
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
typedef bool (*buffer_fn_t)(uim_t *, uim_buf_t *);

typedef struct {
    const char *name;
    size_t argc;
    bool needs_open;
    handler_t run;
} command_t;

static char g_line[PROBE_LINE_MAX + 1];
static size_t g_line_len;
static char g_reply[PROBE_REPLY_MAX];
static char g_payload[UIM_BUF_MAX];
static size_t g_tail_len;   /* bytes of g_payload written after the reply header line */
static uim_input_t g_inputs[UIM_ENV_MAX];

/* ---- replies ------------------------------------------------------------------------------------------------- */

static bool fits(int n)
{
    return n > 0 && (size_t)n < sizeof g_reply;
}

static bool reply_err(const char *name, const char *why)
{
    int n = snprintf(g_reply, sizeof g_reply, "err %s %s", name, why);
    g_tail_len = 0;
    if (!fits(n)) {
        memcpy(g_reply, "err ? internal", sizeof "err ? internal");
    }
    return false;
}

static bool reply_plain(const char *name, bool good)
{
    return fits(snprintf(g_reply, sizeof g_reply, "%s %s", good ? "ok" : "fail", name)) || reply_err(name, "internal");
}

static bool reply_number(const char *name, uint64_t value)
{
    return fits(snprintf(g_reply, sizeof g_reply, "ok %s %llu", name, (unsigned long long)value));
}

static bool reply_lines(const char *name, size_t lines, size_t bytes)
{
    g_tail_len = bytes;
    return fits(snprintf(g_reply, sizeof g_reply, "ok %s lines %zu", name, lines));
}



/* ---- handlers ------------------------------------------------------------------------------------------------ */

static bool cmd_open(probe_t *p, char **arg)
{
    uint64_t origin = 0;
    uint64_t seed = 0;
    if (!probe_parse_u64(arg[0], &origin) || !probe_parse_u64(arg[1], &seed) || origin > UIM_ORIGIN_MAX_MS) {
        return reply_err("open", "bad-arguments");
    }
    p->opened = uim_open(p->model, origin, seed);
    p->origin = origin;
    p->now = origin;
    return reply_plain("open", p->opened);
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
        return reply_plain("env-inputs", false);
    }
    if (n > UIM_ENV_MAX) {
        return reply_err("env-inputs", "model-contract");
    }
    at = (size_t)snprintf(g_reply, sizeof g_reply, "ok env-inputs %u", (unsigned)n);
    for (i = 0; i < n; i++) {
        const uim_input_t *in = &g_inputs[i];
        size_t len = text_len(in->text);
        int w = 0;
        if (in->kind != UIM_IN_ENV || len > UIM_TEXT_MAX) {
            return reply_err("env-inputs", "model-contract");
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
        return reply_err("apply", "bad-arguments");
    }
    in.kind = (uint16_t)kind;
    in.id = (uint32_t)id;
    r = uim_apply(p->model, &in);
    if (r == UIM_OK || r == UIM_REFUSED) {
        return fits(snprintf(g_reply, sizeof g_reply, r == UIM_OK ? "ok apply" : "ok apply refused"));
    }
    p->opened = false;
    return reply_plain("apply", false);
}

static bool cmd_next_due(probe_t *p, char **arg)
{
    uint64_t due = uim_next_due(p->model);
    (void)arg;
    if (due != UIM_NO_DEADLINE && due < p->now) {
        return reply_err("next-due", "model-contract");
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
        return reply_err("advance", "bad-arguments");
    }
    r = probe_advance_to(p, to);
    if (r == PROBE_ADV_CONTRACT) {
        return reply_err("advance", "model-contract");
    }
    if (r == PROBE_ADV_FAILED) {
        p->opened = false;
        return reply_plain("advance", false);
    }
    return reply_number("advance", p->now);
}

/* SEAM(U05): the one place where `lvprobe` joins the probe. After `uim_frame` produced `disp`, U05 writes the facts of
 * the frame (tree, ink, hit table, CRC) here as printable lines ending in LF. Today it writes none. */
static bool seam_frame_lines(struct _lv_display_t *disp, char *out, size_t cap, size_t *len)
{
    (void)disp;
    (void)out;
    (void)cap;
    *len = 0;
    return true;
}

static bool cmd_frame(probe_t *p, char **arg)
{
    struct _lv_display_t *disp = NULL;
    size_t len = 0;
    long lines = 0;
    (void)arg;
    if (!uim_frame(p->model, &disp)) {
        p->opened = false;
        return reply_plain("frame", false);
    }
    if (disp == NULL || !seam_frame_lines(disp, g_payload, sizeof g_payload, &len) || len > sizeof g_payload) {
        return reply_err("frame", "model-contract");
    }
    lines = probe_check_records(NULL, g_payload, len);
    return lines < 0 ? reply_err("frame", "model-contract") : reply_lines("frame", (size_t)lines, len);
}

/* `semantic`, `patches` and `trace`: `ok <name> lines <n>` and the n records verbatim. */
static bool buffer_reply(probe_t *p, const char *name, buffer_fn_t fn, const probe_spec_t *spec, bool poisons)
{
    uim_buf_t buf;
    long lines = 0;
    buf.data = g_payload;
    buf.cap = sizeof g_payload;
    buf.len = 0;
    if (!fn(p->model, &buf)) {
        p->opened = p->opened && !poisons;
        return reply_plain(name, false);
    }
    if (buf.len > buf.cap) {
        return reply_err(name, "model-contract");
    }
    lines = probe_check_records(spec, g_payload, buf.len);
    return lines < 0 ? reply_err(name, "model-contract") : reply_lines(name, (size_t)lines, buf.len);
}

static bool cmd_semantic(probe_t *p, char **arg)
{
    (void)arg;
    return buffer_reply(p, "semantic", uim_semantic, &PROBE_SPEC_SEMANTIC, false);
}

static bool cmd_patches(probe_t *p, char **arg)
{
    (void)arg;
    return buffer_reply(p, "patches", uim_patches, &PROBE_SPEC_PATCHES, true);
}

static bool cmd_trace(probe_t *p, char **arg)
{
    (void)arg;
    return buffer_reply(p, "trace", uim_trace, &PROBE_SPEC_TRACE, true);
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
        return reply_err("domain-at", "bad-arguments");
    }
    if (!uim_domain_at(p->model, (uint16_t)i)) {
        p->opened = false;
        return reply_plain("domain-at", false);
    }
    return reply_plain("domain-at", true);
}

static bool cmd_quit(probe_t *p, char **arg)
{
    (void)arg;
    p->quit = true;
    return fits(snprintf(g_reply, sizeof g_reply, "ok quit"));
}

static const command_t g_commands[] = {
    {"open", 2, false, cmd_open},
    {"env-inputs", 0, true, cmd_env_inputs},
    {"apply", 4, true, cmd_apply},
    {"next-due", 0, true, cmd_next_due},
    {"advance", 1, true, cmd_advance},
    {"frame", 0, true, cmd_frame},
    {"semantic", 0, true, cmd_semantic},
    {"patches", 0, true, cmd_patches},
    {"domain-count", 0, false, cmd_domain_count},
    {"domain-at", 1, true, cmd_domain_at},
    {"trace", 0, true, cmd_trace},
    {"quit", 0, false, cmd_quit},
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
    char *tok[PROBE_TOKENS];
    size_t i = 0;
    int n = split(tok, PROBE_TOKENS);
    g_tail_len = 0;
    if (n < 0) {
        return reply_err("?", "malformed");
    }
    for (i = 0; i < sizeof g_commands / sizeof g_commands[0]; i++) {
        const command_t *c = &g_commands[i];
        bool good = false;
        if (strcmp(tok[0], c->name) != 0) {
            continue;
        }
        if ((size_t)n - 1u != c->argc) {
            return reply_err(c->name, "bad-arguments");
        }
        if (c->needs_open && !p->opened) {
            return reply_err(c->name, "not-open");
        }
        good = c->run(p, tok + 1);
        if (!good && strncmp(g_reply, "err ", 4) != 0) {
            return reply_err(c->name, "internal");
        }
        return good;
    }
    return reply_err("?", "unknown-command");
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

typedef enum { RL_LINE, RL_EOF, RL_PARTIAL, RL_LONG } read_t;

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
    p->errors++;
    (void)reply_err("?", why);
    return emit();
}

/* After `quit`: anything but empty lines until EOF is an error (one reply, every line counted). */
static bool drain(probe_t *p)
{
    bool told = false;
    read_t got = RL_LINE;
    while ((got = read_line()) != RL_EOF) {
        if (g_line_len == 0 && got == RL_LINE) {
            continue;
        }
        if (!told) {
            told = true;
            if (!refuse(p, "after-quit")) {
                return false;
            }
        } else {
            p->errors++;
        }
    }
    return true;
}

static bool serve(probe_t *p)
{
    while (!p->quit) {
        read_t got = read_line();
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
            p->errors++;
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
    p.model = uim_instance();
    p.opened = false;
    p.quit = false;
    p.errors = 0;
    p.origin = 0;
    p.now = 0;
    g_tail_len = 0;
    if (p.model == NULL || !fits(snprintf(g_reply, sizeof g_reply, "ui-probe/1 ready")) || !emit()) {
        return 2;
    }
    if (!serve(&p)) {
        return 2;
    }
    return p.errors == 0 ? 0 : 1;
}
