/* gate//ui/lvprobe: hit injection, the hit query and the observation of a product's tap (3). Injection goes through a
 * real LVGL pointer indev: the product's own when it gave one (only its read callback is replaced, for the two reads of
 * a tap), else the probe's. LVGL's indev processing finds the object and sends the events; the probe reads the pressed
 * object right after the press and listens on the indev for LV_EVENT_CLICKED. The query calls LVGL's
 * lv_indev_search_obj and nothing else. The observation (U05c) injects nothing: while the product feeds its own indev,
 * the same listener (added at open, removed at close) records the objects of LVGL's LV_EVENT_PRESSED and
 * LV_EVENT_CLICKED; an observation adds and allocates nothing. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_private.h"
#include "src/display/lv_display_private.h"
#include "src/indev/lv_indev_private.h"

static void clicked_cb(lv_event_t *e);

/* The probe that is tapping through `indev`: the user data of the probe's own event callback on the indev (the
 * indev's user data stays the product's). */
static lvprobe_t *tapping_probe(lv_indev_t *indev)
{
    uint32_t n = lv_indev_get_event_count(indev);
    uint32_t i;
    for (i = 0; i < n; i++) {
        lv_event_dsc_t *dsc = lv_indev_get_event_dsc(indev, i);
        if (dsc != NULL && lv_event_dsc_get_cb(dsc) == clicked_cb) {
            lvprobe_t *p = lv_event_dsc_get_user_data(dsc);
            if (p != NULL && p->tapping) {
                return p;
            }
        }
    }
    return NULL;
}

static void read_cb(lv_indev_t *indev, lv_indev_data_t *data)
{
    const lvprobe_t *p = tapping_probe(indev);
    data->continue_reading = false;
    if (p == NULL) {
        data->state = LV_INDEV_STATE_RELEASED; /* outside a tap the probe's own indev reports nothing */
        return;
    }
    data->point = p->press_at;
    data->state = p->pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static uint8_t count_up(uint8_t n)
{
    return n < UINT8_MAX ? (uint8_t)(n + 1u) : n;
}

/* During an observation: the object of LVGL's LV_EVENT_PRESSED and LV_EVENT_CLICKED, mapped to its walk index at once;
 * only the first of each is kept, all are counted. */
static void observe(lvprobe_t *p, lv_event_code_t code, lv_obj_t *obj)
{
    if (obj == NULL) {
        return;
    }
    if (code == LV_EVENT_PRESSED) {
        if (p->obs_presses == 0u) {
            p->hit.pressed = true;
            p->hit.pressed_obj = obj;
            p->hit.pressed_node = lvprobe_find(p, obj);
        }
        p->obs_presses = count_up(p->obs_presses);
    } else if (code == LV_EVENT_CLICKED) {
        if (p->obs_clicks == 0u) {
            p->hit.clicked = true;
            p->hit.obj = obj;
            p->hit.node = lvprobe_find(p, obj);
        }
        p->obs_clicks = count_up(p->obs_clicks);
    }
}

/* The probe's listener on the indev (every event code; added at open, removed at close). Its parameter is the object
 * LVGL sends the event to, alive while it is sent. An injected tap records LV_EVENT_CLICKED, an observation (U05c)
 * LV_EVENT_PRESSED and LV_EVENT_CLICKED; any other event, and every event outside a tap, is ignored. */
static void clicked_cb(lv_event_t *e)
{
    lvprobe_t *p = lv_event_get_user_data(e);
    lv_obj_t *obj = lv_event_get_param(e);
    lv_event_code_t code = lv_event_get_code(e);
    if (p != NULL && p->open && p->observing) {
        observe(p, code, obj);
        return;
    }
    if (p == NULL || !p->tapping || code != LV_EVENT_CLICKED) {
        return;
    }
    p->hit.clicked = obj != NULL;
    p->hit.obj = obj;
    p->hit.node = lvprobe_find(p, obj);
}

lvprobe_status_t lvp_indev_open(lvprobe_t *p, lv_indev_t *indev)
{
    if (indev != NULL) {
        if (lv_indev_get_type(indev) != LV_INDEV_TYPE_POINTER) {
            return LVPROBE_ERR_ARG;
        }
        p->own_indev = false;
    } else {
        p->cfg.indev = lv_indev_create();
        if (p->cfg.indev == NULL) {
            return LVPROBE_ERR_LVGL;
        }
        p->own_indev = true;
        lv_indev_set_type(p->cfg.indev, LV_INDEV_TYPE_POINTER);
        lv_indev_set_read_cb(p->cfg.indev, read_cb);
        lv_indev_set_display(p->cfg.indev, p->disp);
        lv_indev_set_mode(p->cfg.indev, LV_INDEV_MODE_EVENT); /* read only when the probe taps */
    }
    return lv_indev_add_event_cb(p->cfg.indev, clicked_cb, LV_EVENT_ALL, p) != NULL ? LVPROBE_OK : LVPROBE_ERR_LVGL;
}

/* The indev is still one of LVGL's (compared by address only). */
static bool indev_alive(const lv_indev_t *indev)
{
    lv_indev_t *i = lv_indev_get_next(NULL);
    uint32_t guard = 0;
    while (i != NULL && guard < LVP_VISIT_CAP) {
        if (i == indev) {
            return true;
        }
        i = lv_indev_get_next(i);
        guard++;
    }
    return false;
}

void lvp_indev_close(lvprobe_t *p)
{
    if (p->cfg.indev != NULL && indev_alive(p->cfg.indev)) {
        if (p->own_indev) {
            if (lv_indev_get_read_cb(p->cfg.indev) == read_cb) { /* still the probe's, not a new one at its address */
                lv_indev_delete(p->cfg.indev);
            }
        } else {
            (void)lv_indev_remove_event_cb_with_user_data(p->cfg.indev, clicked_cb, p);
        }
    }
    p->observing = false;
    p->cfg.indev = NULL;
}

/* Exactly the cases in which LVGL does not process a press: lv_indev_read returns at once (no display, disabled,
 * a screen-load animation running: prev_scr), or indev_proc_press returns (waiting for a release). */
static bool blocked(const lv_indev_t *i)
{
    return i->disp == NULL || !i->enabled || i->disp->prev_scr != NULL || i->wait_until_release;
}

/* Forget everything a previous tap left: pressed and hovered objects, scroll, long press and the click streak. */
static void reset(lv_indev_t *i)
{
    lv_indev_reset(i, NULL);
    i->state = LV_INDEV_STATE_RELEASED;
    i->prev_state = LV_INDEV_STATE_RELEASED;
    i->long_pr_sent = 0;
    i->pr_timestamp = 0;
    i->longpr_rep_timestamp = 0;
    i->pointer.pressed = 0;
    i->pointer.last_pressed = NULL;
    i->pointer.short_click_streak = 0;
    i->pointer.last_short_click_timestamp = lv_tick_get() - (uint32_t)i->double_click_time - 1u;
    i->pointer.last_short_click_point.x = -LV_COORD_MAX;
    i->pointer.last_short_click_point.y = -LV_COORD_MAX;
}

/* The release was not processed (a press handler started a screen-load animation or asked to wait for a release):
 * take the pressed state back and leave the indev released. */
static bool release_lost(lvprobe_t *p)
{
    lv_indev_t *i = p->cfg.indev;
    lv_obj_t *act = i->pointer.act_obj;
    if (act == NULL && i->state == LV_INDEV_STATE_RELEASED && !i->wait_until_release) {
        return false;
    }
    if (act != NULL) {
        lv_obj_remove_state(act, LV_STATE_PRESSED);
    }
    if (p->hit.pressed_obj != NULL && p->hit.pressed_obj != act) {
        lvp_live_scan(p);
        if (p->hit.pressed_node != LVPROBE_NONE && p->cfg.nodes[p->hit.pressed_node].seen) {
            lv_obj_remove_state(p->hit.pressed_obj, LV_STATE_PRESSED);
        }
    }
    reset(i);
    i->wait_until_release = 0;
    return true;
}

static void tap(lvprobe_t *p)
{
    lv_indev_t *i = p->cfg.indev;
    lv_indev_read_cb_t cb = i->read_cb;
    lv_obj_t *act;

    i->read_cb = read_cb; /* the product's indev: its read callback comes back after the two reads */
    p->tapping = true;
    p->pressed = true;
    lv_indev_read(i);
    act = i->pointer.act_obj;
    p->hit.pressed = act != NULL;
    p->hit.pressed_obj = act;
    p->hit.pressed_node = lvprobe_find(p, act);
    p->pressed = false;
    lv_indev_read(i);
    p->tapping = false;
    i->read_cb = cb;
}

static bool point_ok(const lvprobe_t *p, int32_t x, int32_t y)
{
    lv_area_t all;
    lvp_display_area(p, &all);
    return x >= all.x1 && y >= all.y1 && x <= all.x2 && y <= all.y2; /* LVGL would clamp a point outside */
}

lvprobe_status_t lvprobe_hit(lvprobe_t *p, int32_t x, int32_t y, lvprobe_hit_t *out)
{
    lvprobe_status_t st;
    if (p == NULL || !p->open || out == NULL || p->cfg.indev == NULL || p->disp_gone || p->observing ||
        !point_ok(p, x, y)) {
        return p != NULL && p->disp_gone ? LVPROBE_ERR_GONE : LVPROBE_ERR_ARG;
    }
    if (p->disp_gone) {
        return LVPROBE_ERR_GONE;
    }
    if (blocked(p->cfg.indev)) {
        return LVPROBE_ERR_BLOCKED; /* before the walk check: a screen load also changes the tree */
    }
    st = lvp_current(p, false);
    if (st == LVPROBE_OK) {
        st = lvp_tree_current(p); /* reparented, reordered or a flag changed since the walk: STALE */
    }
    if (st != LVPROBE_OK) {
        return st;
    }
    p->hit.pressed = false;
    p->hit.pressed_obj = NULL;
    p->hit.pressed_node = LVPROBE_NONE;
    p->hit.clicked = false;
    p->hit.obj = NULL;
    p->hit.node = LVPROBE_NONE;
    p->press_at.x = x;
    p->press_at.y = y;
    reset(p->cfg.indev);
    tap(p);
    *out = p->hit;
    return release_lost(p) ? LVPROBE_ERR_BLOCKED : LVPROBE_OK;
}

lvprobe_status_t lvprobe_hit_test(lvprobe_t *p, int32_t x, int32_t y, int32_t *node, lv_obj_t **obj)
{
    lv_display_t *d;
    lv_obj_t *roots[4];
    lv_obj_t *found = NULL;
    lv_point_t at;
    uint32_t r;
    lvprobe_status_t st;
    if (p == NULL || !p->open || node == NULL || obj == NULL || p->disp_gone || !point_ok(p, x, y)) {
        return p != NULL && p->disp_gone ? LVPROBE_ERR_GONE : LVPROBE_ERR_ARG;
    }
    if (p->cfg.indev == NULL || blocked(p->cfg.indev)) {
        return LVPROBE_ERR_BLOCKED; /* a tap would not be processed now: the answer would be no tap's */
    }
    st = lvp_current(p, false);
    if (st == LVPROBE_OK) {
        st = lvp_tree_current(p);
    }
    if (st != LVPROBE_OK) {
        return st;
    }
    d = p->disp;
    roots[0] = lv_display_get_layer_sys(d); /* pointer_search_obj in lv_indev.c: sys, top, active, bottom */
    roots[1] = lv_display_get_layer_top(d);
    roots[2] = lv_display_get_screen_active(d);
    roots[3] = lv_display_get_layer_bottom(d);
    at.x = x;
    at.y = y;
    for (r = 0; r < 4u && found == NULL; r++) {
        found = roots[r] != NULL ? lv_indev_search_obj(roots[r], &at) : NULL;
    }
    *obj = found;
    *node = lvprobe_find(p, found);
    return LVPROBE_OK;
}

/* ---- observing a tap the product delivers (U05c) ------------------------------------------------------------ */

static void hit_clear(lvprobe_t *p)
{
    p->hit.pressed = false;
    p->hit.pressed_obj = NULL;
    p->hit.pressed_node = LVPROBE_NONE;
    p->hit.clicked = false;
    p->hit.obj = NULL;
    p->hit.node = LVPROBE_NONE;
    p->obs_presses = 0;
    p->obs_clicks = 0;
}

/* The probe's listener is still on the indev (a product could remove every callback of its indev). */
static bool listening(lv_indev_t *indev, const lvprobe_t *p)
{
    uint32_t n = lv_indev_get_event_count(indev);
    uint32_t i;
    for (i = 0; i < n; i++) {
        lv_event_dsc_t *dsc = lv_indev_get_event_dsc(indev, i);
        if (dsc != NULL && lv_event_dsc_get_cb(dsc) == clicked_cb && lv_event_dsc_get_user_data(dsc) == p) {
            return true;
        }
    }
    return false;
}

lvprobe_status_t lvprobe_observe_begin(lvprobe_t *p, int32_t x, int32_t y)
{
    lvprobe_status_t st = LVPROBE_OK;
    if (p == NULL || !p->open || p->observing || p->cfg.indev == NULL || p->disp_gone || !point_ok(p, x, y)) {
        return p != NULL && p->disp_gone ? LVPROBE_ERR_GONE : LVPROBE_ERR_ARG;
    }
    if (p->own_indev) {
        return LVPROBE_ERR_FORMAT; /* no product indev: nothing of the product's to observe */
    }
    if (!indev_alive(p->cfg.indev)) {
        p->cfg.indev = NULL; /* never touched again */
        return LVPROBE_ERR_GONE;
    }
    if (!listening(p->cfg.indev, p)) {
        return LVPROBE_ERR_LVGL; /* the listener of open was removed: the events would go unseen */
    }
    p->obs_blocked = blocked(p->cfg.indev);
    if (!p->obs_blocked) { /* a blocked press changes no tree; a screen load does, so no walk check then */
        st = lvp_current(p, false);
        st = st == LVPROBE_OK ? lvp_tree_current(p) : st;
    }
    if (st != LVPROBE_OK) {
        return st;
    }
    hit_clear(p);
    p->observing = true;
    return LVPROBE_OK;
}

/* The indev is left pressed: LVGL did not process the release (a screen-load animation started by a press handler),
 * or a press is pending a release. */
static bool release_pending(const lv_indev_t *i)
{
    return i->pointer.act_obj != NULL || i->state != LV_INDEV_STATE_RELEASED || i->wait_until_release;
}

lvprobe_status_t lvprobe_observe_end(lvprobe_t *p, lvprobe_hit_t *out)
{
    lv_indev_t *i = NULL;
    if (p == NULL || !p->open || !p->observing || out == NULL) {
        return LVPROBE_ERR_ARG;
    }
    p->observing = false;
    *out = p->hit;
    i = p->cfg.indev;
    if (!indev_alive(i)) {
        p->cfg.indev = NULL; /* the product deleted its indev during the tap: never touched again */
        return LVPROBE_ERR_GONE;
    }
    if (!listening(i, p)) {
        return LVPROBE_ERR_LVGL; /* removed during the tap: what it did not see is unknown */
    }
    if (p->obs_presses > 1u || p->obs_clicks > 1u) {
        return LVPROBE_ERR_UNSTABLE;
    }
    if ((p->obs_blocked && !out->pressed && !out->clicked) || release_pending(i)) {
        return LVPROBE_ERR_BLOCKED;
    }
    return LVPROBE_OK;
}
