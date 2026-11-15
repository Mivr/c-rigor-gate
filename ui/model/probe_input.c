/* `hit-test` and `tap` (U05a; docs/ui-model.md, "Frame facts"): LVGL's own pointer search, and a press and release
 * through the production pointer path followed by the product's due work and a quiet frame. Static memory only. */
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

/* After the press and release: the product's due work (`uim_settle`), then refreshes to a quiet frame; the tick must
 * not have moved. True when the tap goes on; false when the reply is made (`fail tap` or an `err`), in `*reply`. */
static bool after_tap(probe_t *p, uint32_t tick, bool *reply)
{
    bool worked = false;
    bool flushed = false;
    probe_work_t w = probe_model_settle(p, &worked);
    lvprobe_status_t st = LVPROBE_OK;
    if (w == PROBE_WORK_FAILED) {
        p->opened = false;
        *reply = probe_reply_plain("tap", false);
        return false;
    }
    st = w == PROBE_WORK_OK ? probe_lv_settle(p, &flushed) : LVPROBE_ERR_FORMAT;
    st = (st == LVPROBE_OK && lv_tick_get() != tick) ? LVPROBE_ERR_FORMAT : st;
    if (st != LVPROBE_OK) {
        *reply = probe_fatal(p, probe_why(st));
        return false;
    }
    return true;
}

/* An input like `apply`: a failure poisons; `blocked` (LVGL did not process it) does not. Reply: the pressed and the
 * clicked node. */
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
    uint32_t tick = 0;
    bool reply = false;
    lvprobe_status_t st;
    if (!probe_point(p, arg, &x, &y, &syntax)) {
        return probe_point_err(p, syntax);
    }
    p->framed = false;
    memset(&hit, 0, sizeof hit);
    tick = lv_tick_get();
    st = lvprobe_hit(p->lv, x, y, &hit);
    if (st != LVPROBE_OK && st != LVPROBE_ERR_BLOCKED) {
        return probe_fatal(p, probe_why(st));
    }
    if (!after_tap(p, tick, &reply)) {
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
