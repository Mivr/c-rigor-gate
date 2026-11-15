/* The model adapter of the toy app: implements ui/model/model.h on top of toy.h. */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_product/toy.h"
#include "ui/model/model.h"

enum { LOG_MAX = 1024, INTENT_PRESS = 1, ENV_OFFLINE = 1 };

struct uim {
    bool open;
    uint64_t now;
    uint64_t seed;
    char patches[LOG_MAX];
    size_t patches_len;
    char trace[LOG_MAX];
    size_t trace_len;
};

static struct uim g_model;

/* Appends `line` and a newline to a log; false if it does not fit. */
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

uim_t *uim_instance(void)
{
    return &g_model;
}

bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed)
{
    m->open = false;
    m->patches_len = 0;
    m->trace_len = 0;
    if (!toy_start()) {
        return false;
    }
    m->now = clock_origin_ms;
    m->seed = seed;
    m->open = true;
    return log_add(m->patches, &m->patches_len, "create screen label:Toy button:Press label:notice(hidden)") &&
           log_add(m->trace, &m->trace_len, "boot");
}

uint16_t uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap)
{
    if (!m->open || cap < 1u) {
        return 0;
    }
    memset(&out[0], 0, sizeof out[0]);
    out[0].kind = UIM_IN_ENV;
    out[0].id = ENV_OFFLINE;
    return 1;
}

static bool show(uim_t *m, const char *text)
{
    toy_show_notice(text, m->now);
    toy_draw();
    return log_add(m->patches, &m->patches_len, "show notice");
}

bool uim_apply(uim_t *m, const uim_input_t *in)
{
    char line[UIM_TEXT_MAX + 16u];
    if (!m->open) {
        return false;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_PRESS) {
        toy_press();
        return toy_take_press() && show(m, "Pressed") && log_add(m->trace, &m->trace_len, "press");
    }
    if (in->kind == UIM_IN_ENV && in->id == ENV_OFFLINE) {
        return show(m, "Offline") && log_add(m->trace, &m->trace_len, "env offline");
    }
    if (in->kind == UIM_IN_LINE) {
        int n = snprintf(line, sizeof line, "line %s", in->text);
        return n > 0 && (size_t)n < sizeof line && log_add(m->trace, &m->trace_len, line);
    }
    return false;
}

uint64_t uim_next_due(const uim_t *m)
{
    return m->open ? toy_notice_due() : UIM_NO_DEADLINE;
}

/* One frame step, at most UIM_FRAME_MS and never past the deadline or `to`. */
static uint32_t frame_len(const uim_t *m, uint64_t to)
{
    uint64_t left = to - m->now;
    uint64_t due = toy_notice_due();
    uint64_t len = left < UIM_FRAME_MS ? left : UIM_FRAME_MS;
    if (due != UIM_NO_DEADLINE && due > m->now && due - m->now < len) {
        len = due - m->now;
    }
    return (uint32_t)len;
}

bool uim_advance(uim_t *m, uint64_t to_ms)
{
    if (!m->open || to_ms < m->now) {
        return false;
    }
    while (m->now < to_ms) {
        uint32_t len = frame_len(m, to_ms);
        toy_step(len);
        m->now += len;
        if (toy_notice_due() != UIM_NO_DEADLINE && m->now >= toy_notice_due()) {
            toy_hide_notice();
            if (!log_add(m->patches, &m->patches_len, "hide notice") ||
                !log_add(m->trace, &m->trace_len, "notice timeout")) {
                return false;
            }
        }
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

bool uim_semantic(uim_t *m, uim_buf_t *out)
{
    int n = 0;
    if (!m->open) {
        return false;
    }
    n = snprintf(out->data, out->cap, "label %s\nbutton %s intent=%d\nnotice %s %s\n", toy_title(),
                 toy_button_text(), INTENT_PRESS, toy_notice_shown() ? "shown" : "hidden", toy_notice_text());
    if (n < 0 || (size_t)n >= out->cap) {
        return false;
    }
    out->len = (size_t)n;
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
    } else {
        toy_show_notice("Pressed", m->now);
    }
    toy_draw();
    return true;
}
