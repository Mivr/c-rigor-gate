/* gate//ui/lvprobe: hit injection (3) through a real LVGL pointer indev. LVGL's indev processing finds the object
 * (its own hit-test) and sends LV_EVENT_CLICKED; the probe only listens on the indev for that event. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

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

/* LV_EVENT_CLICKED on the indev: its parameter is the object LVGL is about to send the click to. */
static void clicked_cb(lv_event_t *e)
{
    lvprobe_t *p = lv_event_get_user_data(e);
    lv_obj_t *obj = lv_event_get_param(e);
    if (p == NULL || lv_event_get_code(e) != LV_EVENT_CLICKED) {
        return;
    }
    p->hit.clicked = obj != NULL;
    p->hit.obj = obj;
    p->hit.node = lvprobe_find(p, obj);
}

lvprobe_status_t lvp_indev_open(lvprobe_t *p)
{
    lv_indev_t *indev = lv_indev_create();
    if (indev == NULL) {
        return LVPROBE_ERR_LVGL;
    }
    p->indev = indev;
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, read_cb);
    lv_indev_set_user_data(indev, p);
    lv_indev_set_display(indev, p->disp);
    lv_indev_set_mode(indev, LV_INDEV_MODE_EVENT); /* read only when the probe taps, never by the indev timer */
    if (lv_indev_add_event_cb(indev, clicked_cb, LV_EVENT_CLICKED, p) == NULL) {
        return LVPROBE_ERR_LVGL;
    }
    return LVPROBE_OK;
}

lvprobe_status_t lvprobe_hit(lvprobe_t *p, int32_t x, int32_t y, lvprobe_hit_t *out)
{
    if (p == NULL || !p->open || p->indev == NULL || out == NULL) {
        return LVPROBE_ERR_ARG;
    }
    p->hit.clicked = false;
    p->hit.obj = NULL;
    p->hit.node = LVPROBE_NONE;
    p->press_at.x = x;
    p->press_at.y = y;
    p->pressed = true;
    lv_indev_read(p->indev);
    p->pressed = false;
    lv_indev_read(p->indev);
    *out = p->hit;
    return LVPROBE_OK;
}
