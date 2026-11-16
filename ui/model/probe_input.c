/* `hit-test` and `tap` (U05a, U05c; docs/ui-model.md, "Hit query and tap"): LVGL's own pointer search, and a press and
 * release through the production pointer path (the product's pointer entry, observed on its indev, when it has one;
 * else injected at the pointer indev) followed by the product's due work and a quiet frame. Static memory only. */
#include <string.h>

#include "ui/model/probe.h"

/* What LVGL's own search finds at the point; no input event is sent. Read-only: an error does not poison. */
bool probe_cmd_hit_test(probe_t *p, char **arg)
{
    int32_t x = 0;
    int32_t y = 0;
    int32_t node = LVPROBE_NONE;
    lv_obj_t *obj = NULL;
    bool syntax = false;
    char num[16];
    const char *word = NULL;
    lvprobe_status_t st;
    if (!probe_point(p, arg, &x, &y, &syntax)) {
        return probe_point_err(p, syntax);
    }
    st = lvprobe_hit_test(p->lv, x, y, &node, &obj);
    if (st == LVPROBE_ERR_BLOCKED) {
        return probe_reply_words("hit-test", "blocked", NULL);
    }
    if (st != LVPROBE_OK || (obj != NULL && node == LVPROBE_NONE)) {
        return probe_refuse(p, st != LVPROBE_OK ? probe_why(st) : "internal");   /* outside the walk: never a guess */
    }
    word = probe_node_word(obj != NULL ? node : LVPROBE_NONE, num, sizeof num);
    return word != NULL ? probe_reply_words("hit-test", word, NULL) : probe_refuse(p, "internal");
}

/* After the samples of a tap: the product's due work (`uim_settle`). True when the tap goes on; false when the reply is
 * made (`fail tap`, which poisons, or `err tap model-contract` for a result outside UIM_OK/UIM_ERROR). */
static bool model_settled(probe_t *p, bool *reply)
{
    bool worked = false;
    probe_work_t w = probe_model_settle(p, &worked);
    if (w == PROBE_WORK_FAILED) {
        p->opened = false;
        *reply = probe_reply_plain("tap", false);
        return false;
    }
    if (w != PROBE_WORK_OK) {
        *reply = probe_fatal(p, "model-contract");
        return false;
    }
    return true;
}

/* Refreshes to a quiet frame; the tick must keep the session's offset (`tick`: it did before the tap). */
static bool lv_settled(probe_t *p, bool tick, bool *reply)
{
    bool flushed = false;
    lvprobe_status_t st = probe_lv_settle(p, &flushed);
    st = (st == LVPROBE_OK && (!tick || !probe_tick_ok(p))) ? LVPROBE_ERR_FORMAT : st;
    if (st != LVPROBE_OK) {
        *reply = probe_fatal(p, probe_why(st));
        return false;
    }
    return true;
}

/* The tap injected at the pointer indev (a product without a pointer entry): lvprobe_hit, then the settles. */
static bool injected_tap(probe_t *p, int32_t x, int32_t y, bool tick, lvprobe_hit_t *hit, lvprobe_status_t *st,
                         bool *reply)
{
    *st = lvprobe_hit(p->lv, x, y, hit);
    if (*st != LVPROBE_OK && *st != LVPROBE_ERR_BLOCKED) {
        *reply = probe_fatal(p, probe_why(*st));
        return false;
    }
    return model_settled(p, reply) && lv_settled(p, tick, reply);
}

/* The tap through the product's pointer entry (U05c): press and release through `uim_pointer`, then `uim_settle`
 * (which processes the samples and the work they queue), observed on the product's indev: what LVGL pressed and
 * clicked comes from LVGL's own events (lvprobe_observe_*), never from the probe. A failing `uim_pointer` or settle is
 * `fail tap`; the observation is ended whatever happens (its status adds nothing to a poisoned session then). */
static bool pointer_tap(probe_t *p, int32_t x, int32_t y, bool tick, lvprobe_hit_t *hit, lvprobe_status_t *st,
                        bool *reply)
{
    *st = lvprobe_observe_begin(p->lv, x, y);
    if (*st != LVPROBE_OK) {
        *reply = probe_fatal(p, probe_why(*st));
        return false;
    }
    if (!uim_pointer(p->model, x, y, true) || !uim_pointer(p->model, x, y, false)) {
        (void)lvprobe_observe_end(p->lv, hit);
        p->opened = false;
        *reply = probe_reply_plain("tap", false);
        return false;
    }
    if (!model_settled(p, reply)) {
        (void)lvprobe_observe_end(p->lv, hit);
        return false;
    }
    *st = lvprobe_observe_end(p->lv, hit);
    if (*st != LVPROBE_OK && *st != LVPROBE_ERR_BLOCKED) {
        *reply = probe_fatal(p, probe_why(*st));
        return false;
    }
    return lv_settled(p, tick, reply);
}

/* An input like `apply`: a failure poisons; `blocked` (LVGL did not process it) does not. Reply: the pressed and the
 * clicked node. The path is the product's pointer entry when it has one (capability `pointer`), else the indev. */
bool probe_cmd_tap(probe_t *p, char **arg)
{
    int32_t x = 0;
    int32_t y = 0;
    bool syntax = false;
    lvprobe_hit_t hit;
    char a[16];
    char b[16];
    const char *pressed = NULL;
    const char *clicked = NULL;
    bool tick = false;
    bool reply = false;
    lvprobe_status_t st = LVPROBE_OK;
    if (!probe_point(p, arg, &x, &y, &syntax)) {
        return probe_point_err(p, syntax);
    }
    p->framed = false;
    memset(&hit, 0, sizeof hit);
    if (uim_pointer_supported() != p->pointer) {
        return probe_fatal(p, "model-contract");   /* not the constant the greeting announced */
    }
    tick = probe_tick_ok(p);
    if (!(p->pointer ? pointer_tap(p, x, y, tick, &hit, &st, &reply) : injected_tap(p, x, y, tick, &hit, &st, &reply))) {
        return reply;
    }
    if (st == LVPROBE_ERR_BLOCKED) {
        return probe_reply_words("tap", "blocked", NULL);
    }
    pressed = hit.pressed ? probe_node_word(hit.pressed_node, a, sizeof a) : "none";
    clicked = hit.clicked ? probe_node_word(hit.node, b, sizeof b) : "none";
    if (pressed == NULL || clicked == NULL || (hit.pressed && hit.pressed_node == LVPROBE_NONE) ||
        (hit.clicked && hit.node == LVPROBE_NONE)) {
        return probe_fatal(p, "internal");   /* an object outside the walk took the tap: never a guess */
    }
    return probe_reply_words("tap", pressed, clicked);
}
