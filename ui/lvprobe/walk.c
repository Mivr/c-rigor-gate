/* gate//ui/lvprobe: the O3 tree walk (1): what LVGL laid out, read without rendering anything. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_draw_private.h"

/* The box an object clips its children to (lv_obj_redraw): its coords, or coords + ext draw size when its
 * overflow is visible. */
void lvp_child_clip_box(const lvprobe_node_t *n, lv_area_t *box)
{
    int32_t ext = lv_obj_is_overflow_visible(n->obj) ? lv_obj_get_ext_draw_size(n->obj) : 0;
    *box = n->coords;
    box->x1 -= ext;
    box->y1 -= ext;
    box->x2 += ext;
    box->y2 += ext;
}

/* What lv_obj_refr / lv_obj_redraw check before drawing an object and before drawing its children. */
bool lvp_draw_chain(const lvprobe_t *p, const lvprobe_node_t *n)
{
    const lvprobe_node_t *cur = n;
    uint32_t steps = 0;
    while (steps <= LVPROBE_MAX_DEPTH) {
        lv_obj_t *obj = cur->obj;
        if (obj == NULL || cur->hidden || lv_obj_get_style_opa_layered(obj, LV_PART_MAIN) <= LV_OPA_MIN ||
            lv_obj_get_style_transform_scale_x(obj, LV_PART_MAIN) <= 0 ||
            lv_obj_get_style_transform_scale_y(obj, LV_PART_MAIN) <= 0) {
            return false;
        }
        if (cur != n && lv_obj_get_style_opa_recursive(obj, LV_PART_MAIN) <= LV_OPA_MIN) {
            return false; /* the layer opacity at this ancestor stops its children */
        }
        if (cur->parent == LVPROBE_NONE) {
            return true;
        }
        cur = &p->nodes[cur->parent];
        steps++;
    }
    return false;
}

static int16_t clip_ancestor(const lvprobe_t *p, const lvprobe_node_t *n)
{
    int16_t at = n->parent;
    uint32_t steps = 0;
    while (at != LVPROBE_NONE && steps < LVPROBE_MAX_DEPTH) {
        lv_area_t box;
        lvp_child_clip_box(&p->nodes[at], &box);
        if (!lvp_box_in(&n->coords, &box)) {
            return at;
        }
        at = p->nodes[at].parent;
        steps++;
    }
    return (int16_t)LVPROBE_NONE;
}

static void scroll_ancestor(const lvprobe_t *p, lvprobe_node_t *n)
{
    int16_t at = n->parent;
    uint32_t steps = 0;
    n->scroll = (int16_t)LVPROBE_NONE;
    while (at != LVPROBE_NONE && steps < LVPROBE_MAX_DEPTH) {
        lv_obj_t *obj = p->nodes[at].obj;
        if (lv_obj_is_scrollable(obj) && (lv_obj_get_scroll_top(obj) > 0 || lv_obj_get_scroll_bottom(obj) > 0 ||
                                          lv_obj_get_scroll_left(obj) > 0 || lv_obj_get_scroll_right(obj) > 0)) {
            n->scroll = at;
            n->scroll_x = lv_obj_get_scroll_x(obj);
            n->scroll_y = lv_obj_get_scroll_y(obj);
            return;
        }
        at = p->nodes[at].parent;
        steps++;
    }
}

/* bg_opa scaled the way the renderer scales it: own and inherited `opa`, own and ancestors' `opa_layered`. */
static uint8_t drawn_opa(const lvprobe_t *p, const lvprobe_node_t *n)
{
    lv_opa_t opa = lv_obj_get_style_opa_recursive(n->obj, LV_PART_MAIN);
    lv_opa_t v = opa < LV_OPA_MAX ? LV_OPA_MIX2(n->bg_opa, opa) : n->bg_opa; /* LVGL mixes below LV_OPA_MAX only */
    const lvprobe_node_t *cur = n;
    uint32_t steps = 0;
    while (steps <= LVPROBE_MAX_DEPTH) {
        lv_opa_t layered = lv_obj_get_style_opa_layered(cur->obj, LV_PART_MAIN);
        if (layered < LV_OPA_MAX) {
            v = LV_OPA_MIX2(v, layered);
        }
        if (cur->parent == LVPROBE_NONE) {
            break;
        }
        cur = &p->nodes[cur->parent];
        steps++;
    }
    return v;
}

static void style_facts(const lvprobe_t *p, lvprobe_node_t *n)
{
    lv_obj_t *obj = n->obj;
    lv_color_t bg = lv_obj_get_style_bg_color_filtered(obj, LV_PART_MAIN);
    n->bg_rgb = ((uint32_t)bg.red << 16) | ((uint32_t)bg.green << 8) | (uint32_t)bg.blue;
    n->bg_opa = lv_obj_get_style_bg_opa(obj, LV_PART_MAIN);
    n->bg_opa_drawn = drawn_opa(p, n);
    n->bg_grad = lv_obj_get_style_bg_grad_dir(obj, LV_PART_MAIN) != LV_GRAD_DIR_NONE ||
                 lv_obj_get_style_bg_grad(obj, LV_PART_MAIN) != NULL;
    n->bg_image = lv_obj_get_style_bg_image_src(obj, LV_PART_MAIN) != NULL;
}

static lvprobe_status_t add_node(lvprobe_t *p, lv_obj_t *obj, int32_t depth)
{
    static const lvprobe_node_t zero;
    lvprobe_node_t *n;

    if (p->count >= LVPROBE_MAX_NODES || depth < 0 || depth >= LVPROBE_MAX_DEPTH) {
        return LVPROBE_ERR_FULL;
    }
    n = &p->nodes[p->count];
    *n = zero;
    n->obj = obj;
    n->addr = obj;
    n->class_name = lvp_class_name(obj);
    n->depth = (uint8_t)depth;
    n->parent = depth == 0 ? (int16_t)LVPROBE_NONE : (int16_t)lvprobe_find(p, lv_obj_get_parent(obj));
    n->hidden = lv_obj_is_hidden(obj);
    n->clickable = lv_obj_is_clickable(obj);
    n->font_id = LVPROBE_FONT_UNMAPPED;
    n->glyphs.x2 = -1;
    n->visible.x2 = -1;
    n->ink_box.x2 = -1;
    lv_obj_get_coords(obj, &n->coords);
    p->count++;
    n->clip = clip_ancestor(p, n);
    scroll_ancestor(p, n);
    style_facts(p, n);
    return lv_obj_has_class(obj, &lv_label_class) ? lvp_label_facts(p, n) : LVPROBE_OK;
}

static lvprobe_status_t collect(lvprobe_t *p)
{
    lv_display_t *d = p->disp;
    lv_obj_t *roots[4] = {lv_display_get_layer_bottom(d), lv_display_get_screen_active(d),
                          lv_display_get_layer_top(d), lv_display_get_layer_sys(d)};
    uint32_t r;
    lvprobe_status_t st = LVPROBE_OK;

    for (r = 0; r < 4u && st == LVPROBE_OK; r++) {
        lv_obj_t *obj = roots[r];
        int32_t depth = 0;
        uint32_t visits = 0;
        while (obj != NULL && st == LVPROBE_OK && visits < LVP_VISIT_CAP) {
            st = add_node(p, obj, depth);
            visits++;
            obj = lvp_next(obj, roots[r], &depth);
        }
    }
    return st;
}

lvprobe_status_t lvprobe_walk(lvprobe_t *p)
{
    lvprobe_status_t st;
    uint32_t gen;
    uint16_t i;
    if (p == NULL || !p->open) {
        return LVPROBE_ERR_ARG;
    }
    p->walked = false;
    p->count = 0;
    p->text_used = 0;
    p->has_frame = false;
    st = lvp_scan_screens(p, true);
    if (st == LVPROBE_OK && !lvp_settled(p)) {
        st = LVPROBE_ERR_UNSETTLED;
    }
    gen = p->gen;
    if (st == LVPROBE_OK) {
        st = collect(p);
    }
    for (i = 0; i < p->count && st == LVPROBE_OK; i++) {
        st = p->nodes[i].is_label ? lvp_label_draw(p, i) : LVPROBE_OK;
    }
    if (st == LVPROBE_OK && p->gen != gen) {
        st = LVPROBE_ERR_STALE; /* a draw handler of the product created or deleted objects */
    }
    if (st == LVPROBE_OK && p->fault != LVPROBE_OK) {
        st = p->fault;
        p->fault = LVPROBE_OK;
    }
    if (st != LVPROBE_OK) {
        p->count = 0;
        return st;
    }
    p->walked = true;
    p->walk_gen = gen;
    p->walk_screen = lv_display_get_screen_active(p->disp);
    return LVPROBE_OK;
}
