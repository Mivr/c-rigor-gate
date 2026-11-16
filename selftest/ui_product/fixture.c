/* The shared core of the broken model adapters of the explorer selftest (fixture.h). */
#include <stdio.h>
#include <string.h>

#include "selftest/ui_product/fixture.h"
#include "selftest/ui_product/toy.h"

enum { LINE_MAX_BYTES = 160 };

static bool add_line(fix_t *f, const char *line)
{
    size_t n = strlen(line);
    if (f->trace_len + n + 1u > FIX_LOG_MAX) {
        return false;
    }
    memcpy(f->trace + f->trace_len, line, n);
    f->trace[f->trace_len + n] = '\n';
    f->trace_len += n + 1u;
    return true;
}

static bool event(fix_t *f, const char *type)
{
    char line[LINE_MAX_BYTES];
    int n = snprintf(line, sizeof line, "%llu\t%s\t%llu", (unsigned long long)f->seq, type, (unsigned long long)f->now);
    f->seq++;
    return n > 0 && (size_t)n < sizeof line && add_line(f, line);
}

bool fix_open(fix_t *f, uint64_t origin_ms, bool spin, uint64_t tick_ms)
{
    f->open = false;
    f->spin = spin;
    f->tick_ms = tick_ms;
    f->tick_due = tick_ms > 0u ? origin_ms + tick_ms : FIX_NO_DEADLINE;
    f->seq = 0;
    f->trace_len = 0;
    f->spin_due = FIX_NO_DEADLINE;
    if (!toy_start()) {
        return false;
    }
    f->now = origin_ms;
    f->open = event(f, "boot");
    return f->open;
}

fix_result_t fix_apply(fix_t *f, uint16_t kind, uint32_t id, const char *press_type)
{
    if (!f->open) {
        return FIX_ERROR;
    }
    if (kind != 3u || id != 1u || toy_notice_shown()) {
        return FIX_REFUSED;
    }
    toy_show_notice("Pressed", f->now);
    toy_draw();
    f->spin_due = f->spin ? f->now + 1u : FIX_NO_DEADLINE;
    return event(f, press_type) ? FIX_OK : FIX_ERROR;
}

uint64_t fix_next_due(const fix_t *f)
{
    uint64_t notice = toy_notice_due();
    uint64_t due = notice < f->spin_due ? notice : f->spin_due;
    if (!f->open) {
        return FIX_NO_DEADLINE;
    }
    return due < f->tick_due ? due : f->tick_due;
}

bool fix_step(fix_t *f, uint32_t ms)
{
    if (!f->open || ms < 1u || ms > 16u) {
        return false;
    }
    toy_step(ms);
    f->now += ms;
    if (f->spin_due != FIX_NO_DEADLINE && f->now >= f->spin_due) {
        f->spin_due = f->now + 1u;   /* the defect: the work reschedules itself 1 ms later, forever */
    }
    if (f->tick_due != FIX_NO_DEADLINE && f->now >= f->tick_due) {
        f->tick_due += f->tick_ms;   /* a perpetual tick: legitimate, and never quiet */
    }
    if (toy_notice_due() != FIX_NO_DEADLINE && f->now >= toy_notice_due()) {
        toy_hide_notice();
        return event(f, "notice_timeout");
    }
    return true;
}

bool fix_semantic(const fix_t *f, char *data, size_t cap, size_t *len)
{
    unsigned i = 0;
    *len = 0;
    if (!f->open) {
        return false;
    }
    for (i = 0; i < TOY_NODES; i++) {
        toy_node_t node;
        int n = 0;
        if (!toy_node(i, &node) || strpbrk(node.text, "\\\t\n") != NULL) {
            return false;
        }
        n = snprintf(data + *len, cap - *len, "%s\t%s\t%s\t%d\t%d\t%d\t%d\t1\t%s\t%s\tbody\tnormal\t%s\tnone\n", node.key,
                     node.role, node.text, (int)node.x, (int)node.y, (int)node.w, (int)node.h, i == 1u ? "1:0" : "-",
                     node.hidden ? "hidden" : "-", i == 1u ? "tap" : "none");
        if (n <= 0 || (size_t)n >= cap - *len) {
            return false;
        }
        *len += (size_t)n;
    }
    return true;
}

bool fix_take_trace(fix_t *f, char *data, size_t cap, size_t *len)
{
    if (!f->open || f->trace_len > cap) {
        return false;
    }
    memcpy(data, f->trace, f->trace_len);
    *len = f->trace_len;
    f->trace_len = 0;
    return true;
}
