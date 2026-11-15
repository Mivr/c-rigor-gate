/* gate//ui/lvprobe: open and close, settling, the node table, the event callbacks, area helpers. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_class_private.h"
#include "src/core/lv_obj_private.h"
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

bool lvp_box_cut(lv_area_t *acc, const lv_area_t *with)
{
    acc->x1 = with->x1 > acc->x1 ? with->x1 : acc->x1;
    acc->y1 = with->y1 > acc->y1 ? with->y1 : acc->y1;
    acc->x2 = with->x2 < acc->x2 ? with->x2 : acc->x2;
    acc->y2 = with->y2 < acc->y2 ? with->y2 : acc->y2;
    return !lvp_box_empty(acc);
}

void lvp_display_area(const lvprobe_t *p, lv_area_t *a)
{
    a->x1 = 0;
    a->y1 = 0;
    a->x2 = lv_display_get_horizontal_resolution(p->disp) - 1;
    a->y2 = lv_display_get_vertical_resolution(p->disp) - 1;
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

bool lvp_has_cb(lv_obj_t *obj, const lvprobe_t *p)
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
        if (!lvp_has_cb(obj, p) && lv_obj_add_event_cb(obj, lvp_event_cb, LV_EVENT_ALL, p) == NULL) {
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

/* The three layers of the display (bottom, top, sys), which LVGL keeps outside the screen list. */
static void layers(const lvprobe_t *p, lv_obj_t *out[3])
{
    out[0] = p->disp->bottom_layer;
    out[1] = p->disp->top_layer;
    out[2] = p->disp->sys_layer;
}

static void display_cb(lv_event_t *e)
{
    lvprobe_t *p = lv_event_get_user_data(e);
    if (p != NULL && p->open && lv_event_get_code(e) == LV_EVENT_FLUSH_START) {
        p->flushes++;
    }
}

static lvprobe_status_t attach_start(lvprobe_t *p, lv_indev_t *indev)
{
    lv_obj_t *roots[3];
    uint32_t i;
    lvprobe_status_t st = LVPROBE_OK;

    if (lv_display_add_event_cb(p->disp, display_cb, LV_EVENT_FLUSH_START, p) == NULL) {
        return LVPROBE_ERR_LVGL;
    }
    st = lvp_indev_open(p, indev);
    layers(p, roots);
    for (i = 0; i < 3u && st == LVPROBE_OK; i++) {
        st = roots[i] != NULL ? lvp_attach_tree(p, roots[i]) : LVPROBE_OK;
    }
    return st == LVPROBE_OK ? lvp_scan_screens(p, false) : st;
}

static bool config_ok(const lvprobe_config_t *c)
{
    return c->nodes != NULL && c->max_nodes > 0u && c->max_nodes <= INT16_MAX && c->text != NULL &&
           c->text_bytes > 0u && c->life != NULL && c->life_cap > 0u && c->screens != NULL && c->max_screens > 0u &&
           c->scratch != NULL && c->scratch_px > 0u;
}

lvprobe_status_t lvprobe_open(lvprobe_t *p, lv_display_t *disp, const lvprobe_config_t *cfg)
{
    static const lvprobe_t closed;
    lvprobe_status_t st;

    if (p == NULL || disp == NULL || cfg == NULL || p->open || !config_ok(cfg) ||
        (cfg->indev != NULL && lv_indev_get_display(cfg->indev) != disp)) {
        return LVPROBE_ERR_ARG;
    }
    if (lv_display_get_refr_timer(disp) == NULL) {
        return LVPROBE_ERR_FORMAT; /* lv_refr_now could not refresh it */
    }
    *p = closed;
    p->disp = disp;
    p->cfg = *cfg;
    p->hit.node = LVPROBE_NONE;
    p->hit.pressed_node = LVPROBE_NONE;
    p->glyph_node = LVPROBE_NONE;
    p->open = true;
    st = attach_start(p, cfg->indev);
    if (st != LVPROBE_OK) {
        lvprobe_close(p);
    }
    return st;
}

/* The display is still one of LVGL's (compared by address only). */
static bool display_alive(const lv_display_t *disp)
{
    lv_display_t *d = lv_display_get_next(NULL);
    uint32_t guard = 0;
    while (d != NULL && guard < LVP_VISIT_CAP) {
        if (d == disp) {
            return true;
        }
        d = lv_display_get_next(d);
        guard++;
    }
    return false;
}

void lvprobe_close(lvprobe_t *p)
{
    lv_obj_t *roots[3];
    uint32_t i;
    if (p == NULL || !p->open) {
        return;
    }
    if (display_alive(p->disp)) {
        layers(p, roots);
        for (i = 0; i < 3u; i++) {
            if (roots[i] != NULL) {
                detach_tree(p, roots[i]);
            }
        }
        for (i = 0; i < p->disp->screen_cnt; i++) { /* the display's own list: only live screens */
            detach_tree(p, p->disp->screens[i]);
        }
        (void)lv_display_remove_event_cb_with_user_data(p->disp, display_cb, p);
    }
    lvp_indev_close(p);
    p->open = false;
}

/* Mark the nodes whose object is reached from the display's screens and layers and still carries the probe's
 * callback. Only reached objects are dereferenced; a node that is not marked is not used. */
void lvp_live_scan(lvprobe_t *p)
{
    lv_obj_t *roots[3];
    uint32_t r;
    uint16_t i;
    for (i = 0; i < p->count; i++) {
        p->cfg.nodes[i].seen = false;
    }
    layers(p, roots);
    for (r = 0; r < p->disp->screen_cnt + 3u; r++) {
        lv_obj_t *root = r < p->disp->screen_cnt ? p->disp->screens[r] : roots[r - p->disp->screen_cnt];
        lv_obj_t *obj = root;
        int32_t depth = 0;
        uint32_t visits = 0;
        while (obj != NULL && visits < LVP_VISIT_CAP) {
            int32_t at = lvprobe_find(p, obj);
            if (at != LVPROBE_NONE && lvp_has_cb(obj, p)) {
                p->cfg.nodes[at].seen = true;
            }
            visits++;
            obj = lvp_next(obj, root, &depth);
        }
    }
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

/* No dirty area and no pending layout on any drawn root: the buffer holds what LVGL shows. */
bool lvp_settled(const lvprobe_t *p)
{
    lv_obj_t *roots[4];
    uint32_t i;
    layers(p, roots);
    roots[3] = p->disp->act_scr;
    if (p->disp->inv_p != 0u) {
        return false;
    }
    for (i = 0; i < 4u; i++) {
        if (roots[i] != NULL && (roots[i]->scr_layout_inv || roots[i]->layout_inv)) {
            return false;
        }
    }
    return true;
}

lvprobe_status_t lvprobe_settle(lvprobe_t *p, bool *flushed)
{
    if (p == NULL || !p->open || flushed == NULL) {
        return LVPROBE_ERR_ARG;
    }
    p->flushes = 0;
    lv_refr_now(p->disp);
    *flushed = p->flushes > 0u;
    return LVPROBE_OK;
}

lvprobe_status_t lvp_current(lvprobe_t *p, bool need_settled)
{
    lvprobe_status_t st;
    if (p == NULL || !p->open) {
        return LVPROBE_ERR_ARG;
    }
    st = lvp_scan_screens(p, true);
    if (st != LVPROBE_OK) {
        return st;
    }
    if (!p->walked || p->gen != p->walk_gen || lv_display_get_screen_active(p->disp) != p->walk_screen) {
        return LVPROBE_ERR_STALE;
    }
    return (need_settled && !lvp_settled(p)) ? LVPROBE_ERR_UNSETTLED : LVPROBE_OK;
}

uint16_t lvprobe_count(const lvprobe_t *p)
{
    return p == NULL ? 0u : p->count;
}

const lvprobe_node_t *lvprobe_node(const lvprobe_t *p, uint16_t index)
{
    return (p == NULL || index >= p->count) ? NULL : &p->cfg.nodes[index];
}

int32_t lvprobe_find(const lvprobe_t *p, const lv_obj_t *obj)
{
    uint16_t i;
    if (p == NULL || obj == NULL) {
        return LVPROBE_NONE;
    }
    for (i = 0; i < p->count; i++) {
        if (p->cfg.nodes[i].obj == obj) {
            return (int32_t)i;
        }
    }
    return LVPROBE_NONE;
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
            p->gen++;
            lvp_on_created(p, child);
        }
    } else if (code == LV_EVENT_DELETE) {
        p->gen++;
        lvp_on_deleted(p, self);
    }
}
