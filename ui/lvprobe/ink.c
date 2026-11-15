/* gate//ui/lvprobe: ink attribution (2) and luminance samples (4). The node is kept from being drawn by a
 * temporary local `opa_layered` = 0 (lv_obj_refr then skips it and its subtree): no flag, no layout, no focus
 * changes. Every walked node's coords, the focus and the restored pixels are checked. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_draw_private.h"

typedef struct {
    lv_style_selector_t sel;
    bool had;
    lv_style_value_t value;
    lv_obj_t *focus_default;
    lv_obj_t *focus_own;
} undo_t;

static uint32_t luma(uint32_t rgb)
{
    return 2126u * ((rgb >> 16) & 0xFFu) + 7152u * ((rgb >> 8) & 0xFFu) + 722u * (rgb & 0xFFu);
}

static void save_box(const lvprobe_t *p, const lv_draw_buf_t *b, const lv_area_t *a)
{
    size_t k = 0;
    int32_t x;
    int32_t y;
    for (y = a->y1; y <= a->y2; y++) {
        for (x = a->x1; x <= a->x2; x++) {
            p->scratch[k] = lvp_pixel(b, x, y);
            k++;
        }
    }
}

static bool box_unchanged(const lvprobe_t *p, const lv_draw_buf_t *b, const lv_area_t *a)
{
    size_t k = 0;
    int32_t x;
    int32_t y;
    for (y = a->y1; y <= a->y2; y++) {
        for (x = a->x1; x <= a->x2; x++) {
            if (p->scratch[k] != lvp_pixel(b, x, y)) {
                return false;
            }
            k++;
        }
    }
    return true;
}

static void sample(uint32_t rgb, bool first, uint32_t *lo, uint32_t *hi)
{
    if (first || luma(rgb) < luma(*lo)) {
        *lo = rgb;
    }
    if (first || luma(rgb) > luma(*hi)) {
        *hi = rgb;
    }
}

/* Saved pixels (with the node) against the current ones (without it). */
static void diff_box(const lvprobe_t *p, const lv_draw_buf_t *b, const lv_area_t *a, lvprobe_node_t *n)
{
    size_t k = 0;
    int32_t x;
    int32_t y;
    bool has = false;
    for (y = a->y1; y <= a->y2; y++) {
        for (x = a->x1; x <= a->x2; x++) {
            uint32_t with = p->scratch[k];
            uint32_t without = lvp_pixel(b, x, y);
            k++;
            if (with != without) {
                lv_area_t one = {x, y, x, y};
                sample(with, n->ink == 0u, &n->ink_lo, &n->ink_hi);
                sample(without, n->ink == 0u, &n->bg_lo, &n->bg_hi);
                n->ink++;
                lvp_box_add(&n->ink_box, &has, &one);
            }
        }
    }
}

static void clear_ink(lvprobe_node_t *n)
{
    n->has_ink = false;
    n->unstable = false;
    n->ink = 0;
    n->ink_box.x1 = 0;
    n->ink_box.y1 = 0;
    n->ink_box.x2 = -1;
    n->ink_box.y2 = -1;
    n->ink_lo = 0;
    n->ink_hi = 0;
    n->bg_lo = 0;
    n->bg_hi = 0;
}

static bool coords_kept(const lvprobe_t *p)
{
    uint16_t i;
    for (i = 0; i < p->count; i++) {
        lv_area_t now;
        if (p->nodes[i].obj == NULL || !lv_obj_is_valid(p->nodes[i].obj)) {
            return false;
        }
        lv_obj_get_coords(p->nodes[i].obj, &now);
        if (now.x1 != p->nodes[i].coords.x1 || now.y1 != p->nodes[i].coords.y1 || now.x2 != p->nodes[i].coords.x2 ||
            now.y2 != p->nodes[i].coords.y2) {
            return false;
        }
    }
    return true;
}

static lv_obj_t *focused(lv_group_t *g)
{
    return g != NULL ? lv_group_get_focused(g) : NULL;
}

static bool suppress(lv_obj_t *obj, undo_t *u)
{
    lv_style_value_t zero;
    u->sel = (lv_style_selector_t)LV_PART_MAIN | (lv_style_selector_t)lv_obj_get_state(obj);
    u->had = lv_obj_get_local_style_prop(obj, LV_STYLE_OPA_LAYERED, &u->value, u->sel) == LV_STYLE_RES_FOUND;
    u->focus_default = focused(lv_group_get_default());
    u->focus_own = focused(lv_obj_get_group(obj));
    zero.num = LV_OPA_TRANSP;
    lv_obj_set_local_style_prop(obj, LV_STYLE_OPA_LAYERED, zero, u->sel);
    return lv_obj_get_style_opa_layered(obj, LV_PART_MAIN) == LV_OPA_TRANSP;
}

static bool restore(lv_obj_t *obj, const undo_t *u)
{
    if (u->had) {
        lv_obj_set_local_style_prop(obj, LV_STYLE_OPA_LAYERED, u->value, u->sel);
    } else {
        (void)lv_obj_remove_local_style_prop(obj, LV_STYLE_OPA_LAYERED, u->sel);
    }
    return focused(lv_group_get_default()) == u->focus_default && focused(lv_obj_get_group(obj)) == u->focus_own;
}

static lvprobe_status_t ink_region(const lvprobe_t *p, const lv_draw_buf_t *b, const lvprobe_node_t *n,
                                   lv_area_t *a, bool *any)
{
    lv_area_t box = n->coords;
    int32_t ext = lv_obj_get_ext_draw_size(n->obj);
    box.x1 -= ext;
    box.y1 -= ext;
    box.x2 += ext;
    box.y2 += ext;
    *any = !lvp_box_empty(&box) && lvp_clip_to_frame(b, &box, a);
    if (*any && (size_t)lv_area_get_size(a) > p->scratch_px) {
        return LVPROBE_ERR_FULL;
    }
    return LVPROBE_OK;
}

static lvprobe_status_t measure(lvprobe_t *p, const lv_draw_buf_t *b, lvprobe_node_t *n, const lv_area_t *a)
{
    undo_t u;
    bool ok;
    uint32_t gen = p->gen;
    save_box(p, b, a);
    ok = coords_kept(p) && suppress(n->obj, &u);
    lv_refr_now(p->disp);
    ok = ok && coords_kept(p);
    diff_box(p, b, a, n);
    ok = restore(n->obj, &u) && ok;
    lv_refr_now(p->disp);
    ok = ok && coords_kept(p) && box_unchanged(p, b, a) && p->gen == gen;
    if (!ok) {
        clear_ink(n);
        n->unstable = true;
        return LVPROBE_ERR_UNSTABLE;
    }
    n->has_ink = true;
    return LVPROBE_OK;
}

lvprobe_status_t lvprobe_ink(lvprobe_t *p, uint16_t index)
{
    const lv_draw_buf_t *b;
    lvprobe_node_t *n;
    lv_area_t a;
    bool any = false;
    lvprobe_status_t st = lvp_current(p, true);

    if (st != LVPROBE_OK) {
        return st;
    }
    if (index >= p->count) {
        return LVPROBE_ERR_ARG;
    }
    n = &p->nodes[index];
    if (n->obj == NULL || !lv_obj_is_valid(n->obj)) {
        return LVPROBE_ERR_GONE;
    }
    b = lvp_frame_buf(p);
    if (b == NULL) {
        return LVPROBE_ERR_FORMAT;
    }
    clear_ink(n);
    st = ink_region(p, b, n, &a, &any);
    if (st != LVPROBE_OK || !any) {
        n->has_ink = st == LVPROBE_OK;
        return st;
    }
    return measure(p, b, n, &a);
}
