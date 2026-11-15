/* A deliberately NONDETERMINISTIC model adapter of the toy (U05 selftest): the trace type of a press carries the process id,
 * which comes from outside the model interface. Run twice in fresh processes, the same path gives different traces, which
 * `rigor ui-explore` reports as `model-nondeterministic` at the press. Never a pattern for a product. */
#include <stdio.h>
#include <unistd.h>

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
    return fix_open(&m->f, clock_origin_ms, false, 0u);
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
    char type[48];
    int n = snprintf(type, sizeof type, "press-%ld", (long)getpid());
    if (n <= 0 || (size_t)n >= sizeof type) {
        return UIM_ERROR;
    }
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
