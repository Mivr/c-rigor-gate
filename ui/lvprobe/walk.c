/* gate//ui/lvprobe: the O3 tree walk (1) and the `clipped` verdict (2), from LVGL's own layout and draw tasks. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_draw_private.h"
#include "src/draw/lv_draw_label_private.h"
#include "src/draw/lv_draw_private.h"
#include "src/misc/lv_area_private.h"
#include "src/widgets/label/lv_label_private.h"

/* The node whose glyphs lvp_capture_task is collecting: the glyph callback of LVGL has no user data. */
static lvprobe_node_t *g_glyph_node;

static void glyph_cb(lv_draw_task_t *t, lv_draw_glyph_dsc_t *dsc, lv_draw_fill_dsc_t *fill_dsc,
                     const lv_area_t *fill_area)
{
    (void)t;
    (void)fill_dsc;
    (void)fill_area;
    if (g_glyph_node != NULL && dsc != NULL && dsc->letter_coords != NULL) {
        lvp_box_add(&g_glyph_node->glyphs, &g_glyph_node->has_glyphs, dsc->letter_coords);
    }
}

/* A label draw task LVGL just created: record the clip it will be drawn with, then let LVGL's own character
 * iterator place every glyph of it with the clip opened up, so glyphs the renderer cuts are seen too. */
void lvp_capture_task(lvprobe_t *p, lv_event_t *e)
{
    lv_draw_task_t *t = lv_event_get_draw_task(e);
    lv_draw_label_dsc_t *dsc;
    lv_area_t saved;
    int32_t at;
    lvprobe_node_t *n;

    if (t == NULL || lv_draw_task_get_type(t) != LV_DRAW_TASK_TYPE_LABEL) {
        return;
    }
    at = lvprobe_find(p, lv_event_get_current_target(e));
    dsc = lv_draw_task_get_label_dsc(t);
    if (at == LVPROBE_NONE || dsc == NULL || !p->nodes[at].is_label) {
        return;
    }
    n = &p->nodes[at];
    if (n->drawn) {
        bool has = true;
        lvp_box_add(&n->visible, &has, &t->clip_area);
    } else {
        n->visible = t->clip_area;
        n->drawn = true;
    }
    saved = t->clip_area;
    t->clip_area.x1 = -LV_COORD_MAX;
    t->clip_area.y1 = -LV_COORD_MAX;
    t->clip_area.x2 = LV_COORD_MAX;
    t->clip_area.y2 = LV_COORD_MAX;
    g_glyph_node = n;
    lv_draw_label_iterate_characters(t, dsc, &t->area, glyph_cb);
    g_glyph_node = NULL;
    t->clip_area = saved;
}

static uint16_t font_id(const lvprobe_t *p, const lv_font_t *font)
{
    uint16_t i;
    for (i = 0; i < p->font_count; i++) {
        if (p->fonts[i] == font) {
            return p->font_ids[i];
        }
    }
    return LVPROBE_FONT_UNMAPPED;
}

static lvprobe_status_t copy_text(lvprobe_t *p, lvprobe_node_t *n, const char *text)
{
    size_t i = 0;
    char *dst = &p->text[p->text_used];
    size_t room = LVPROBE_TEXT_BYTES - p->text_used;

    if (text == NULL) {
        text = "";
    }
    while (i < room && text[i] != '\0') {
        dst[i] = text[i];
        i++;
    }
    if (i >= room) {
        return LVPROBE_ERR_FULL;
    }
    dst[i] = '\0';
    n->text = dst;
    p->text_used += i + 1u;
    return LVPROBE_OK;
}

static lvprobe_status_t label_facts(lvprobe_t *p, lvprobe_node_t *n)
{
    lv_obj_t *obj = n->obj;
    const lv_label_t *label = (const lv_label_t *)obj;
    int32_t letter = lv_obj_get_style_text_letter_space(obj, LV_PART_MAIN);
    int32_t line = lv_obj_get_style_text_line_space(obj, LV_PART_MAIN);
    lvprobe_status_t st = copy_text(p, n, lv_label_get_text(obj));

    if (st != LVPROBE_OK) {
        return st;
    }
    n->is_label = true;
    n->font = lv_obj_get_style_text_font(obj, LV_PART_MAIN);
    n->font_id = font_id(p, n->font);
    n->line_height = n->font != NULL ? lv_font_get_line_height(n->font) : 0;
    n->align = (uint8_t)lv_obj_get_style_text_align(obj, LV_PART_MAIN);
    n->long_mode = (uint8_t)lv_label_get_long_mode(obj);
    if (n->font != NULL) {
        lv_text_get_size(&n->natural, n->text, n->font, letter, line, LV_COORD_MAX,
                         label->recolor ? LV_TEXT_FLAG_RECOLOR : LV_TEXT_FLAG_NONE);
    }
    n->laid_out = label->text_size;
    n->lines = (n->laid_out.y > 0 && n->line_height + line > 0) ? (n->laid_out.y + line) / (n->line_height + line) : 0;
    return LVPROBE_OK;
}

/* The box an object clips its children to: its coords, or coords + ext draw size when overflow is visible. */
static void child_clip_box(const lvprobe_node_t *n, lv_area_t *box)
{
    int32_t ext = lv_obj_is_overflow_visible(n->obj) ? lv_obj_get_ext_draw_size(n->obj) : 0;
    *box = n->coords;
    box->x1 -= ext;
    box->y1 -= ext;
    box->x2 += ext;
    box->y2 += ext;
}

static int16_t clip_ancestor(const lvprobe_t *p, const lvprobe_node_t *n)
{
    int16_t at = n->parent;
    uint32_t steps = 0;
    while (at != LVPROBE_NONE && steps < LVPROBE_MAX_DEPTH) {
        lv_area_t box;
        child_clip_box(&p->nodes[at], &box);
        if (!lvp_box_in(&n->coords, &box)) {
            return at;
        }
        at = p->nodes[at].parent;
        steps++;
    }
    return (int16_t)LVPROBE_NONE;
}

static lvprobe_status_t add_node(lvprobe_t *p, lv_obj_t *obj, int32_t depth)
{
    static const lvprobe_node_t zero;
    lvprobe_node_t *n;
    lv_color_t bg;

    if (p->count >= LVPROBE_MAX_NODES || depth < 0 || depth >= LVPROBE_MAX_DEPTH) {
        return LVPROBE_ERR_FULL;
    }
    n = &p->nodes[p->count];
    *n = zero;
    n->obj = obj;
    n->class_name = lvp_class_name(obj);
    n->depth = (uint8_t)depth;
    n->parent = depth == 0 ? (int16_t)LVPROBE_NONE : (int16_t)lvprobe_find(p, lv_obj_get_parent(obj));
    n->hidden = lv_obj_is_hidden(obj);
    n->clickable = lv_obj_is_clickable(obj);
    lv_obj_get_coords(obj, &n->coords);
    bg = lv_obj_get_style_bg_color(obj, LV_PART_MAIN);
    n->bg_rgb = ((uint32_t)bg.red << 16) | ((uint32_t)bg.green << 8) | (uint32_t)bg.blue;
    n->bg_opa = lv_obj_get_style_bg_opa(obj, LV_PART_MAIN);
    n->font_id = LVPROBE_FONT_UNMAPPED;
    p->count++;
    n->clip = clip_ancestor(p, n);
    return lv_obj_check_type(obj, &lv_label_class) ? label_facts(p, n) : LVPROBE_OK;
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

/* Redraw the whole screen once with label draw-task events on, so every label's real draw task is seen. */
static void capture(lvprobe_t *p)
{
    uint16_t i;
    for (i = 0; i < p->count; i++) {
        lv_obj_t *obj = p->nodes[i].obj;
        p->draw_events_before[i] = lv_obj_is_send_draw_task_events(obj) ? 1u : 0u;
        if (p->nodes[i].is_label) {
            lv_obj_set_send_draw_task_events(obj, true);
        }
    }
    lv_obj_invalidate(lv_display_get_screen_active(p->disp));
    p->capturing = true;
    lv_refr_now(p->disp);
    p->capturing = false;
    for (i = 0; i < p->count; i++) {
        if (p->nodes[i].obj != NULL) {
            lv_obj_set_send_draw_task_events(p->nodes[i].obj, p->draw_events_before[i] != 0u);
        }
    }
}

/* Hidden by itself or by an ancestor: LVGL draws nothing of it. */
static bool hidden_chain(const lvprobe_t *p, const lvprobe_node_t *n)
{
    const lvprobe_node_t *cur = n;
    uint32_t steps = 0;
    while (steps <= LVPROBE_MAX_DEPTH) {
        if (cur->hidden) {
            return true;
        }
        if (cur->parent == LVPROBE_NONE) {
            return false;
        }
        cur = &p->nodes[cur->parent];
        steps++;
    }
    return false;
}

/* Some part of the label's box survives every clipping ancestor. */
static bool box_reachable(const lvprobe_t *p, const lvprobe_node_t *n)
{
    lv_area_t box = n->coords;
    int16_t at = n->parent;
    uint32_t steps = 0;
    while (at != LVPROBE_NONE && steps < LVPROBE_MAX_DEPTH) {
        lv_area_t clip;
        child_clip_box(&p->nodes[at], &clip);
        if (!lv_area_intersect(&box, &box, &clip)) {
            return false;
        }
        at = p->nodes[at].parent;
        steps++;
    }
    return !lvp_box_empty(&box);
}

static void verdicts(lvprobe_t *p)
{
    uint16_t i;
    for (i = 0; i < p->count; i++) {
        lvprobe_node_t *n = &p->nodes[i];
        if (!n->is_label) {
            continue;
        }
        if (n->drawn) {
            n->clipped = n->has_glyphs && !lvp_box_in(&n->glyphs, &n->visible);
        } else {
            n->clipped = n->text[0] != '\0' && !hidden_chain(p, n) && !box_reachable(p, n);
        }
    }
}

lvprobe_status_t lvprobe_walk(lvprobe_t *p)
{
    lvprobe_status_t st;
    if (p == NULL || !p->open) {
        return LVPROBE_ERR_ARG;
    }
    p->count = 0;
    p->text_used = 0;
    p->has_frame = false;
    lv_refr_now(p->disp); /* settle pending layout and dirty areas first: the walk reads the frame LVGL shows */
    st = lvp_attach_all(p);
    if (st == LVPROBE_OK) {
        st = collect(p);
    }
    if (st != LVPROBE_OK) {
        p->count = 0;
        return st;
    }
    capture(p);
    verdicts(p);
    if (p->fault != LVPROBE_OK) {
        st = p->fault;
        p->fault = LVPROBE_OK;
    }
    return st;
}
