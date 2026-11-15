/* gate//ui/lvprobe: label facts (1) and the `clipped` verdict (2). The glyph boxes come from LVGL's own label
 * draw code: the label is redrawn with lv_obj_redraw into the probe's layer, which is never rendered or flushed,
 * and LVGL's character iterator places the glyphs of the label draw task it created. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_draw_private.h"
#include "src/core/lv_obj_private.h"
#include "src/draw/lv_draw_label_private.h"
#include "src/draw/lv_draw_private.h"
#include "src/misc/lv_text_private.h"
#include "src/widgets/label/lv_label_private.h"

/* lv_label.c:33 (LV_LABEL_DOT_BEGIN_INV, private to that file): no dots are set. */
#define LVP_DOT_BEGIN_INV 0xFFFFFFFFu

/* Append `len` bytes (or up to the NUL when len is SIZE_MAX) to the text pool; false when it is full. */
static bool pool_put(lvprobe_t *p, const char *s, size_t len)
{
    size_t i;
    for (i = 0; i < len && s[i] != '\0'; i++) {
        if (p->text_used + 1u >= p->cfg.text_bytes) {
            return false;
        }
        p->cfg.text[p->text_used] = s[i];
        p->text_used++;
    }
    return true;
}

static const char *pool_end(lvprobe_t *p, const char *start)
{
    if (p->text_used >= p->cfg.text_bytes) {
        return NULL;
    }
    p->cfg.text[p->text_used] = '\0';
    p->text_used++;
    return start;
}

/* The label's own text: in DOTS mode LVGL overwrote LV_LABEL_DOT_NUM + 1 bytes at dot_begin and kept them in dot[]. */
static const char *full_text(lvprobe_t *p, const lv_label_t *label)
{
    const char *start = &p->cfg.text[p->text_used];
    size_t kept = 0;
    bool ok = pool_put(p, label->text, label->dot_begin);
    while (ok && kept < LV_LABEL_DOT_NUM + 1u && label->dot[kept] != '\0') {
        kept++;
    }
    ok = ok && pool_put(p, label->dot, kept);
    if (ok && kept == LV_LABEL_DOT_NUM + 1u) {
        ok = pool_put(p, &label->text[label->dot_begin + LV_LABEL_DOT_NUM + 1u], SIZE_MAX);
    }
    return ok ? pool_end(p, start) : NULL;
}

/* The flags lv_label lays its text out with (get_label_flags in lv_label.c). */
static lv_text_flag_t label_flags(const lv_label_t *label)
{
    const lv_obj_t *obj = &label->obj;
    lv_text_flag_t flag = LV_TEXT_FLAG_NONE;
    if (label->recolor) {
        flag |= LV_TEXT_FLAG_RECOLOR;
    }
    if (label->expand) {
        flag |= LV_TEXT_FLAG_EXPAND;
    }
    if (lv_obj_get_style_width(obj, LV_PART_MAIN) == LV_SIZE_CONTENT &&
        lv_obj_get_style_max_width(obj, LV_PART_MAIN) == LV_COORD_MAX && !obj->w_layout) {
        flag |= LV_TEXT_FLAG_FIT;
    }
    return flag;
}

static void sizes(lvprobe_node_t *n, const lv_label_t *label)
{
    lv_text_attributes_t a = {0};
    a.letter_space = lv_obj_get_style_text_letter_space(n->obj, LV_PART_MAIN);
    a.line_space = lv_obj_get_style_text_line_space(n->obj, LV_PART_MAIN);
    a.max_width = LV_COORD_MAX;
    a.text_flags = label->recolor ? LV_TEXT_FLAG_RECOLOR : LV_TEXT_FLAG_NONE;
    lv_text_get_size_attributes(&n->natural, n->full_text, n->font, &a);
    if (n->dotted) { /* the size of the shortened text, laid out as lv_label_refr_text lays a text out */
        a.max_width = lv_obj_get_content_width(n->obj);
        a.text_flags = label_flags(label);
        lv_text_get_size_attributes(&n->laid_out, n->text, n->font, &a);
    } else {
        n->laid_out = label->text_size;
    }
    n->lines = (n->laid_out.y > 0 && n->line_height + a.line_space > 0)
                   ? (n->laid_out.y + a.line_space) / (n->line_height + a.line_space)
                   : 0;
}

lvprobe_status_t lvp_label_facts(lvprobe_t *p, lvprobe_node_t *n)
{
    const lv_label_t *label = (const lv_label_t *)n->obj;
    const char *start = &p->cfg.text[p->text_used];
    uint16_t i;

    n->is_label = true;
    n->text = pool_put(p, label->text != NULL ? label->text : "", SIZE_MAX) ? pool_end(p, start) : NULL;
    n->dotted = label->dot_begin != LVP_DOT_BEGIN_INV && !label->static_txt && label->text != NULL;
    n->full_text = n->dotted ? full_text(p, label) : n->text;
    if (n->text == NULL || n->full_text == NULL) {
        return LVPROBE_ERR_FULL;
    }
    n->font = lv_obj_get_style_text_font(n->obj, LV_PART_MAIN);
    for (i = 0; i < p->font_count; i++) {
        n->font_id = p->fonts[i] == n->font ? p->font_ids[i] : n->font_id;
    }
    n->line_height = n->font != NULL ? lv_font_get_line_height(n->font) : 0;
    n->align = (uint8_t)lv_obj_get_style_text_align(n->obj, LV_PART_MAIN);
    n->long_mode = (uint8_t)label->long_mode;
    if (n->font != NULL) {
        sizes(n, label);
    }
    return LVPROBE_OK;
}

static void glyph_cb(lv_draw_task_t *t, lv_draw_glyph_dsc_t *dsc, lv_draw_fill_dsc_t *fill_dsc,
                     const lv_area_t *fill_area)
{
    lvprobe_t *p = t->target_layer != NULL ? t->target_layer->user_data : NULL;
    lvprobe_node_t *n;
    (void)fill_dsc;
    (void)fill_area;
    if (p == NULL || p->glyph_node == LVPROBE_NONE || dsc == NULL || dsc->letter_coords == NULL) {
        return;
    }
    n = &p->cfg.nodes[p->glyph_node];
    lvp_box_add(&n->glyphs, &n->has_glyphs, dsc->letter_coords);
    if (dsc->g != NULL && dsc->g->resolved_font == NULL && n->missing < UINT16_MAX) {
        n->missing++; /* LVGL draws a placeholder box: no font in the fallback chain has the glyph */
    }
}

/* A label draw task of the node: record its clip, then let LVGL's iterator place every glyph with the clip open. */
static void capture(lvprobe_t *p, uint16_t index, lv_draw_task_t *t)
{
    lvprobe_node_t *n = &p->cfg.nodes[index];
    lv_draw_label_dsc_t *dsc = lv_draw_task_get_label_dsc(t);
    if (dsc == NULL || dsc->base.obj != n->obj || dsc->base.part != LV_PART_MAIN) {
        return;
    }
    if (n->drawn) {
        bool has = true;
        lvp_box_add(&n->visible, &has, &t->clip_area);
    } else {
        n->visible = t->clip_area;
        n->drawn = true;
        n->align_drawn = (uint8_t)dsc->align;
    }
    t->clip_area.x1 = -LV_COORD_MAX;
    t->clip_area.y1 = -LV_COORD_MAX;
    t->clip_area.x2 = LV_COORD_MAX;
    t->clip_area.y2 = LV_COORD_MAX;
    p->glyph_node = index;
    lv_draw_label_iterate_characters(t, dsc, &t->area, glyph_cb);
    p->glyph_node = LVPROBE_NONE;
}

/* Every task LVGL put on the probe's layer is captured if it is the label's, then freed; none is ever drawn. */
static void drain(lvprobe_t *p, uint16_t index)
{
    lv_draw_task_t *t = p->layer.draw_task_head;
    uint32_t guard = 0;
    while (t != NULL && guard < LVP_VISIT_CAP) {
        lv_draw_task_t *next = t->next;
        if (t->type == LV_DRAW_TASK_TYPE_LABEL) {
            capture(p, index, t);
        }
        lv_draw_cleanup_task(t);
        t = next;
        guard++;
    }
    p->layer.draw_task_head = NULL;
}

/* The clip lv_obj_redraw gives the node's children chain: the display cut by every ancestor's child clip box. */
static bool chain_clip(const lvprobe_t *p, const lvprobe_node_t *n, lv_area_t *clip)
{
    int16_t at = n->parent;
    uint32_t steps = 0;
    lvp_display_area(p, clip);
    while (at != LVPROBE_NONE && steps < LVPROBE_MAX_DEPTH) {
        lv_area_t box;
        lvp_child_clip_box(&p->cfg.nodes[at], &box);
        if (!lvp_box_cut(clip, &box)) {
            return false;
        }
        at = p->cfg.nodes[at].parent;
        steps++;
    }
    return true;
}

/* Not drawn although nothing hides it: clipped when no clip leaves any of its content box (where text goes). */
static bool content_cut(const lvprobe_node_t *n, bool chain_open, const lv_area_t *clip)
{
    lv_area_t content;
    lv_area_t own = *clip;
    lv_area_t ext = n->coords;
    int32_t e = lv_obj_get_ext_draw_size(n->obj);
    if (!chain_open) {
        return true;
    }
    ext.x1 -= e;
    ext.y1 -= e;
    ext.x2 += e;
    ext.y2 += e;
    lv_obj_get_content_coords(n->obj, &content);
    return !lvp_box_cut(&own, &ext) || !lvp_box_cut(&own, &content);
}

/* LVGL renders a drop shadow or a layered descendant through a sub-layer it really dispatches: not measured. */
static bool needs_sub_layer(const lvprobe_node_t *n)
{
    lv_obj_t *obj = n->obj;
    int32_t depth = 0;
    uint32_t visits = 0;
    if (lv_obj_get_style_drop_shadow_opa(obj, LV_PART_MAIN) > LV_OPA_MIN) {
        return true;
    }
    obj = lvp_next(obj, n->obj, &depth);
    while (obj != NULL && visits < LVP_VISIT_CAP) {
        if (lv_obj_get_layer_type(obj) != LV_LAYER_TYPE_NONE || lv_obj_get_style_drop_shadow_opa(obj, LV_PART_MAIN) > LV_OPA_MIN) {
            return true;
        }
        visits++;
        obj = lvp_next(obj, n->obj, &depth);
    }
    return false;
}

/* The layer opacity lv_obj_refr hands the label: every ancestor's and its own `opa`, mixed below LV_OPA_MAX. */
static lv_opa_t layer_opa(const lvprobe_t *p, const lvprobe_node_t *n)
{
    lv_opa_t opa = LV_OPA_COVER;
    const lvprobe_node_t *cur = n;
    uint32_t steps = 0;
    while (steps <= LVPROBE_MAX_DEPTH) {
        lv_opa_t own = lv_obj_get_style_opa(cur->obj, LV_PART_MAIN);
        if (own < LV_OPA_MAX) {
            opa = LV_OPA_MIX2(opa, own);
        }
        if (cur->parent == LVPROBE_NONE) {
            break;
        }
        cur = &p->cfg.nodes[cur->parent];
        steps++;
    }
    return opa;
}

/* LVGL's `rendered` mark of the label and of every walked node below it (they follow it in walk order). */
static void save_rendered(lvprobe_t *p, uint16_t index, bool restore)
{
    uint16_t i = index;
    do {
        lvprobe_node_t *m = &p->cfg.nodes[i];
        if (restore && !m->was_rendered) {
            m->obj->rendered = 0;
        } else if (!restore) {
            m->was_rendered = m->obj->rendered != 0u;
        }
        i++;
    } while (i < p->count && p->cfg.nodes[i].depth > p->cfg.nodes[index].depth);
}

static void dry_draw(lvprobe_t *p, uint16_t index, const lv_area_t *clip)
{
    lvprobe_node_t *n = &p->cfg.nodes[index];
    uint32_t gen = p->gen;
    lv_layer_init(&p->layer);
    p->layer.user_data = p;
    p->layer.display = p->disp;
    p->layer.color_format = LV_COLOR_FORMAT_XRGB8888;
    p->layer.opa = layer_opa(p, n);
    lvp_display_area(p, &p->layer.buf_area);
    p->layer._clip_area = *clip;
    p->layer.phy_clip_area = *clip;
    save_rendered(p, index, false);
    lv_obj_redraw(&p->layer, n->obj);
    drain(p, index);
    if (p->gen == gen) { /* a draw handler that deleted objects makes the walk stale: touch nothing then */
        save_rendered(p, index, true); /* lv_obj_redraw marks them; the probe rendered nothing */
    }
}

lvprobe_status_t lvp_label_draw(lvprobe_t *p, uint16_t index)
{
    lvprobe_node_t *n = &p->cfg.nodes[index];
    lv_area_t clip;
    bool open;

    if (!lvp_draw_chain(p, n)) {
        return LVPROBE_OK; /* hidden or fully transparent: not drawn and not clipped */
    }
    if (needs_sub_layer(n)) {
        n->unsupported = true; /* not measured: drawn 0, no boxes, not clipped; the walk goes on */
        return LVPROBE_OK;
    }
    open = chain_clip(p, n, &clip);
    if (open) {
        dry_draw(p, index, &clip);
    }
    if (n->drawn) {
        n->clipped = n->has_glyphs && !lvp_box_in(&n->glyphs, &n->visible);
    } else {
        n->clipped = n->natural.x > 0 && layer_opa(p, n) > LV_OPA_MIN && content_cut(n, open, &clip);
    }
    return LVPROBE_OK;
}
