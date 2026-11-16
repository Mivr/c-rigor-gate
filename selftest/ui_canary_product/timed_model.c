/* The model adapter of the timed canary (selftest/ui_time.sh): implements ui/model/model.h on top of timed.h. Intent v
 * (1..TV_COUNT-1, arg 0) asks for variant v at the current instant. After every input and every step the scene of
 * (variant, that instant, now) is published: its difference from the last one is appended as scene patches
 * (`create <key> node - <role>`, `remove <key> node <role> -`, `update <key> text <old> <new>`, the lockers adapter's
 * forms) and the LVGL objects are rebuilt. The deadline is the next instant the scene may change. Identity: the state
 * line only (`main`, `dialog`, `detail`). No env input, no pointer entry, no view domain. */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_canary_product/timed.h"
#include "ui/model/model.h"

enum { LOG_MAX = 1024, PATCH_MAX = 8192, LINE = 256 };

struct uim {
    bool open;
    uint64_t now;
    uint64_t since;
    uint64_t seq;
    timed_variant_t variant;
    timed_scene_t cur;
    timed_scene_t next;   /* the scene being published (static, not on the stack) */
    char trace[LOG_MAX];
    size_t trace_len;
    char patches[PATCH_MAX];
    size_t patches_len;
};

static struct uim g_model;

uim_t *uim_instance(void)
{
    return &g_model;
}

static bool append(char *log, size_t cap, size_t *len, const char *line, int n)
{
    if (n <= 0 || (size_t)n >= LINE || *len + (size_t)n > cap) {
        return false;
    }
    memcpy(log + *len, line, (size_t)n);
    *len += (size_t)n;
    return true;
}

static bool event(uim_t *m, const char *type)
{
    char line[LINE];
    int n = snprintf(line, sizeof line, "%llu\t%s\t%llu\n", (unsigned long long)m->seq, type, (unsigned long long)m->now);
    m->seq++;
    return append(m->trace, sizeof m->trace, &m->trace_len, line, n);
}

static bool patch(uim_t *m, const char *op, const char *key, const char *field, const char *old, const char *new_)
{
    char line[LINE];
    int n = snprintf(line, sizeof line, "%s\t%s\t%s\t%s\t%s\n", op, key, field, old, new_);
    return append(m->patches, sizeof m->patches, &m->patches_len, line, n);
}

static const timed_node_t *find(const timed_scene_t *s, const char *key)
{
    unsigned i;
    for (i = 0; i < s->count; i++) {
        if (strcmp(s->nodes[i].key, key) == 0) {
            return &s->nodes[i];
        }
    }
    return NULL;
}

/* The patches from `a` to `b`; *changed if there is any (or the state class differs). */
static bool diff(uim_t *m, const timed_scene_t *a, const timed_scene_t *b, bool *changed)
{
    unsigned i;
    bool ok = true;
    *changed = strcmp(a->cls, b->cls) != 0;
    for (i = 0; ok && i < a->count; i++) {
        const timed_node_t *other = find(b, a->nodes[i].key);
        if (other == NULL) {
            ok = patch(m, "remove", a->nodes[i].key, "node", a->nodes[i].role, "-");
            *changed = true;
        } else if (strcmp(other->text, a->nodes[i].text) != 0) {
            ok = patch(m, "update", a->nodes[i].key, "text", a->nodes[i].text, other->text);
            *changed = true;
        }
    }
    for (i = 0; ok && i < b->count; i++) {
        if (find(a, b->nodes[i].key) == NULL) {
            ok = patch(m, "create", b->nodes[i].key, "node", "-", b->nodes[i].role);
            *changed = true;
        }
    }
    return ok;
}

/* Publish the scene of now: its patches, and the LVGL objects rebuilt when it changed. */
static bool refresh(uim_t *m, bool *worked)
{
    bool changed = false;
    timed_scene_at(m->variant, m->since, m->now, &m->next);
    if (!diff(m, &m->cur, &m->next, &changed)) {
        return false;
    }
    *worked = changed;
    if (changed && !timed_build(&m->next)) {
        return false;
    }
    m->cur = m->next;
    return true;
}

bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed)
{
    bool worked = false;
    (void)seed;
    m->open = false;
    m->seq = 0;
    m->trace_len = 0;
    m->patches_len = 0;
    m->variant = TV_NONE;
    m->now = clock_origin_ms;
    m->since = clock_origin_ms;
    if (!timed_start()) {
        return false;
    }
    timed_scene_at(TV_NONE, m->since, m->now, &m->cur);
    if (!timed_build(&m->cur)) {
        return false;
    }
    m->patches_len = 0;
    m->open = event(m, "boot") && refresh(m, &worked);
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
    bool worked = false;
    if (!m->open) {
        return UIM_ERROR;
    }
    if (in->kind != UIM_IN_INTENT || in->arg != 0 || in->id == 0u || in->id >= (uint32_t)TV_COUNT) {
        return UIM_REFUSED;
    }
    m->variant = (timed_variant_t)in->id;
    m->since = m->now;
    if (m->variant == TV_FLASH && !(timed_flash_object() && patch(m, "create", "flash", "node", "-", "panel") &&
                                    patch(m, "remove", "flash", "node", "panel", "-"))) {
        return UIM_ERROR;
    }
    return event(m, "variant") && refresh(m, &worked) ? UIM_OK : UIM_ERROR;
}

uim_result_t uim_settle(uim_t *m, bool *worked)
{
    *worked = false;
    return m->open && refresh(m, worked) ? UIM_OK : UIM_ERROR;
}

uint64_t uim_next_due(const uim_t *m)
{
    uint64_t due = m->open ? timed_next_change(m->variant, m->since, m->now) : TIMED_NONE;
    return due == TIMED_NONE ? UIM_NO_DEADLINE : due;
}

bool uim_step(uim_t *m, uint32_t ms)
{
    bool worked = false;
    if (!m->open || ms < 1u || ms > UIM_FRAME_MS) {
        return false;
    }
    timed_step(ms);
    m->now += ms;
    return refresh(m, &worked);
}

bool uim_frame(uim_t *m, struct _lv_display_t **disp)
{
    if (!m->open) {
        return false;
    }
    timed_draw();
    *disp = timed_display();
    return *disp != NULL;
}

/* key, role, label, x, y, w, h, enabled, intent:arg, flags, style token 1, and `-` for the last three. */
bool uim_semantic(uim_t *m, uim_buf_t *out)
{
    unsigned i;
    out->len = 0;
    if (!m->open) {
        return false;
    }
    for (i = 0; i < m->cur.count; i++) {
        const timed_node_t *n = &m->cur.nodes[i];
        int k = snprintf(out->data + out->len, out->cap - out->len, "%s\t%s\t%s\t%d\t%d\t%d\t%d\t1\t-\t-\t1\t-\t-\t-\n",
                         n->key, n->role, n->text, (int)n->x, (int)n->y, (int)n->w, (int)n->h);
        if (k <= 0 || (size_t)k >= out->cap - out->len) {
            return false;
        }
        out->len += (size_t)k;
    }
    return true;
}

static bool drain(char *log, size_t *len, uim_buf_t *out)
{
    if (*len > out->cap) {
        return false;
    }
    memcpy(out->data, log, *len);
    out->len = *len;
    *len = 0;
    return true;
}

bool uim_patches(uim_t *m, uim_buf_t *out)
{
    out->len = 0;
    return m->open && drain(m->patches, &m->patches_len, out);
}

bool uim_trace(uim_t *m, uim_buf_t *out)
{
    out->len = 0;
    return m->open && drain(m->trace, &m->trace_len, out);
}

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

bool uim_identity_supported(void)
{
    return true;
}

bool uim_identity(uim_t *m, uim_buf_t *out)
{
    int n = 0;
    out->len = 0;
    if (!m->open) {
        return false;
    }
    n = snprintf(out->data, out->cap, "state\t%s\n", m->cur.cls);
    if (n <= 0 || (size_t)n >= out->cap) {
        return false;
    }
    out->len = (size_t)n;
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
