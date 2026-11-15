/* gate//ui/lvprobe: open and close, the node table, the event callback and the lifecycle log (5). */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_class_private.h"
#include "src/display/lv_display_private.h"

bool lvp_box_empty(const lv_area_t *a)
{
    return a->x2 < a->x1 || a->y2 < a->y1;
}

bool lvp_box_in(const lv_area_t *inner, const lv_area_t *outer)
{
    return inner->x1 >= outer->x1 && inner->y1 >= outer->y1 && inner->x2 <= outer->x2 && inner->y2 <= outer->y2;
}

void lvp_box_add(lv_area_t *acc, bool *has, const lv_area_t *a)
{
    if (lvp_box_empty(a)) {
        return;
    }
    if (!*has) {
        *acc = *a;
        *has = true;
        return;
    }
    acc->x1 = a->x1 < acc->x1 ? a->x1 : acc->x1;
    acc->y1 = a->y1 < acc->y1 ? a->y1 : acc->y1;
    acc->x2 = a->x2 > acc->x2 ? a->x2 : acc->x2;
    acc->y2 = a->y2 > acc->y2 ? a->y2 : acc->y2;
}

const char *lvp_class_name(const lv_obj_t *obj)
{
    const lv_obj_class_t *cls = lv_obj_get_class(obj);
    return (cls != NULL && cls->name != NULL) ? cls->name : "?";
}

lv_obj_t *lvp_next(lv_obj_t *obj, const lv_obj_t *root, int32_t *depth)
{
    lv_obj_t *cur = obj;
    uint32_t guard = 0;

    if (lv_obj_get_child_count(cur) > 0u) {
        *depth += 1;
        return lv_obj_get_child(cur, 0);
    }
    while (cur != root && guard < LVP_VISIT_CAP) {
        lv_obj_t *parent = lv_obj_get_parent(cur);
        int32_t at = lv_obj_get_index(cur);
        guard++;
        if (parent == NULL || at < 0) {
            return NULL;
        }
        if ((uint32_t)at + 1u < lv_obj_get_child_count(parent)) {
            return lv_obj_get_child(parent, at + 1);
        }
        cur = parent;
        *depth -= 1;
    }
    return NULL;
}

static bool has_cb(lv_obj_t *obj, const lvprobe_t *p)
{
    uint32_t n = lv_obj_get_event_count(obj);
    uint32_t i;
    for (i = 0; i < n; i++) {
        lv_event_dsc_t *dsc = lv_obj_get_event_dsc(obj, i);
        if (dsc != NULL && lv_event_dsc_get_cb(dsc) == lvp_event_cb && lv_event_dsc_get_user_data(dsc) == p) {
            return true;
        }
    }
    return false;
}

lvprobe_status_t lvp_attach_tree(lvprobe_t *p, lv_obj_t *root)
{
    lv_obj_t *obj = root;
    int32_t depth = 0;
    uint32_t visits = 0;

    while (obj != NULL && visits < LVP_VISIT_CAP) {
        if (!has_cb(obj, p) && lv_obj_add_event_cb(obj, lvp_event_cb, LV_EVENT_ALL, p) == NULL) {
            return LVPROBE_ERR_LVGL;
        }
        visits++;
        obj = lvp_next(obj, root, &depth);
    }
    return obj == NULL ? LVPROBE_OK : LVPROBE_ERR_FULL;
}

static void detach_tree(lvprobe_t *p, lv_obj_t *root)
{
    lv_obj_t *obj = root;
    int32_t depth = 0;
    uint32_t visits = 0;

    while (obj != NULL && visits < LVP_VISIT_CAP) {
        (void)lv_obj_remove_event_cb_with_user_data(obj, lvp_event_cb, p);
        visits++;
        obj = lvp_next(obj, root, &depth);
    }
}

/* Every screen of the display and its three layers (the layers are screens of LVGL too; attaching is idempotent). */
static lvprobe_status_t for_each_root(lvprobe_t *p, bool attach)
{
    lv_display_t *d = p->disp;
    lv_obj_t *layers[3] = {d->bottom_layer, d->top_layer, d->sys_layer};
    uint32_t i;
    lvprobe_status_t st = LVPROBE_OK;

    for (i = 0; i < d->screen_cnt + 3u && st == LVPROBE_OK; i++) {
        lv_obj_t *root = i < d->screen_cnt ? d->screens[i] : layers[i - d->screen_cnt];
        if (root == NULL) {
            continue;
        }
        if (attach) {
            st = lvp_attach_tree(p, root);
        } else {
            detach_tree(p, root);
        }
    }
    return st;
}

lvprobe_status_t lvp_attach_all(lvprobe_t *p)
{
    return for_each_root(p, true);
}

lvprobe_status_t lvprobe_open(lvprobe_t *p, lv_display_t *disp, uint32_t *scratch, size_t scratch_px)
{
    static const lvprobe_t closed;
    lvprobe_status_t st;

    if (p == NULL || disp == NULL || scratch == NULL || scratch_px == 0u) {
        return LVPROBE_ERR_ARG;
    }
    *p = closed;
    p->disp = disp;
    p->scratch = scratch;
    p->scratch_px = scratch_px;
    p->hit.node = LVPROBE_NONE;
    p->open = true;
    st = lvp_indev_open(p);
    if (st == LVPROBE_OK) {
        st = lvp_attach_all(p);
    }
    if (st != LVPROBE_OK) {
        lvprobe_close(p);
    }
    return st;
}

void lvprobe_close(lvprobe_t *p)
{
    if (p == NULL || !p->open) {
        return;
    }
    (void)for_each_root(p, false);
    if (p->indev != NULL) {
        lv_indev_delete(p->indev);
        p->indev = NULL;
    }
    p->open = false;
}

lvprobe_status_t lvprobe_map_font(lvprobe_t *p, const lv_font_t *font, uint16_t id)
{
    uint16_t i;
    if (p == NULL || !p->open || font == NULL || id == LVPROBE_FONT_UNMAPPED) {
        return LVPROBE_ERR_ARG;
    }
    for (i = 0; i < p->font_count; i++) {
        if (p->fonts[i] == font) {
            p->font_ids[i] = id;
            return LVPROBE_OK;
        }
    }
    if (p->font_count >= LVPROBE_MAX_FONTS) {
        return LVPROBE_ERR_FULL;
    }
    p->fonts[p->font_count] = font;
    p->font_ids[p->font_count] = id;
    p->font_count++;
    return LVPROBE_OK;
}

uint16_t lvprobe_count(const lvprobe_t *p)
{
    return p == NULL ? 0u : p->count;
}

const lvprobe_node_t *lvprobe_node(const lvprobe_t *p, uint16_t index)
{
    return (p == NULL || index >= p->count) ? NULL : &p->nodes[index];
}

int32_t lvprobe_find(const lvprobe_t *p, const lv_obj_t *obj)
{
    uint16_t i;
    if (p == NULL || obj == NULL) {
        return LVPROBE_NONE;
    }
    for (i = 0; i < p->count; i++) {
        if (p->nodes[i].obj == obj) {
            return (int32_t)i;
        }
    }
    return LVPROBE_NONE;
}

static void life_push(lvprobe_t *p, bool created, const lv_obj_t *obj)
{
    lvprobe_life_t *e;
    p->life_seq++;
    if (p->life_count >= LVPROBE_LIFE_CAP) {
        p->life_lost++;
        return;
    }
    e = &p->life[p->life_count];
    p->life_count++;
    e->seq = p->life_seq;
    e->created = created ? 1u : 0u;
    e->node = created ? (int16_t)LVPROBE_NONE : (int16_t)lvprobe_find(p, obj);
    e->parent = (int16_t)lvprobe_find(p, lv_obj_get_parent(obj));
    e->class_name = lvp_class_name(obj);
}

/* A new child of an observed object: log it and everything below it, and observe them. */
static void on_created(lvprobe_t *p, lv_obj_t *child)
{
    lv_obj_t *obj = child;
    int32_t depth = 0;
    uint32_t visits = 0;

    while (obj != NULL && visits < LVP_VISIT_CAP) {
        life_push(p, true, obj);
        visits++;
        obj = lvp_next(obj, child, &depth);
    }
    if (lvp_attach_tree(p, child) != LVPROBE_OK) {
        p->fault = LVPROBE_ERR_LVGL;
    }
}

static void on_deleted(lvprobe_t *p, lv_obj_t *obj)
{
    int32_t at = lvprobe_find(p, obj);
    life_push(p, false, obj);
    if (at != LVPROBE_NONE) {
        p->nodes[at].obj = NULL;
    }
}

void lvp_event_cb(lv_event_t *e)
{
    lvprobe_t *p = lv_event_get_user_data(e);
    lv_event_code_t code = lv_event_get_code(e);
    lv_obj_t *self = lv_event_get_current_target(e);

    if (p == NULL || !p->open || self != lv_event_get_target(e)) {
        return; /* closed, or an event bubbling up from a child (the child reports its own) */
    }
    if (code == LV_EVENT_CHILD_CREATED) {
        lv_obj_t *child = lv_event_get_param(e);
        if (child != NULL) {
            on_created(p, child);
        }
    } else if (code == LV_EVENT_DELETE) {
        on_deleted(p, self);
    } else if (code == LV_EVENT_DRAW_TASK_ADDED && p->capturing) {
        lvp_capture_task(p, e);
    }
}

lvprobe_status_t lvprobe_life(lvprobe_t *p, lvprobe_life_t *out, uint16_t cap, uint16_t *n, uint32_t *lost)
{
    uint16_t i;
    uint16_t take;
    if (p == NULL || !p->open || n == NULL || lost == NULL || (out == NULL && cap > 0u)) {
        return LVPROBE_ERR_ARG;
    }
    take = p->life_count < cap ? p->life_count : cap;
    for (i = 0; i < take; i++) {
        out[i] = p->life[i];
    }
    *n = take;
    *lost = p->life_lost + (uint32_t)(p->life_count - take);
    p->life_count = 0;
    p->life_lost = 0;
    if (p->fault != LVPROBE_OK) {
        lvprobe_status_t f = p->fault;
        p->fault = LVPROBE_OK;
        return f;
    }
    return *lost > 0u ? LVPROBE_ERR_OVERFLOW : LVPROBE_OK;
}
