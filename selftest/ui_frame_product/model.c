/* The model adapter of the frame toy (selftest/ui_frame.sh): implements ui/model/model.h on top of app.h.
 * Intents: 1 press the button (through the app's pointer: UIM_MISSED when the overlay takes the tap), 2 and 3 make the
 * overlay clickable or not, 4 and 5 squeeze the fit label or give it room, 6 adds APP_MANY labels (a frame too large for
 * one reply), 7 adds one label and 8 deletes it (lifecycle events). No env input, no timer. The trace carries the input
 * handlers' events, so a hit query that fires nothing leaves it empty. */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_frame_product/app.h"
#include "ui/model/model.h"

enum { LOG_MAX = 4096, LINE = 160 };

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

/* The handlers' events, in the order they fired. */
static bool handler_events(uim_t *m)
{
    static const char *const names[] = {"button_pressed", "button_clicked", "overlay_pressed", "overlay_clicked"};
    app_event_t e;
    while (app_take_event(&e)) {
        if (!event(m, names[e])) {
            return false;
        }
    }
    return true;
}

bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed)
{
    (void)seed;
    m->open = false;
    m->seq = 0;
    m->trace_len = 0;
    m->now = clock_origin_ms;
    m->open = app_start() && event(m, "boot");
    return m->open;
}

bool uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap, uint16_t *count)
{
    (void)out;
    (void)cap;
    *count = 0;
    return m->open;
}

static uim_result_t press(uim_t *m)
{
    bool clicked = app_press();
    if (!handler_events(m)) {
        return UIM_ERROR;
    }
    if (!clicked) {
        return UIM_MISSED;
    }
    app_show_notice();
    app_draw();
    return event(m, "press") ? UIM_OK : UIM_ERROR;
}

static uim_result_t change(unsigned id)
{
    if (id == 2u || id == 3u) {
        app_cover(id == 2u);
    } else if (id == 4u || id == 5u) {
        app_fit(id == 5u);
    } else if (id == 6u) {
        return app_many() ? UIM_OK : UIM_ERROR;
    } else if (id == 7u) {
        return app_add() ? UIM_OK : UIM_REFUSED;
    } else {
        app_drop();
    }
    return UIM_OK;
}

uim_result_t uim_apply(uim_t *m, const uim_input_t *in)
{
    uim_result_t r = UIM_REFUSED;
    if (!m->open) {
        return UIM_ERROR;
    }
    if (in->kind != UIM_IN_INTENT || in->id < 1u || in->id > 8u) {
        return UIM_REFUSED;
    }
    r = in->id == 1u ? press(m) : change(in->id);
    if (r == UIM_OK && in->id != 1u) {
        app_draw();
    }
    return r;
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
    app_step(ms);
    m->now += ms;
    return true;
}

bool uim_frame(uim_t *m, struct _lv_display_t **disp)
{
    if (!m->open) {
        return false;
    }
    app_draw();
    *disp = app_display();
    return *disp != NULL;
}

/* key, role, label (escaped by the record grammar: the Bulgarian notice byte by byte), x, y, w, h, enabled, intent:arg,
 * flags, style, importance, input_policy, wrap_policy. */
static bool node_line(unsigned i, uim_buf_t *out)
{
    app_node_t node;
    char text[LINE];
    size_t at = 0;
    size_t k = 0;
    int n = 0;
    text[0] = '\0';
    if (!app_node(i, &node)) {
        return false;
    }
    for (k = 0; node.text[k] != '\0' && at + 5u < sizeof text; k++) {
        unsigned char c = (unsigned char)node.text[k];
        n = (c < 0x20u || c > 0x7eu) ? snprintf(text + at, sizeof text - at, "\\x%02x", (unsigned)c)
            : c == '\\' ? snprintf(text + at, sizeof text - at, "\\\\")
                         : snprintf(text + at, sizeof text - at, "%c", (char)c);
        at += n > 0 ? (size_t)n : 0u;
    }
    if (node.text[k] != '\0') {
        return false;
    }
    n = snprintf(out->data + out->len, out->cap - out->len, "%s\t%s\t%s\t%d\t%d\t%d\t%d\t1\t%s\t%s\tbody\tnormal\t%s\tnone\n",
                 node.key, i == 1u ? "button" : "label", text, (int)node.x, (int)node.y, (int)node.w, (int)node.h,
                 i == 1u ? "1:0" : "-", node.hidden ? "hidden" : "-", i == 1u ? "tap" : "none");
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
    for (i = 0; i < APP_NODES && m->open; i++) {
        if (!node_line(i, out)) {
            return false;
        }
    }
    return m->open;
}

bool uim_patches(uim_t *m, uim_buf_t *out)
{
    out->len = 0;
    return m->open;
}

bool uim_trace(uim_t *m, uim_buf_t *out)
{
    if (!m->open || !handler_events(m) || m->trace_len > out->cap) {
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
