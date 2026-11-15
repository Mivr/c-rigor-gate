/* What the lvprobe commands of the probe share (docs/ui-model.md, "Frame facts"): status mapping, replies, the LVGL
 * settle loop, the checked `uim_settle`, point parsing. Static memory only; no recursion. */
#include <stdio.h>

#include "ui/model/probe.h"

static bool retry(lvprobe_status_t st)
{
    return st == LVPROBE_ERR_STALE || st == LVPROBE_ERR_UNSETTLED;
}

/* A capacity or a full payload is `too-large`. A display the probe cannot read, gone, never quiet, current or stable,
 * or an LVGL failure (normally the product's doing, e.g. its pool) is `model-contract`. Anything else is `internal`. */
const char *probe_why(lvprobe_status_t st)
{
    if (st == LVPROBE_ERR_FULL || st == LVPROBE_ERR_OVERFLOW || st == LVPROBE_ERR_TRUNC) {
        return "too-large";
    }
    if (st == LVPROBE_ERR_FORMAT || st == LVPROBE_ERR_GONE || retry(st) || st == LVPROBE_ERR_UNSTABLE ||
        st == LVPROBE_ERR_LVGL) {
        return "model-contract";
    }
    return "internal";
}

bool probe_fatal(probe_t *p, const char *reason)
{
    p->opened = false;
    p->framed = false;
    return probe_reply_err(p->cmd, reason);
}

bool probe_refuse(probe_t *p, const char *reason)
{
    p->framed = false;
    return probe_reply_err(p->cmd, reason);
}

/* probe_reply_plain writes `ok ` and its name argument. */
bool probe_reply_words(const char *name, const char *a, const char *b)
{
    char line[64];
    int n = b != NULL ? snprintf(line, sizeof line, "%s %s %s", name, a, b) : snprintf(line, sizeof line, "%s %s", name, a);
    return (n > 0 && (size_t)n < sizeof line) ? probe_reply_plain(line, true) : probe_reply_err(name, "internal");
}

lvprobe_status_t probe_lv_settle(probe_t *p, bool *flushed)
{
    unsigned i;
    *flushed = false;
    for (i = 0; i < PROBE_SETTLE_MAX; i++) {
        bool now = true;
        lvprobe_status_t st = lvprobe_settle(p->lv, &now);
        if (st != LVPROBE_OK || !now) {
            return st;
        }
        *flushed = true;
    }
    return LVPROBE_ERR_UNSETTLED;
}

probe_work_t probe_model_settle(probe_t *p, bool *worked)
{
    uim_result_t r = UIM_ERROR;
    *worked = false;
    r = uim_settle(p->model, worked);
    if (r == UIM_OK) {
        return PROBE_WORK_OK;
    }
    return r == UIM_ERROR ? PROBE_WORK_FAILED : PROBE_WORK_CONTRACT;
}

bool probe_point(const probe_t *p, char **arg, int32_t *x, int32_t *y, bool *syntax)
{
    uint64_t vx = 0;
    uint64_t vy = 0;
    *syntax = probe_parse_u64(arg[0], &vx) && probe_parse_u64(arg[1], &vy);
    if (!*syntax || !p->framed || vx >= (uint64_t)lv_display_get_horizontal_resolution(p->disp) ||
        vy >= (uint64_t)lv_display_get_vertical_resolution(p->disp)) {
        return false;
    }
    *x = (int32_t)vx;
    *y = (int32_t)vy;
    return true;
}

bool probe_point_err(const probe_t *p, bool syntax)
{
    return probe_reply_err(p->cmd, syntax && !p->framed ? "no-frame" : "bad-arguments");
}

const char *probe_node_word(int32_t node, char *buf, size_t cap)
{
    int n = 0;
    if (node == LVPROBE_NONE) {
        return "none";
    }
    n = snprintf(buf, cap, "%ld", (long)node);
    return (n > 0 && (size_t)n < cap) ? buf : NULL;
}
