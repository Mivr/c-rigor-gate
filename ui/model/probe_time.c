/* The time loop of the probe: the gate, not the model, owns the frame grid and the deadlines (model.h, `uim_step`). */
#include "ui/model/probe.h"

/* The next step from `now`: at most to the next frame boundary, the next deadline and `to`. */
static uint32_t step_len(const probe_t *p, uint64_t to, bool *contract)
{
    uint64_t len = UIM_FRAME_MS - (p->now - p->origin) % UIM_FRAME_MS;
    uint64_t due = uim_next_due(p->model);
    if (to - p->now < len) {
        len = to - p->now;
    }
    if (due != UIM_NO_DEADLINE && due <= p->now) {   /* a deadline on a stable scene is in the future */
        *contract = true;
    } else if (due != UIM_NO_DEADLINE && due - p->now < len) {
        len = due - p->now;
    }
    return (uint32_t)len;
}

probe_advance_t probe_advance_to(probe_t *p, uint64_t to)
{
    while (p->now < to) {
        bool contract = false;
        uint32_t len = step_len(p, to, &contract);
        if (contract) {
            return PROBE_ADV_CONTRACT;
        }
        if (!uim_step(p->model, len)) {
            return PROBE_ADV_FAILED;
        }
        p->now += len;
    }
    return PROBE_ADV_OK;
}

