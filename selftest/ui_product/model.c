/* The model adapter of the toy app: implements ui/model/model.h on top of toy.h.
 * The fixture has two deliberately broken inputs so the selftest can see the probe's rules: INTENT_BROKEN makes uim_apply
 * fail (the session is poisoned), INTENT_BAD_RECORD writes a trace record that breaks the record grammar (model-contract).
 * Three more inputs exist to show the gate's time loop: INTENT_DUE_NOW arms a deadline at the current time (a contract
 * violation), INTENT_CHAIN makes the next notice timeout arm a second timer 20 ms later (a deadline created during an
 * advance), INTENT_SHRINK_BUF makes uim_semantic change the capacity of the caller's buffer, INTENT_MANY_TABS writes a trace record with 40 TABs, INTENT_LOG_STEPS toggles one trace event per uim_step (so the frame grid is visible).
 * INTENT_PRESS taps the button through the app's pointer: while the notice shows, its scrim takes the tap and the apply
 * is UIM_MISSED (U05a, the F3b canary).
 * U05c: the toy's pointer entry, `uim_pointer`, works like a host's input hook: it queues the sample above LVGL (toy.h)
 * and a press posts the trace event `touch`; `uim_settle` feeds the queue to the app's indev, then runs the press the
 * button's handler recorded. It exists only in the build that links pointer_on.c (`uim_pointer_supported`); the build
 * with pointer_off.c has no entry, so the probe injects its taps at the indev and no `touch` is posted.
 * INTENT_POINTER_TOGGLE disables (and then enables again) the app's pointer indev: LVGL processes no tap then.
 * Two broken pointer entries for the probe's rules: after INTENT_POINTER_FAIL `uim_pointer` fails (`fail tap`, the
 * session poisoned); after INTENT_POINTER_TWICE a release queues a second whole tap after it (two presses and two
 * clicks: not one tap, `err tap model-contract`). INTENT_BUTTON_DISABLE and INTENT_BUTTON_ENABLE put the button in
 * LVGL's disabled state and back (a tap then presses it and clicks nothing, on both paths). */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_product/toy.h"
#include "ui/model/model.h"

enum { LOG_MAX = 2048, INTENT_PRESS = 1, INTENT_BROKEN = 666, INTENT_BAD_RECORD = 667,
       INTENT_DUE_NOW = 668, INTENT_CHAIN = 669, INTENT_LOG_STEPS = 670, INTENT_MANY_TABS = 671, INTENT_SHRINK_BUF = 672,
       INTENT_POINTER_TOGGLE = 673, INTENT_POINTER_FAIL = 674, INTENT_POINTER_TWICE = 675,
       INTENT_BUTTON_DISABLE = 676, INTENT_BUTTON_ENABLE = 677, ENV_OFFLINE = 1, LINE_MAX_BYTES = 160 };

struct uim {
    bool open;
    uint64_t now;
    uint64_t seed;
    uint64_t seq;
    uint64_t second_due;
    bool chain;
    bool log_steps;
    bool shrink;
    bool pointer_fail;
    bool pointer_twice;
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
    m->second_due = UIM_NO_DEADLINE;
    m->chain = false;
    m->log_steps = false;
    m->shrink = false;
    m->pointer_fail = false;
    m->pointer_twice = false;
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
    if (in->kind == UIM_IN_INTENT && in->id >= INTENT_DUE_NOW && in->id <= INTENT_LOG_STEPS) {
        m->second_due = in->id == INTENT_DUE_NOW ? m->now : m->second_due;
        m->chain = in->id == INTENT_CHAIN ? true : m->chain;
        m->log_steps = in->id == INTENT_LOG_STEPS ? !m->log_steps : m->log_steps;
        return UIM_OK;
    }
    if (in->kind == UIM_IN_INTENT && (in->id == INTENT_POINTER_FAIL || in->id == INTENT_POINTER_TWICE)) {
        m->pointer_fail = m->pointer_fail || in->id == INTENT_POINTER_FAIL;
        m->pointer_twice = m->pointer_twice || in->id == INTENT_POINTER_TWICE;
        return UIM_OK;
    }
    if (in->kind == UIM_IN_INTENT && (in->id == INTENT_BUTTON_DISABLE || in->id == INTENT_BUTTON_ENABLE)) {
        toy_set_button_disabled(in->id == INTENT_BUTTON_DISABLE);
        return UIM_OK;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_POINTER_TOGGLE) {
        toy_set_pointer_enabled(!toy_pointer_enabled());
        return UIM_OK;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_SHRINK_BUF) {
        m->shrink = true;
        return UIM_OK;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_MANY_TABS) {
        char line[48];
        memset(line, '\t', 40);
        line[40] = '\0';
        return log_add(m->trace, &m->trace_len, line) ? UIM_OK : UIM_ERROR;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_BAD_RECORD) {
        return log_add(m->trace, &m->trace_len, "a record without tabs") ? UIM_OK : UIM_ERROR;
    }
    if (in->kind == UIM_IN_INTENT && in->id == INTENT_PRESS) {   /* a tap at the button through the app's pointer */
        toy_press();
        if (!toy_take_press()) {
            return UIM_MISSED;   /* the notice's scrim took it: delivered, but no press */
        }
        return show(m, "Pressed") && event(m, "press") ? UIM_OK : UIM_ERROR;
    }
    if (in->kind == UIM_IN_ENV && in->id == ENV_OFFLINE && !toy_notice_shown()) {
        return show(m, "Offline") && event(m, "env_offline") ? UIM_OK : UIM_ERROR;
    }
    if (in->kind == UIM_IN_LINE && in->text[0] != '\0') {
        return event(m, "line") ? UIM_OK : UIM_ERROR;
    }
    return UIM_REFUSED;
}

/* The toy's pointer entry: queue the sample, and a press posts `touch` (only in the build that has the entry). */
bool uim_pointer(uim_t *m, int32_t x, int32_t y, bool down)
{
    if (!uim_pointer_supported() || !m->open || m->pointer_fail || !toy_pointer(x, y, down)) {
        return false;
    }
    if (m->pointer_twice && !down && (!toy_pointer(x, y, true) || !toy_pointer(x, y, false))) {
        return false;   /* the release of a tap, then a second whole tap */
    }
    return !down || event(m, "touch");
}

/* The queued pointer samples go to the app's indev; a tap at the button leaves a press queued (the button's handler
 * records it): run it now, as an apply would. */
uim_result_t uim_settle(uim_t *m, bool *worked)
{
    *worked = false;
    if (!m->open) {
        return UIM_ERROR;
    }
    *worked = toy_pump() > 0u;
    if (!toy_take_press()) {
        return UIM_OK;
    }
    *worked = true;
    return show(m, "Pressed") && event(m, "press") ? UIM_OK : UIM_ERROR;
}

uint64_t uim_next_due(const uim_t *m)
{
    uint64_t notice = toy_notice_due();
    if (!m->open) {
        return UIM_NO_DEADLINE;
    }
    return notice < m->second_due ? notice : m->second_due;
}

/* The notice timer: hide at the deadline; an armed chain starts the second timer, 20 ms later. */
static bool notice_timer(uim_t *m)
{
    if (toy_notice_due() == UIM_NO_DEADLINE || m->now < toy_notice_due()) {
        return true;
    }
    toy_hide_notice();
    if (m->chain) {
        m->second_due = m->now + 20u;
        m->chain = false;
    }
    return patch(m, "set", "notice", "hidden", "0", "1") && event(m, "notice_timeout");
}

static bool second_timer(uim_t *m)
{
    if (m->second_due == UIM_NO_DEADLINE || m->now < m->second_due) {
        return true;
    }
    m->second_due = UIM_NO_DEADLINE;
    return event(m, "second_timer");
}

bool uim_step(uim_t *m, uint32_t ms)
{
    if (!m->open || ms < 1u || ms > UIM_FRAME_MS) {
        return false;
    }
    toy_step(ms);
    m->now += ms;
    return (!m->log_steps || event(m, "step")) && notice_timer(m) && second_timer(m);
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
    out->cap -= m->shrink ? 1u : 0u;
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
