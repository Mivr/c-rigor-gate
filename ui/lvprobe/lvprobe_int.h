/* Internal declarations shared by the files of gate//ui/lvprobe. Not part of the interface: callers include
 * "ui/lvprobe/lvprobe.h" only (it is exported because the library's own files share it). */
#ifndef UI_LVPROBE_LVPROBE_INT_H
#define UI_LVPROBE_LVPROBE_INT_H

#include "ui/lvprobe/lvprobe.h"

/* Upper bound of objects one pre-order traversal visits (a bound for the loop, far above LVPROBE_MAX_NODES). */
#define LVP_VISIT_CAP 65536u

/* The one event callback the probe registers on every observed object (user data: the probe). */
void lvp_event_cb(lv_event_t *e);

/* Pre-order successor of `obj` inside the subtree of `root`, or NULL at the end. `*depth` follows the moves. */
lv_obj_t *lvp_next(lv_obj_t *obj, const lv_obj_t *root, int32_t *depth);

/* Register lvp_event_cb on every object below and including `root` that does not have it yet. */
lvprobe_status_t lvp_attach_tree(lvprobe_t *p, lv_obj_t *root);

/* Attach to every screen and layer of the display. */
lvprobe_status_t lvp_attach_all(lvprobe_t *p);

/* LVGL's class name of `obj`, "?" when it has none. */
const char *lvp_class_name(const lv_obj_t *obj);

/* Called by lvp_event_cb for LV_EVENT_DRAW_TASK_ADDED while a walk captures (walk.c). */
void lvp_capture_task(lvprobe_t *p, lv_event_t *e);

/* Create the probe's pointer indev (hit.c). */
lvprobe_status_t lvp_indev_open(lvprobe_t *p);

/* Area helpers. */
bool lvp_box_empty(const lv_area_t *a);
bool lvp_box_in(const lv_area_t *inner, const lv_area_t *outer);
void lvp_box_add(lv_area_t *acc, bool *has, const lv_area_t *a);

#endif /* UI_LVPROBE_LVPROBE_INT_H */
