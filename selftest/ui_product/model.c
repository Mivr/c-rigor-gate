/* The model adapter of the toy app: implements ui/model/model.h on top of toy.h.
 * The fixture has two deliberately broken inputs so the selftest can see the probe's rules: INTENT_BROKEN makes uim_apply
 * fail (the session is poisoned), INTENT_BAD_RECORD writes a trace record that breaks the record grammar (model-contract). */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_product/toy.h"
#include "ui/model/model.h"

enum { LOG_MAX = 2048, INTENT_PRESS = 1, INTENT_BROKEN = 666, INTENT_BAD_RECORD = 667, ENV_OFFLINE = 1, LINE_MAX_BYTES = 160 };

struct uim {
    bool open;
    uint64_t now;
    uint64_t seed;
    uint64_t seq;
    char patches[LOG_MAX];
    size_t patches_len;
    char trace[LOG_MAX];
    size_t trace_len;
};

static struct uim g_model;

/* Appends `line` and an LF to a log; false if it does not fit. */
static bool log_add(char *log, size_t *len, const char *line)
{
    size_t n = strlen(line);
    if (*len + n + 1u > LOG_MAX) {
        return false;
    }
    memcpy(log + *len, line, n);
    log[*len + n] = '\n';
    *len += n + 1u;
    return true;
}

static bool log_take(char *log, size_t *len, uim_buf_t *out)
{
    if (*len > out->cap) {
        return false;
    }
    memcpy(out->data, log, *len);
    out->len = *len;
    *len = 0;
    return true;
}

/* Escapes `in` into `out` by the record grammar of model.h. */
static bool escape(char *out, size_t cap, const char *in)
{
    size_t at = 0;
    for (; *in != '\0'; in++) {
        unsigned char c = (unsigned char)*in;
        int n = 0;
        if (c == '\\') {
            n = snprintf(out + at, cap - at, "\\\\");
        } else if (c == '\t') {
            n = snprintf(out + at, cap - at, "\\t");
        } else if (c == '\n') {
            n = snprintf(out + at, cap - at, "\\n");
        } else if (c < 0x20 || c > 0x7e) {
            n = snprintf(out + at, cap - at, "\\x%02x", (unsigned)c);
        } else if (at + 1u < cap) {
            out[at] = (char)c;
            out[at + 1u] = '\0';
            n = 1;
        }
        if (n <= 0 || at + (size_t)n >= cap) {
            return false;
        }
        at += (size_t)n;
    }
    out[at] = '\0';
    return true;
}

uim_t *uim_instance(void)
{
    return &g_model;
}

/* One patch record: op, key, field, old, new. */
static bool patch(uim_t *m, const char *op, const char *key, const char *field, const char *from, const char *to)
{
    char line[LINE_MAX_BYTES];
    int n = snprintf(line, sizeof line, "%s\t%s\t%s\t%s\t%s", op, key, field, from, to);
    return n > 0 && (size_t)n < sizeof line && log_add(m->patches, &m->patches_len, line);
}

/* One trace record: seq, type, mono_ms. */
static bool event(uim_t *m, const char *type)
{
    char line[LINE_MAX_BYTES];
    int n = snprintf(line, sizeof line, "%llu\t%s\t%llu", (unsigned long long)m->seq, type, (unsigned long long)m->now);
    m->seq++;
    return n > 0 && (size_t)n < sizeof line && log_add(m->trace, &m->trace_len, line);
}

bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed)
{
    m->open = false;
    m->patches_len = 0;
    m->trace_len = 0;
    m->seq = 0;
    if (!toy_start()) {
        return false;
    }
    m->now = clock_origin_ms;
    m->seed = seed;
    m->open = patch(m, "create", "screen", "-", "-", "-") && patch(m, "create", "title", "text", "-", "Toy") &&
              patch(m, "create", "button", "text", "-", "Press") && patch(m, "create", "notice", "hidden", "-", "1") &&
              event(m, "boot");
    return m->open;
}

bool uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap, uint16_t *count)
{
    *count = 0;
    if (!m->open) {
        return false;
    }
    if (cap >= 1u) {
        memset(&out[0], 0, sizeof out[0]);
        out[0].kind = UIM_IN_ENV;
        out[0].id = ENV_OFFLINE;
        *count = 1;
    }
    return true;
}

static bool show(uim_t *m, const char *text)
{
    toy_show_notice(text, m->now);
    toy_draw();
    return patch(m, "set", "notice", "hidden", "1", "0");
}

uim_result_t uim_apply(uim_t *m, const uim_input_t *in)
{
    if (!m->open || (in->kind == UIM_IN_INTENT && in->id == INTENT_BROKEN)) {
        return UIM_ERROR;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_BAD_RECORD) {
        return log_add(m->trace, &m->trace_len, "a record without tabs") ? UIM_OK : UIM_ERROR;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_PRESS && !toy_notice_shown()) {
        toy_press();
        return toy_take_press() && show(m, "Pressed") && event(m, "press") ? UIM_OK : UIM_ERROR;
    }
    if (in->kind == UIM_IN_ENV && in->id == ENV_OFFLINE && !toy_notice_shown()) {
        return show(m, "Offline") && event(m, "env_offline") ? UIM_OK : UIM_ERROR;
    }
    if (in->kind == UIM_IN_LINE && in->text[0] != '\0') {
        return event(m, "line") ? UIM_OK : UIM_ERROR;
    }
    return UIM_REFUSED;
}

uint64_t uim_next_due(const uim_t *m)
{
    return m->open ? toy_notice_due() : UIM_NO_DEADLINE;
}

bool uim_step(uim_t *m, uint32_t ms)
{
    if (!m->open || ms < 1u || ms > UIM_FRAME_MS) {
        return false;
    }
    toy_step(ms);
    m->now += ms;
    if (toy_notice_due() != UIM_NO_DEADLINE && m->now >= toy_notice_due()) {
        toy_hide_notice();
        return patch(m, "set", "notice", "hidden", "0", "1") && event(m, "notice_timeout");
    }
    return true;
}

bool uim_frame(uim_t *m, struct _lv_display_t **disp)
{
    if (!m->open) {
        return false;
    }
    toy_draw();
    *disp = toy_display();
    return *disp != NULL;
}

/* One semantic record of node `i`; false if it does not fit. */
static bool node_line(unsigned i, char *line, size_t cap)
{
    toy_node_t node;
    char text[LINE_MAX_BYTES / 4];
    int n = 0;
    if (!toy_node(i, &node) || !escape(text, sizeof text, node.text)) {
        return false;
    }
    n = snprintf(line, cap, "%s\t%s\t%s\t%d\t%d\t%d\t%d\t1\t%s\t%s\tbody\tnormal\t%s\tnone\n", node.key, node.role, text,
                 (int)node.x, (int)node.y, (int)node.w, (int)node.h, i == 1u ? "1:0" : "-", node.hidden ? "hidden" : "-",
                 i == 1u ? "tap" : "none");
    return n > 0 && (size_t)n < cap;
}

bool uim_semantic(uim_t *m, uim_buf_t *out)
{
    unsigned i = 0;
    char line[LINE_MAX_BYTES];
    out->len = 0;
    if (!m->open) {
        return false;
    }
    for (i = 0; i < TOY_NODES; i++) {
        size_t n = 0;
        if (!node_line(i, line, sizeof line) || out->len + (n = strlen(line)) > out->cap) {
            return false;
        }
        memcpy(out->data + out->len, line, n);
        out->len += n;
    }
    return true;
}

bool uim_patches(uim_t *m, uim_buf_t *out)
{
    return m->open && log_take(m->patches, &m->patches_len, out);
}

bool uim_trace(uim_t *m, uim_buf_t *out)
{
    return m->open && log_take(m->trace, &m->trace_len, out);
}

uint16_t uim_domain_count(void)
{
    return 2;
}

bool uim_domain_at(uim_t *m, uint16_t i)
{
    if (!m->open || i >= 2u) {
        return false;
    }
    if (i == 0u) {
        toy_hide_notice();
        toy_draw();
        return patch(m, "set", "notice", "hidden", "0", "1");
    }
    toy_show_notice("Pressed", m->now);
    toy_draw();
    return patch(m, "set", "notice", "hidden", "1", "0");
}
