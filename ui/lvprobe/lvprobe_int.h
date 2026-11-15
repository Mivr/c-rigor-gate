/* Internal declarations shared by the files of gate//ui/lvprobe. Not part of the interface: callers include
 * "ui/lvprobe/lvprobe.h" only (this header is exported because the library's own files share it). */
#ifndef UI_LVPROBE_LVPROBE_INT_H
#define UI_LVPROBE_LVPROBE_INT_H

#include "ui/lvprobe/lvprobe.h"

/* Upper bound of objects one pre-order traversal visits (a bound for the loop, far above LVPROBE_MAX_NODES). */
#define LVP_VISIT_CAP 65536u

/* probe.c */
void lvp_event_cb(lv_event_t *e);
lv_obj_t *lvp_next(lv_obj_t *obj, const lv_obj_t *root, int32_t *depth);
lvprobe_status_t lvp_attach_tree(lvprobe_t *p, lv_obj_t *root);
bool lvp_has_cb(lv_obj_t *obj, const lvprobe_t *p);
/* Mark (node.seen) the nodes whose object is reached from the display's roots and carries the probe's callback. */
void lvp_live_scan(lvprobe_t *p);
void lvp_sort_nodes(lvprobe_t *p);
int32_t lvp_find_addr(const lvprobe_t *p, const void *addr, bool live); /* live: only nodes not deleted */
/* The walk is valid for an encoder or a lookup: it succeeded, nothing changed since, the display exists. */
bool lvp_walk_valid(const lvprobe_t *p);
/* Every walked node is reached and as walked (parent, index among siblings, hidden, clickable): OK, GONE or STALE. */
lvprobe_status_t lvp_tree_current(lvprobe_t *p);
const char *lvp_class_name(const lv_obj_t *obj);
bool lvp_box_empty(const lv_area_t *a);
bool lvp_box_in(const lv_area_t *inner, const lv_area_t *outer);
void lvp_box_add(lv_area_t *acc, bool *has, const lv_area_t *a);
bool lvp_box_cut(lv_area_t *acc, const lv_area_t *with); /* acc = acc and with; false when empty */
bool lvp_settled(const lvprobe_t *p);
/* Open, walked, no structural change since the walk (new screens are looked for first), settled if asked. */
lvprobe_status_t lvp_current(lvprobe_t *p, bool need_settled);
void lvp_display_area(const lvprobe_t *p, lv_area_t *a);

/* life.c */
void lvp_on_created(lvprobe_t *p, lv_obj_t *child);
void lvp_on_deleted(lvprobe_t *p, lv_obj_t *obj);
/* Compare the display's screens with the observed ones: observe new ones (logging their subtree as created and
 * late when `log`), forget deleted ones. */
lvprobe_status_t lvp_scan_screens(lvprobe_t *p, bool log);

/* walk.c */
void lvp_child_clip_box(const lvprobe_node_t *n, lv_area_t *box);
bool lvp_draw_chain(const lvprobe_t *p, const lvprobe_node_t *n); /* LVGL would draw it (no hidden, opa 0) */

/* label.c */
lvprobe_status_t lvp_label_facts(lvprobe_t *p, lvprobe_node_t *n);
lvprobe_status_t lvp_label_draw(lvprobe_t *p, uint16_t index);

/* pixels.c */
const lv_draw_buf_t *lvp_frame_buf(const lvprobe_t *p);
uint32_t lvp_pixel(const lv_draw_buf_t *b, int32_t x, int32_t y);
bool lvp_clip_to_frame(const lv_draw_buf_t *b, const lv_area_t *in, lv_area_t *out);

/* hit.c */
lvprobe_status_t lvp_indev_open(lvprobe_t *p, lv_indev_t *indev);
void lvp_indev_close(lvprobe_t *p);

#endif /* UI_LVPROBE_LVPROBE_INT_H */
