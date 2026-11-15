/* gate//ui/lvprobe: hit injection (3) through a real LVGL pointer indev: the product's own when it gave one, else
 * the probe's. LVGL's indev processing finds the object (its own hit-test) and sends the events; the probe reads the
 * pressed object right after the press and listens on the indev for LV_EVENT_CLICKED. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/display/lv_display_private.h"
#include "src/indev/lv_indev_private.h"

static void read_cb(lv_indev_t *indev, lv_indev_data_t *data)
{
    const lvprobe_t *p = lv_indev_get_user_data(indev);
    if (p == NULL) {
        return;
    }
    data->point = p->press_at;
    data->state = p->pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
    data->continue_reading = false;
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
        p->indev = indev;
        p->own_indev = false;
    } else {
        p->indev = lv_indev_create();
        if (p->indev == NULL) {
            return LVPROBE_ERR_LVGL;
        }
        p->own_indev = true;
        lv_indev_set_type(p->indev, LV_INDEV_TYPE_POINTER);
        lv_indev_set_read_cb(p->indev, read_cb);
        lv_indev_set_user_data(p->indev, p);
        lv_indev_set_display(p->indev, p->disp);
        lv_indev_set_mode(p->indev, LV_INDEV_MODE_EVENT); /* read only when the probe taps */
    }
    return lv_indev_add_event_cb(p->indev, clicked_cb, LV_EVENT_CLICKED, p) != NULL ? LVPROBE_OK : LVPROBE_ERR_LVGL;
}

void lvp_indev_close(lvprobe_t *p)
{
    if (p->indev == NULL) {
        return;
    }
    if (p->own_indev) {
        lv_indev_delete(p->indev);
    } else {
        (void)lv_indev_remove_event_cb_with_user_data(p->indev, clicked_cb, p);
    }
    p->indev = NULL;
}

/* The cases in which lv_indev_read returns without processing the point, or keeps ignoring the press. */
static bool blocked(const lvprobe_t *p)
{
    const lv_indev_t *i = p->indev;
    const lv_display_t *d = p->disp;
    return i->disp != d || !i->enabled || i->wait_until_release || d->prev_scr != NULL || d->scr_to_load != NULL;
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

static void tap(lvprobe_t *p)
{
    lv_indev_t *i = p->indev;
    lv_indev_read_cb_t cb = i->read_cb;
    void *user = i->user_data;
    lv_obj_t *act;

    i->read_cb = read_cb; /* the product's indev: its callback and user data come back after the two reads */
    i->user_data = p;
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
    i->user_data = user;
}

lvprobe_status_t lvprobe_hit(lvprobe_t *p, int32_t x, int32_t y, lvprobe_hit_t *out)
{
    lv_area_t all;
    lvprobe_status_t st;
    if (p == NULL || !p->open || out == NULL) {
        return LVPROBE_ERR_ARG;
    }
    lvp_display_area(p, &all);
    if (x < all.x1 || y < all.y1 || x > all.x2 || y > all.y2) {
        return LVPROBE_ERR_ARG; /* LVGL would clamp the point onto the edge */
    }
    if (p->indev == NULL || blocked(p)) {
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
    reset(p->indev);
    tap(p);
    *out = p->hit;
    return LVPROBE_OK;
}
