/* The gate-owned `main` of a UI probe binary (P004 4.2; protocol: docs/ui-model.md, "ui-probe/1").
 *
 * Reads one command per line on stdin and writes exactly one reply line per command on stdout. Strict: an unknown or
 * malformed command is answered with an `err` line, counted, and the exit status is 1 at the end. Model failures are
 * ordinary replies (`fail <command>`) and do not count. Static memory only; no recursion; no allocation. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "ui/model/model.h"

enum {
    PROBE_LINE_MAX = 512,
    PROBE_TOKENS = 8,
    PROBE_REPLY_MAX = 2 * UIM_BUF_MAX + 64
};

typedef struct {
    uim_t *model;
    bool opened;
    bool quit;
    unsigned errors;
} probe_t;

typedef bool (*handler_t)(probe_t *p, char **arg, size_t argc);

typedef struct {
    const char *name;
    size_t argc;
    bool needs_open;
    handler_t run;
} command_t;

static char g_line[PROBE_LINE_MAX + 2];
static char g_reply[PROBE_REPLY_MAX];
static char g_payload[UIM_BUF_MAX];
static uim_input_t g_inputs[UIM_ENV_MAX];

/* ---- replies ------------------------------------------------------------------------------------------------- */

static bool say(const char *text)
{
    size_t n = strlen(text);
    if (n >= sizeof g_reply) {
        return false;
    }
    memcpy(g_reply, text, n + 1u);
    return true;
}

static bool reply_err(const char *name, const char *why)
{
    int n = snprintf(g_reply, sizeof g_reply, "err %s %s", name, why);
    if (n < 0 || (size_t)n >= sizeof g_reply) {
        (void)say("err internal");
    }
    return false;
}

static bool reply_ok(const char *fmt_name, unsigned long long value)
{
    int n = snprintf(g_reply, sizeof g_reply, "ok %s %llu", fmt_name, value);
    return n > 0 && (size_t)n < sizeof g_reply;
}

static bool reply_plain(const char *name, bool good)
{
    int n = snprintf(g_reply, sizeof g_reply, "%s %s", good ? "ok" : "fail", name);
    return n > 0 && (size_t)n < sizeof g_reply;
}

/* ---- strict number and hex parsing -------------------------------------------------------------------------- */

static bool parse_u64(const char *s, uint64_t *out)
{
    uint64_t v = 0;
    size_t i = 0;
    if (s[0] == '\0' || strlen(s) > 20u) {
        return false;
    }
    for (i = 0; s[i] != '\0'; i++) {
        uint64_t d = 0;
        if (s[i] < '0' || s[i] > '9') {
            return false;
        }
        d = (uint64_t)(s[i] - '0');
        if (v > (UINT64_MAX - d) / 10u) {
            return false;
        }
        v = v * 10u + d;
    }
    if (s[0] == '0' && s[1] != '\0') {
        return false;
    }
    *out = v;
    return true;
}

static bool parse_i32(const char *s, int32_t *out)
{
    uint64_t mag = 0;
    bool neg = s[0] == '-';
    if (!parse_u64(neg ? s + 1 : s, &mag) || mag > (neg ? 2147483648u : 2147483647u)) {
        return false;
    }
    *out = neg ? (int32_t)(-(int64_t)mag) : (int32_t)mag;
    return true;
}

static int hex_digit(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    return (c >= 'a' && c <= 'f') ? c - 'a' + 10 : -1;
}

/* `-` is the empty text; otherwise lowercase hex of the bytes, each printable ASCII. */
static bool parse_text(const char *s, char *out)
{
    size_t n = strlen(s);
    size_t i = 0;
    if (strcmp(s, "-") == 0) {
        out[0] = '\0';
        return true;
    }
    if (n == 0 || n % 2u != 0 || n / 2u > UIM_TEXT_MAX) {
        return false;
    }
    for (i = 0; i < n / 2u; i++) {
        int hi = hex_digit(s[2u * i]);
        int lo = hex_digit(s[2u * i + 1u]);
        int b = hi * 16 + lo;
        if (hi < 0 || lo < 0 || b < 0x20 || b > 0x7e) {
            return false;
        }
        out[i] = (char)b;
    }
    out[n / 2u] = '\0';
    return true;
}

static void to_hex(const unsigned char *bytes, size_t n, char *out)
{
    static const char digits[] = "0123456789abcdef";
    size_t i = 0;
    for (i = 0; i < n; i++) {
        out[2u * i] = digits[bytes[i] >> 4];
        out[2u * i + 1u] = digits[bytes[i] & 15u];
    }
    out[2u * n] = '\0';
}

static bool append_hex(size_t at, const unsigned char *bytes, size_t n)
{
    if (at + 2u * n >= sizeof g_reply) {
        return false;
    }
    to_hex(bytes, n, g_reply + at);
    return true;
}

/* ---- handlers ------------------------------------------------------------------------------------------------ */

static bool cmd_open(probe_t *p, char **arg, size_t argc)
{
    uint64_t origin = 0;
    uint64_t seed = 0;
    (void)argc;
    if (!parse_u64(arg[0], &origin) || !parse_u64(arg[1], &seed)) {
        return reply_err("open", "bad-arguments");
    }
    p->opened = uim_open(p->model, origin, seed);
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

static bool cmd_env_inputs(probe_t *p, char **arg, size_t argc)
{
    uint16_t n = uim_env_inputs(p->model, g_inputs, (uint16_t)UIM_ENV_MAX);
    size_t at = 0;
    size_t i = 0;
    int w = 0;
    (void)arg;
    (void)argc;
    if (n > UIM_ENV_MAX) {
        return reply_plain("env-inputs", false);
    }
    w = snprintf(g_reply, sizeof g_reply, "ok env-inputs %u", (unsigned)n);
    at = w > 0 ? (size_t)w : sizeof g_reply;
    for (i = 0; i < n && at < sizeof g_reply; i++) {
        const uim_input_t *in = &g_inputs[i];
        size_t len = text_len(in->text);
        char hex[2u * UIM_TEXT_MAX + 2u] = "-";
        if (len > UIM_TEXT_MAX) {
            return reply_plain("env-inputs", false);
        }
        if (len > 0) {
            to_hex((const unsigned char *)in->text, len, hex);
        }
        w = snprintf(g_reply + at, sizeof g_reply - at, " %u:%lu:%ld:%s", (unsigned)in->kind,
                     (unsigned long)in->id, (long)in->arg, hex);
        at = w > 0 ? at + (size_t)w : sizeof g_reply;
    }
    return at < sizeof g_reply;
}

static bool cmd_apply(probe_t *p, char **arg, size_t argc)
{
    uim_input_t in;
    uint64_t kind = 0;
    uint64_t id = 0;
    (void)argc;
    memset(&in, 0, sizeof in);
    if (!parse_u64(arg[0], &kind) || kind < UIM_IN_ENV || kind > UIM_IN_INTENT || !parse_u64(arg[1], &id) ||
        id > UINT32_MAX || !parse_i32(arg[2], &in.arg) || !parse_text(arg[3], in.text)) {
        return reply_err("apply", "bad-arguments");
    }
    in.kind = (uint16_t)kind;
    in.id = (uint32_t)id;
    return reply_plain("apply", uim_apply(p->model, &in));
}

static bool cmd_next_due(probe_t *p, char **arg, size_t argc)
{
    uint64_t due = uim_next_due(p->model);
    (void)arg;
    (void)argc;
    if (due == UIM_NO_DEADLINE) {
        return say("ok next-due none");
    }
    return reply_ok("next-due", due);
}

static bool cmd_advance(probe_t *p, char **arg, size_t argc)
{
    uint64_t to = 0;
    (void)argc;
    if (!parse_u64(arg[0], &to)) {
        return reply_err("advance", "bad-arguments");
    }
    return reply_plain("advance", uim_advance(p->model, to));
}

/* SEAM(U05): the one place where `lvprobe` joins the probe. After `uim_frame` produced `disp`, U05 appends the
 * facts of the frame (tree, ink, hit table, CRC) to the reply of `frame` here. Today it adds nothing. */
static size_t seam_frame_facts(struct _lv_display_t *disp, char *out, size_t cap)
{
    (void)disp;
    (void)out;
    (void)cap;
    return 0;
}

static bool cmd_frame(probe_t *p, char **arg, size_t argc)
{
    struct _lv_display_t *disp = NULL;
    size_t at = 0;
    int w = 0;
    (void)arg;
    (void)argc;
    if (!uim_frame(p->model, &disp)) {
        return reply_plain("frame", false);
    }
    w = snprintf(g_reply, sizeof g_reply, "ok frame %d", disp != NULL ? 1 : 0);
    at = w > 0 ? (size_t)w : sizeof g_reply;
    if (at >= sizeof g_reply) {
        return false;
    }
    at += seam_frame_facts(disp, g_reply + at, sizeof g_reply - at);
    return at < sizeof g_reply;
}

/* `semantic`, `patches` and `trace`: `ok <name> <len> <hex of the bytes>`. */
static bool buffer_reply(const char *name, bool (*fn)(uim_t *, uim_buf_t *), probe_t *p)
{
    uim_buf_t buf;
    int w = 0;
    buf.data = g_payload;
    buf.cap = sizeof g_payload;
    buf.len = 0;
    if (!fn(p->model, &buf) || buf.len > buf.cap) {
        return reply_plain(name, false);
    }
    w = snprintf(g_reply, sizeof g_reply, "ok %s %zu ", name, buf.len);
    if (w < 0 || (size_t)w >= sizeof g_reply) {
        return false;
    }
    return append_hex((size_t)w, (const unsigned char *)g_payload, buf.len);
}

static bool cmd_semantic(probe_t *p, char **arg, size_t argc)
{
    (void)arg;
    (void)argc;
    return buffer_reply("semantic", uim_semantic, p);
}

static bool cmd_patches(probe_t *p, char **arg, size_t argc)
{
    (void)arg;
    (void)argc;
    return buffer_reply("patches", uim_patches, p);
}

static bool cmd_trace(probe_t *p, char **arg, size_t argc)
{
    (void)arg;
    (void)argc;
    return buffer_reply("trace", uim_trace, p);
}

static bool cmd_domain_count(probe_t *p, char **arg, size_t argc)
{
    (void)p;
    (void)arg;
    (void)argc;
    return reply_ok("domain-count", uim_domain_count());
}

static bool cmd_domain_at(probe_t *p, char **arg, size_t argc)
{
    uint64_t i = 0;
    (void)argc;
    if (!parse_u64(arg[0], &i) || i > UINT16_MAX) {
        return reply_err("domain-at", "bad-arguments");
    }
    return reply_plain("domain-at", uim_domain_at(p->model, (uint16_t)i));
}

static bool cmd_quit(probe_t *p, char **arg, size_t argc)
{
    (void)arg;
    (void)argc;
    p->quit = true;
    return say("ok quit");
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

/* Splits `line` in place on single spaces. -1 if it is malformed (empty token, too many tokens, or a byte that is not
 * printable ASCII), else the token count. */
static int split(char *line, char **tok, size_t max)
{
    size_t n = 0;
    size_t i = 0;
    bool start = true;
    if (line[0] == '\0') {
        return -1;
    }
    for (i = 0; line[i] != '\0'; i++) {
        unsigned char c = (unsigned char)line[i];
        if (c < 0x20 || c > 0x7e) {
            return -1;
        }
        if (c == ' ') {
            if (start) {
                return -1;
            }
            line[i] = '\0';
            start = true;
        } else if (start) {
            if (n == max) {
                return -1;
            }
            tok[n++] = &line[i];
            start = false;
        }
    }
    return start ? -1 : (int)n;
}

static bool dispatch(probe_t *p, char *line)
{
    char *tok[PROBE_TOKENS];
    size_t i = 0;
    int n = split(line, tok, PROBE_TOKENS);
    if (n < 0) {
        return reply_err("?", "malformed");
    }
    for (i = 0; i < sizeof g_commands / sizeof g_commands[0]; i++) {
        const command_t *c = &g_commands[i];
        if (strcmp(tok[0], c->name) != 0) {
            continue;
        }
        if ((size_t)n - 1u != c->argc) {
            return reply_err(c->name, "bad-arguments");
        }
        if (c->needs_open && !p->opened) {
            return reply_err(c->name, "not-open");
        }
        return c->run(p, tok + 1, c->argc);
    }
    return reply_err("?", "unknown-command");
}

static bool emit(void)
{
    return fputs(g_reply, stdout) >= 0 && fputc('\n', stdout) != EOF && fflush(stdout) == 0;
}

/* Reads one line into g_line without its end. 1: a line; 0: EOF; -1: too long (the rest of the line is dropped). */
static int read_line(void)
{
    size_t n = 0;
    int c = 0;
    bool too_long = false;
    for (;;) {
        c = fgetc(stdin);
        if (c == EOF) {
            return n == 0 && !too_long ? 0 : (too_long ? -1 : 1);
        }
        if (c == '\n') {
            break;
        }
        if (n < PROBE_LINE_MAX) {
            g_line[n++] = (char)c;
        } else {
            too_long = true;
        }
    }
    g_line[n] = '\0';
    return too_long ? -1 : 1;
}

int main(void)
{
    probe_t p;
    int got = 0;
    p.model = uim_instance();
    p.opened = false;
    p.quit = false;
    p.errors = 0;
    if (p.model == NULL || !say("ui-probe/1 ready") || !emit()) {
        return 2;
    }
    while (!p.quit) {
        got = read_line();
        if (got == 0) {
            (void)reply_err("?", "eof-without-quit");
            p.errors++;
            break;
        }
        if (got < 0) {
            (void)reply_err("?", "line-too-long");
            p.errors++;
        } else if (!dispatch(&p, g_line)) {
            p.errors++;
        }
        if (!emit()) {
            return 2;
        }
    }
    if (got == 0 && !emit()) {
        return 2;
    }
    return p.errors == 0 ? 0 : 1;
}
