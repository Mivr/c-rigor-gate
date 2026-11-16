/* The model adapter of the canary app (selftest/ui_judges.sh): implements ui/model/model.h on top of canary.h.
 * Intent v (1..CANARY_VARIANTS-1, arg 0) rebuilds the scene as variant v; intent 0 the clean scene. The semantic records
 * are the scene table in the vocabulary of docs/ui-judges.md (that of the real lockers adapter): rects in display
 * pixels, structural roles, flag letters, numeric style tokens. No deadline, no env input. */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_canary_product/canary.h"
#include "ui/model/model.h"

enum { LOG_MAX = 1024, LINE = 256 };

struct uim {
    bool open;
    uint64_t now;
    uint64_t seq;
    char trace[LOG_MAX];
    size_t trace_len;
};

static struct uim g_model;

uim_t *uim_instance(void)
{
    return &g_model;
}

static bool event(uim_t *m, const char *type)
{
    char line[LINE];
    int n = snprintf(line, sizeof line, "%llu\t%s\t%llu\n", (unsigned long long)m->seq, type, (unsigned long long)m->now);
    if (n <= 0 || (size_t)n >= sizeof line || m->trace_len + (size_t)n > LOG_MAX) {
        return false;
    }
    memcpy(m->trace + m->trace_len, line, (size_t)n);
    m->trace_len += (size_t)n;
    m->seq++;
    return true;
}

bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed)
{
    (void)seed;
    m->open = false;
    m->seq = 0;
    m->trace_len = 0;
    if (!canary_start()) {
        return false;
    }
    m->now = clock_origin_ms;
    m->open = event(m, "boot");
    return m->open;
}

bool uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap, uint16_t *count)
{
    (void)out;
    (void)cap;
    *count = 0;
    return m->open;
}

uim_result_t uim_apply(uim_t *m, const uim_input_t *in)
{
    if (!m->open) {
        return UIM_ERROR;
    }
    if (in->kind != UIM_IN_INTENT || in->arg != 0 || in->id >= CANARY_VARIANTS) {
        return UIM_REFUSED;
    }
    return canary_show(in->id) && event(m, "variant") ? UIM_OK : UIM_ERROR;
}

uim_result_t uim_settle(uim_t *m, bool *worked)
{
    *worked = false;
    return m->open ? UIM_OK : UIM_ERROR;
}

uint64_t uim_next_due(const uim_t *m)
{
    (void)m;
    return UIM_NO_DEADLINE;
}

bool uim_step(uim_t *m, uint32_t ms)
{
    if (!m->open || ms < 1u || ms > UIM_FRAME_MS) {
        return false;
    }
    canary_step(ms);
    m->now += ms;
    return true;
}

bool uim_frame(uim_t *m, struct _lv_display_t **disp)
{
    if (!m->open) {
        return false;
    }
    canary_draw();
    *disp = canary_display();
    return *disp != NULL;
}

/* Escapes `in` into `out` by the record grammar of model.h; false if it does not fit. */
static bool escape(char *out, size_t cap, const char *in)
{
    size_t at = 0;
    for (; *in != '\0'; in++) {
        unsigned char c = (unsigned char)*in;
        int n = (c < 0x20u || c > 0x7eu) ? snprintf(out + at, cap - at, "\\x%02x", (unsigned)c)
                : c == '\\' ? snprintf(out + at, cap - at, "\\\\")
                            : snprintf(out + at, cap - at, "%c", (char)c);
        if (n <= 0 || at + (size_t)n >= cap) {
            return false;
        }
        at += (size_t)n;
    }
    out[at] = '\0';
    return true;
}

/* key, role, label, x, y, w, h, enabled, intent:arg, flags, style token, and `-` for importance, input_policy and
 * wrap_policy (the judges take them from the contract), as the real lockers adapter writes them. */
static bool node_line(unsigned i, uim_buf_t *out)
{
    canary_node_t node;
    char text[LINE / 2];
    int n = 0;
    if (!canary_node(i, &node) || !escape(text, sizeof text, node.text)) {
        return false;
    }
    n = snprintf(out->data + out->len, out->cap - out->len, "%s\t%s\t%s\t%d\t%d\t%d\t%d\t%d\t%s\t%s\t%u\t-\t-\t-\n",
                 node.key, node.role, text, (int)node.x, (int)node.y, (int)node.w, (int)node.h, node.enabled ? 1 : 0,
                 node.intent, node.flags, node.token);
    if (n <= 0 || (size_t)n >= out->cap - out->len) {
        return false;
    }
    out->len += (size_t)n;
    return true;
}

bool uim_semantic(uim_t *m, uim_buf_t *out)
{
    unsigned i;
    out->len = 0;
    if (!m->open) {
        return false;
    }
    for (i = 0; i < canary_count(); i++) {
        if (!node_line(i, out)) {
            return false;
        }
    }
    return true;
}

bool uim_patches(uim_t *m, uim_buf_t *out)
{
    out->len = 0;
    return m->open;
}

bool uim_trace(uim_t *m, uim_buf_t *out)
{
    if (!m->open || m->trace_len > out->cap) {
        return false;
    }
    memcpy(out->data, m->trace, m->trace_len);
    out->len = m->trace_len;
    m->trace_len = 0;
    return true;
}

uint16_t uim_domain_count(void)
{
    return 0;
}

bool uim_domain_at(uim_t *m, uint16_t i)
{
    (void)m;
    (void)i;
    return false;
}
