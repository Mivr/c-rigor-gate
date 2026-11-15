/* gate//ui/lvprobe: hit injection and the hit query (3). Injection goes through a real LVGL pointer indev: the
 * product's own when it gave one (only its read callback is replaced, for the two reads of a tap), else the probe's.
 * LVGL's indev processing finds the object and sends the events; the probe reads the pressed object right after the
 * press and listens on the indev for LV_EVENT_CLICKED. The query calls LVGL's lv_indev_search_obj and nothing else. */
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

/* LV_EVENT_CLICKED on the indev: its parameter is the object LVGL sends the click to. */
static void clicked_cb(lv_event_t *e)
{
    lvprobe_t *p = lv_event_get_user_data(e);
    lv_obj_t *obj = lv_event_get_param(e);
    if (p == NULL || !p->tapping || lv_event_get_code(e) != LV_EVENT_CLICKED) {
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
    return lv_indev_add_event_cb(p->cfg.indev, clicked_cb, LV_EVENT_CLICKED, p) != NULL ? LVPROBE_OK
                                                                                        : LVPROBE_ERR_LVGL;
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
            lv_indev_delete(p->cfg.indev);
        } else {
            (void)lv_indev_remove_event_cb_with_user_data(p->cfg.indev, clicked_cb, p);
        }
    }
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
    if (p == NULL || !p->open || out == NULL || p->cfg.indev == NULL || !point_ok(p, x, y)) {
        return LVPROBE_ERR_ARG;
    }
    if (blocked(p->cfg.indev)) {
        return LVPROBE_ERR_BLOCKED; /* before the walk check: a screen load also changes the tree */
    }
    st = lvp_current(p, false);
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
    if (p == NULL || !p->open || node == NULL || obj == NULL || !point_ok(p, x, y)) {
        return LVPROBE_ERR_ARG;
    }
    st = lvp_current(p, false);
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
