/* The model adapter of the frame toy (selftest/ui_frame.sh): implements ui/model/model.h on top of app.h.
 * Input handlers and animation callbacks only queue work; run_work runs it (in uim_apply, uim_step and uim_settle).
 * Intents: 1 press the button through the app's pointer (UIM_MISSED when the overlay takes the tap; a press shows the
 * notice for NOTICE_MS), 2 and 3 make the overlay clickable or not, 4 and 5 squeeze the fit label or give it room, 6 adds
 * APP_MANY labels (too large for one reply), 7 adds one label and 8 deletes it (lifecycle events), 9 animates the bar
 * for ANIM_MS (a deadline; its end retitles the screen "Done"), 10 starts a 0 ms animation and returns without running
 * it (LVGL runs it at the next refresh: the frame must run the work it posts); that work retitles the screen "Half" and
 * starts a second 0 ms animation, whose work retitles it "Done" (so a frame must take its snapshot again after work). Broken on purpose: 11 frames a second
 * display, 12 frames a pointer that is no display, 13 adds a second pointer indev, 14 moves LVGL's tick from a clock, 15
 * makes this apply return a value outside the enum, 16 makes the next uim_settle return UIM_REFUSED, 17 the one after
 * it, 18 makes the uim_settle after the next move LVGL's tick itself, 19 drives LVGL's tick from a clock that moves
 * between frames (never within one command), 20 makes every uim_settle run work (it never quiets), 21 makes the next
 * uim_settle fail, 22 the one after it. `open <t> 2` starts on a
 * display larger than the probe's ink scratch. The trace carries the handlers' events too. */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_frame_product/app.h"
#include "ui/model/model.h"

enum { LOG_MAX = 4096, LINE = 160, NOTICE_MS = 3000, ANIM_MS = 100 };

struct uim {
    bool open;
    uint64_t now;
    uint64_t seq;
    uint64_t notice_due;
    uint64_t anim_due;
    bool chain;           /* the next animation's work starts another one (intent 10) */
    int frame_mode;       /* 0 the display, 11 a second display, 12 no display */
    int bad_result;       /* returned by apply 15 */
    unsigned refuse_in;   /* the uim_settle call (counting from 1) that returns UIM_REFUSED, 0 none */
    unsigned tick_in;     /* the uim_settle call that moves LVGL's tick, 0 none */
    unsigned error_in;    /* the uim_settle call that returns UIM_ERROR, 0 none */
    bool busy;            /* every uim_settle runs work (it never quiets) */
    bool rare_clock;      /* LVGL's tick comes from a clock that moves between frames */
    char trace[LOG_MAX];
    size_t trace_len;
};

static struct uim g_model;
static const int g_not_a_display[4];

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

static bool handler_events(uim_t *m)
{
    static const char *const names[] = {"button_pressed", "button_clicked", "overlay_pressed", "overlay_clicked",
                                        "pointer_clicked"};
    app_event_t e;
    while (app_take_event(&e)) {
        if (!event(m, names[e])) {
            return false;
        }
    }
    return true;
}

/* Runs the queued work at the current time; `*worked` if any ran, `*pressed` if a press did. */
static bool run_work(uim_t *m, bool *worked, bool *pressed)
{
    app_work_t w;
    *worked = false;
    *pressed = false;
    if (!handler_events(m)) {
        return false;
    }
    while (app_take_work(&w)) {
        *worked = true;
        if (w == APP_WORK_PRESS) {
            *pressed = true;
            app_show_notice(true);
            m->notice_due = m->now + NOTICE_MS;
        } else if (m->chain) {
            m->chain = false;
            app_set_title("Half");
            if (!app_animate(0)) {
                return false;
            }
        } else {
            app_set_title("Done");
            m->anim_due = UIM_NO_DEADLINE;
        }
        if (!event(m, w == APP_WORK_PRESS ? "press" : "anim_done")) {
            return false;
        }
    }
    if (*worked) {
        app_draw();
    }
    return true;
}

bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed)
{
    m->open = false;
    m->seq = 0;
    m->trace_len = 0;
    m->now = clock_origin_ms;
    m->notice_due = UIM_NO_DEADLINE;
    m->anim_due = UIM_NO_DEADLINE;
    m->chain = false;
    m->frame_mode = 0;
    m->bad_result = 0;
    m->refuse_in = 0;
    m->tick_in = 0;
    m->error_in = 0;
    m->busy = false;
    m->rare_clock = false;
    m->open = app_start(seed == 2u) && event(m, "boot");
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
    bool worked = false;
    bool pressed = false;
    app_press();
    if (!run_work(m, &worked, &pressed)) {
        return UIM_ERROR;
    }
    return pressed ? UIM_OK : UIM_MISSED;
}

static uim_result_t animate(uim_t *m, uint32_t ms)
{
    if (!app_animate(ms)) {
        return UIM_ERROR;
    }
    m->anim_due = ms > 0u ? m->now + ms : UIM_NO_DEADLINE;
    m->chain = ms == 0u;
    return UIM_OK;
}

static uim_result_t fixture(uim_t *m, unsigned id)
{
    if (id == 11u || id == 12u) {
        m->frame_mode = (int)id;
    } else if (id == 13u) {
        return app_extra_pointer() ? UIM_OK : UIM_ERROR;
    } else if (id == 14u) {
        app_moving_tick();
    } else if (id == 15u) {
        m->bad_result = 7;
        return (uim_result_t)m->bad_result;
    } else if (id == 16u || id == 17u) {
        m->refuse_in = id - 15u;
    } else if (id == 18u) {
        m->tick_in = 2;
    } else if (id == 19u) {
        m->rare_clock = true;
        app_rare_clock();
    } else {
        m->busy = id == 20u;
        m->error_in = id == 20u ? 0u : id - 20u;
    }
    return UIM_OK;
}

static uim_result_t change(uim_t *m, unsigned id)
{
    if (id == 2u || id == 3u) {
        app_cover(id == 2u);
    } else if (id == 4u || id == 5u) {
        app_fit(id == 5u);
    } else if (id == 6u) {
        return app_many() ? UIM_OK : UIM_ERROR;
    } else if (id == 7u) {
        return app_add() ? UIM_OK : UIM_REFUSED;
    } else if (id == 8u) {
        app_drop();
    } else if (id == 9u || id == 10u) {
        return animate(m, id == 9u ? ANIM_MS : 0u);
    } else {
        return fixture(m, id);
    }
    return UIM_OK;
}

uim_result_t uim_apply(uim_t *m, const uim_input_t *in)
{
    uim_result_t r = UIM_REFUSED;
    if (!m->open) {
        return UIM_ERROR;
    }
    if (in->kind != UIM_IN_INTENT || in->id < 1u || in->id > 22u) {
        return UIM_REFUSED;
    }
    r = in->id == 1u ? press(m) : change(m, in->id);
    if (r == UIM_OK && in->id != 1u && in->id != 10u && in->id != 14u) {
        app_draw();
    }
    return r;
}

uim_result_t uim_settle(uim_t *m, bool *worked)
{
    bool pressed = false;
    *worked = false;
    if (!m->open) {
        return UIM_ERROR;
    }
    if (m->tick_in > 0u && --m->tick_in == 0u) {
        lv_tick_inc(5);   /* broken on purpose: the product moves the tick the gate owns */
    }
    if (m->refuse_in > 0u && --m->refuse_in == 0u) {
        return UIM_REFUSED;
    }
    if (m->error_in > 0u && --m->error_in == 0u) {
        return UIM_ERROR;
    }
    if (m->busy) {
        *worked = true;   /* broken on purpose: there is always more work */
        return event(m, "busy") ? UIM_OK : UIM_ERROR;
    }
    return run_work(m, worked, &pressed) ? UIM_OK : UIM_ERROR;
}

uint64_t uim_next_due(const uim_t *m)
{
    if (!m->open) {
        return UIM_NO_DEADLINE;
    }
    return m->notice_due < m->anim_due ? m->notice_due : m->anim_due;
}

bool uim_step(uim_t *m, uint32_t ms)
{
    bool worked = false;
    bool pressed = false;
    if (!m->open || ms < 1u || ms > UIM_FRAME_MS) {
        return false;
    }
    app_step(ms);
    m->now += ms;
    if (m->now >= m->notice_due) {
        app_show_notice(false);
        m->notice_due = UIM_NO_DEADLINE;
        if (!event(m, "notice_timeout")) {
            return false;
        }
    }
    return run_work(m, &worked, &pressed);
}

bool uim_frame(uim_t *m, struct _lv_display_t **disp)
{
    if (!m->open) {
        return false;
    }
    if (m->rare_clock) {
        app_clock_moves();   /* a wall clock moved since the last frame, never during one */
    }
    app_draw();
    *disp = m->frame_mode == 11 ? app_second_display()
            : m->frame_mode == 12 ? (struct _lv_display_t *)(uintptr_t)(const void *)g_not_a_display
                                  : app_display();
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
        n = c == '\t' ? snprintf(text + at, sizeof text - at, "\\t")
            : c == '\n' ? snprintf(text + at, sizeof text - at, "\\n")
            : (c < 0x20u || c > 0x7eu) ? snprintf(text + at, sizeof text - at, "\\x%02x", (unsigned)c)
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

/* No pointer entry (U05c): the probe injects its taps at the app's pointer indev, as before. */
bool uim_pointer_supported(void)
{
    return false;
}

bool uim_pointer(uim_t *m, int32_t x, int32_t y, bool down)
{
    (void)m;
    (void)x;
    (void)y;
    (void)down;
    return false;
}

/* No scene identity (U24): `identity` is `err identity unsupported`, the greeting does not announce it. */
bool uim_identity_supported(void)
{
    return false;
}

bool uim_identity(uim_t *m, uim_buf_t *out)
{
    (void)m;
    out->len = 0;
    return false;
}
