/* A deliberately STARVING model adapter of the toy (U05 selftest): a press arms a timer that re-arms itself 1 ms after every
 * firing (fixture.c), so its next deadline never gets more than a frame ahead of now; `rigor ui-explore` reports
 * `timer-starvation` instead of advancing the clock past it. Never a pattern for a product. */
#include "selftest/ui_product/fixture.h"
#include "selftest/ui_product/toy.h"
#include "ui/model/model.h"

struct uim {
    fix_t f;
};

static struct uim g_model;

uim_t *uim_instance(void)
{
    return &g_model;
}

bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed)
{
    (void)seed;
    return fix_open(&m->f, clock_origin_ms, true, 0u);
}

bool uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap, uint16_t *count)
{
    (void)out;
    (void)cap;
    *count = 0;
    return m->f.open;
}

uim_result_t uim_apply(uim_t *m, const uim_input_t *in)
{
    const char *type = "press";
    fix_result_t r = fix_apply(&m->f, in->kind, in->id, type);
    return r == FIX_OK ? UIM_OK : r == FIX_REFUSED ? UIM_REFUSED : UIM_ERROR;
}

/* The fixture queues no work: nothing is ever due without moving the clock. */
uim_result_t uim_settle(uim_t *m, bool *worked)
{
    *worked = false;
    return m->f.open ? UIM_OK : UIM_ERROR;
}

uint64_t uim_next_due(const uim_t *m)
{
    return fix_next_due(&m->f);
}

bool uim_step(uim_t *m, uint32_t ms)
{
    return fix_step(&m->f, ms);
}

bool uim_frame(uim_t *m, struct _lv_display_t **disp)
{
    if (!m->f.open) {
        return false;
    }
    toy_draw();
    *disp = toy_display();
    return *disp != NULL;
}

bool uim_semantic(uim_t *m, uim_buf_t *out)
{
    return fix_semantic(&m->f, out->data, out->cap, &out->len);
}

bool uim_patches(uim_t *m, uim_buf_t *out)
{
    out->len = 0;
    return m->f.open;
}

bool uim_trace(uim_t *m, uim_buf_t *out)
{
    return fix_take_trace(&m->f, out->data, out->cap, &out->len);
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

/* No pointer entry (U05c): the probe injects its taps at the toy's indev. */
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
