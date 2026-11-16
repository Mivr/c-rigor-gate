/* gate//ui/lvprobe: ink attribution (2) and luminance samples (4). The node is kept from being drawn by a
 * the object's own `hidden` bit set directly for the measurement (no layout mark, no focus move, no style, no event,
 * no allocation). Every walked node's coords, the focus and the restored pixels are checked. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_draw_private.h"
#include "src/core/lv_obj_private.h"
#include "src/core/lv_obj_style_private.h"

typedef struct {
    lv_obj_t *focus_default;
    lv_obj_t *focus_own;
    uint16_t hidden; /* the object's own `hidden` bit before the measurement */
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
            p->cfg.scratch[k] = lvp_pixel(b, x, y);
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
            if (p->cfg.scratch[k] != lvp_pixel(b, x, y)) {
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
            uint32_t with = p->cfg.scratch[k];
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

/* Every walked node is still live and where the walk saw it. Only live nodes are dereferenced. */
static bool coords_kept(lvprobe_t *p)
{
    uint16_t i;
    bool kept = true;
    lvp_live_scan(p);
    for (i = 0; i < p->count && kept; i++) {
        const lvprobe_node_t *n = &p->cfg.nodes[i];
        lv_area_t now;
        if (!n->seen) {
            kept = false;
            break;
        }
        lv_obj_get_coords(n->obj, &now);
        kept = now.x1 == n->coords.x1 && now.y1 == n->coords.y1 && now.x2 == n->coords.x2 && now.y2 == n->coords.y2;
    }
    return kept;
}

/* LVGL's `rendered` marks of the live nodes, saved before the refreshes and put back after (revealing what an opaque
 * node covers makes LVGL mark it rendered). */
static void rendered_marks(lvprobe_t *p, bool restore)
{
    uint16_t i;
    for (i = 0; i < p->count; i++) {
        lvprobe_node_t *n = &p->cfg.nodes[i];
        if (!n->reached) {
            continue;
        }
        if (!restore) {
            n->was_rendered = n->obj->rendered != 0u;
        } else if (!n->was_rendered) {
            n->obj->rendered = 0;
        }
    }
}

/* A signature of the ancestors' scrollbar areas where they touch the diff box `box` (hiding a child can change a
 * scrollbar there, and those pixels are not the child's ink). Scrollbars elsewhere do not enter the diff. */
static uint32_t scrollbars(const lvprobe_t *p, const lvprobe_node_t *n, const lv_area_t *box)
{
    uint32_t h = 2166136261u;
    int16_t at = n->parent;
    uint32_t steps = 0;
    while (at != LVPROBE_NONE && steps < LVPROBE_MAX_DEPTH) {
        lv_area_t a[2];
        uint32_t k;
        lv_obj_get_scrollbar_area(p->cfg.nodes[at].obj, &a[0], &a[1]);
        for (k = 0; k < 2u; k++) {
            if (lvp_box_empty(&a[k]) || !lvp_box_cut(&a[k], box)) {
                continue;
            }
            h = (h ^ (uint32_t)a[k].x1) * 16777619u;
            h = (h ^ (uint32_t)a[k].y1) * 16777619u;
            h = (h ^ (uint32_t)a[k].x2) * 16777619u;
            h = (h ^ (uint32_t)a[k].y2) * 16777619u;
        }
        at = p->cfg.nodes[at].parent;
        steps++;
    }
    return h;
}

/* The node or an ancestor is transformed: its pixels are not inside its untransformed box. */
static bool transformed(const lvprobe_t *p, const lvprobe_node_t *n)
{
    const lvprobe_node_t *cur = n;
    uint32_t steps = 0;
    while (steps <= LVPROBE_MAX_DEPTH) {
        lv_obj_t *o = cur->obj;
        if (lv_obj_get_style_transform_rotation(o, LV_PART_MAIN) != 0 ||
            lv_obj_get_style_transform_scale_x(o, LV_PART_MAIN) != LV_SCALE_NONE ||
            lv_obj_get_style_transform_scale_y(o, LV_PART_MAIN) != LV_SCALE_NONE ||
            lv_obj_get_style_transform_skew_x(o, LV_PART_MAIN) != 0 ||
            lv_obj_get_style_transform_skew_y(o, LV_PART_MAIN) != 0) {
            return true;
        }
        if (cur->parent == LVPROBE_NONE) {
            return false;
        }
        cur = &p->cfg.nodes[cur->parent];
        steps++;
    }
    return true;
}

static lv_obj_t *focused(lv_group_t *g)
{
    return g != NULL ? lv_group_get_focused(g) : NULL;
}

/* A style transition of the node is running: its styles would differ after the measurement. */
static bool in_transition(const lv_obj_t *obj)
{
    uint32_t i;
    for (i = 0; i < obj->style_cnt; i++) {
        if (obj->styles[i].is_trans) {
            return true;
        }
    }
    return false;
}

/* Add the probe's opa = 0 style for the node's current state; false (and nothing left behind) when it does
 * not win (a local or more specific style sets opa). */
/* Keep the node from being drawn: invalidate it, then set LVGL's own `hidden` bit directly. lv_obj_refr skips a hidden
 * object and its subtree. Unlike lv_obj_set_hidden this marks no layout dirty (the display is settled, so no layout
 * runs: siblings stay put; any layout that did run would move a node and be caught) and moves no focus; no style,
 * event or allocation. */
static void suppress(lv_obj_t *obj, undo_t *u)
{
    u->focus_default = focused(lv_group_get_default());
    u->focus_own = focused(lv_obj_get_group(obj));
    u->hidden = obj->hidden;
    lv_obj_invalidate(obj);
    obj->hidden = 1;
}

/* Only for a node that is still live: the saved bit comes back, never a plain 0. */
static bool restore(lv_obj_t *obj, const undo_t *u)
{
    obj->hidden = u->hidden & 1u;
    lv_obj_invalidate(obj);
    return focused(lv_group_get_default()) == u->focus_default && focused(lv_obj_get_group(obj)) == u->focus_own;
}

/* One refresh that must flush and leave the display settled. */
static bool refresh(lvprobe_t *p)
{
    p->flushes = 0;
    lv_refr_now(p->disp);
    return p->flushes > 0u && lvp_settled(p);
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
    if (*any && (size_t)lv_area_get_size(a) > p->cfg.scratch_px) {
        return LVPROBE_ERR_FULL;
    }
    return LVPROBE_OK;
}

static lvprobe_status_t unstable(lvprobe_node_t *n, lvprobe_status_t st)
{
    clear_ink(n);
    n->unstable = st == LVPROBE_ERR_UNSTABLE;
    return st;
}

/* After a node moved, lay its parent out again (with the node drawn) so the second refresh puts the siblings back. */
static void relayout(lvprobe_t *p, const lvprobe_node_t *n)
{
    if (n->parent != LVPROBE_NONE && p->cfg.nodes[n->parent].reached) {
        lv_obj_mark_layout_as_dirty(p->cfg.nodes[n->parent].obj);
    }
}

static lvprobe_status_t measure(lvprobe_t *p, const lv_draw_buf_t *b, lvprobe_node_t *n, const lv_area_t *a)
{
    undo_t u;
    bool ok;
    bool kept;
    uint32_t gen = p->gen;
    uint32_t bars = scrollbars(p, n, a);
    if (in_transition(n->obj) || lv_anim_count_running() > 0u) {
        return unstable(n, LVPROBE_ERR_UNSTABLE); /* refused before anything changed */
    }
    save_box(p, b, a);
    rendered_marks(p, false);
    suppress(n->obj, &u);
    ok = scrollbars(p, n, a) == bars;
    ok = refresh(p) && ok;
    kept = coords_kept(p);
    if (!n->reached) {
        return unstable(n, LVPROBE_ERR_GONE); /* deleted by a handler during the refresh: nothing to restore */
    }
    diff_box(p, b, a, n);
    ok = restore(n->obj, &u) && ok && kept;
    if (!kept) {
        relayout(p, n);
    }
    ok = refresh(p) && ok;
    ok = coords_kept(p) && ok && box_unchanged(p, b, a) && p->gen == gen;
    rendered_marks(p, true);
    if (!n->reached) {
        return unstable(n, LVPROBE_ERR_GONE);
    }
    if (!ok) {
        return unstable(n, LVPROBE_ERR_UNSTABLE);
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

    if (st == LVPROBE_OK && (index >= p->count || p->cfg.nodes[index].parent == LVPROBE_NONE)) {
        st = LVPROBE_ERR_ARG; /* out of range, or a screen or layer root (refused) */
    }
    if (st == LVPROBE_OK) {
        st = lvp_tree_current(p); /* every node reached and as walked: checked before any dereference */
    }
    if (st != LVPROBE_OK) {
        return st;
    }
    n = &p->cfg.nodes[index];
    b = lvp_frame_buf(p);
    if (b == NULL) {
        return LVPROBE_ERR_FORMAT;
    }
    clear_ink(n);
    n->ink_unsupported = false;
    if (!coords_kept(p)) {
        return unstable(n, LVPROBE_ERR_UNSTABLE);
    }
    if (transformed(p, n)) {
        n->ink_unsupported = true;
        return LVPROBE_ERR_UNSUPPORTED;
    }
    if (!lvp_draw_chain(p, n)) {
        n->has_ink = true; /* LVGL draws nothing of it: ink 0, nothing refreshed */
        return LVPROBE_OK;
    }
    st = ink_region(p, b, n, &a, &any);
    if (st != LVPROBE_OK || !any) {
        n->has_ink = st == LVPROBE_OK;
        return st;
    }
    return measure(p, b, n, &a);
}
