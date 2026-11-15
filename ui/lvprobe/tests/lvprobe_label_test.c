/* gate//ui/lvprobe through its public header: label facts and the `clipped` verdict (U02). Every label uses the
 * monospace test font (testkit.h): 'A' is a solid 8x12 box at line rows 2..13, one pixel right of a 10 px advance. */
#include "ui/lvprobe/tests/testkit.h"

static void t_a_label_in_a_box_too_small_is_clipped(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *tight;
    lv_obj_t *fits;
    const lvprobe_node_t *a;
    const lvprobe_node_t *b;
    if (disp == NULL) {
        return;
    }
    tight = tk_label(lv_screen_active(), "AA", 10, 10);
    lv_obj_set_size(tight, 80, 8);
    fits = tk_label(lv_screen_active(), "AA", 10, 40);
    CHECK(t, tk_walk(t));
    a = tk_node(t, tight);
    b = tk_node(t, fits);
    if (a != NULL && b != NULL) {
        CHECK(t, a->drawn && a->has_glyphs && a->clipped);
        CHECK(t, tk_box_is(&a->glyphs, 11, 12, 28, 23));
        CHECK(t, tk_box_is(&a->visible, 6, 6, 93, 17));
        CHECK(t, b->drawn && b->has_glyphs && !b->clipped);
        CHECK(t, tk_box_is(&b->glyphs, 11, 42, 28, 53));
        CHECK(t, tk_box_is(&b->visible, 6, 36, 33, 55));
        CHECK(t, tk_box_is(&b->coords, 10, 40, 29, 55));
        CHECK_EQ_I64(t, b->lines, 1);
        CHECK_EQ_I64(t, b->natural.x, 20);
        CHECK_EQ_I64(t, b->natural.y, TK_LINE_H);
        CHECK_EQ_I64(t, b->laid_out.x, 20);
        CHECK_EQ_I64(t, b->laid_out.y, TK_LINE_H);
        CHECK_EQ_I64(t, b->line_height, TK_LINE_H);
        CHECK_EQ_STR(t, b->text, "AA");
        CHECK_EQ_STR(t, b->class_name, "lv_label");
        CHECK_EQ_U64(t, b->missing, 0);
    }
    tk_stop(disp);
}

static void t_a_label_cut_by_its_parent_is_clipped(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box;
    lv_obj_t *label;
    const lvprobe_node_t *n;
    if (disp == NULL) {
        return;
    }
    box = tk_box(lv_screen_active(), 10, 10, 40, 40, 0xFFFFFFu);
    label = tk_label(box, "AAAA", 20, 0);
    CHECK(t, tk_walk(t));
    n = tk_node(t, label);
    if (n != NULL) {
        CHECK_EQ_I64(t, n->clip, tk_index(box));
        CHECK_EQ_I64(t, n->parent, tk_index(box));
        CHECK(t, tk_box_is(&n->visible, 26, 10, 49, 25));
        CHECK(t, tk_box_is(&n->glyphs, 31, 12, 68, 23));
        CHECK(t, n->clipped);
    }
    tk_stop(disp);
}

/* Й in a row (a clipping parent) lower than the line is cut by the row; in a row of the line height it fits. Ё rises
 * 4 px above the line, so even a row of the line height cuts it. */
static void t_a_cyrillic_glyph_in_a_tight_row_is_clipped(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *tight_row = tk_box(lv_screen_active(), 10, 10, 60, 10, 0xFFFFFFu);
    lv_obj_t *row = tk_box(lv_screen_active(), 10, 40, 60, TK_LINE_H, 0xFFFFFFu);
    lv_obj_t *high_row = tk_box(lv_screen_active(), 10, 80, 60, TK_LINE_H, 0xFFFFFFu);
    lv_obj_t *a = tk_label(tight_row, "\xD0\x99", 0, 0);
    lv_obj_t *b = tk_label(row, "\xD0\x99", 0, 0);
    lv_obj_t *c = tk_label(high_row, "\xD0\x81", 0, 0);
    const lvprobe_node_t *na;
    const lvprobe_node_t *nb;
    const lvprobe_node_t *nc;
    CHECK_EQ_I64(t, lvprobe_map_font(&tk_probe, &tk_mono, 7), LVPROBE_OK);
    CHECK(t, tk_walk(t));
    na = tk_node(t, a);
    nb = tk_node(t, b);
    nc = tk_node(t, c);
    if (na != NULL && nb != NULL && nc != NULL) {
        CHECK_EQ_U64(t, na->font_id, 7);
        CHECK_EQ_I64(t, na->clip, tk_index(tight_row));
        CHECK(t, tk_box_is(&na->glyphs, 11, 10, 18, 23));
        CHECK(t, tk_box_is(&na->visible, 10, 10, 23, 19));
        CHECK(t, na->clipped);
        CHECK_EQ_I64(t, nb->clip, LVPROBE_NONE);
        CHECK(t, tk_box_is(&nb->glyphs, 11, 40, 18, 53));
        CHECK(t, !nb->clipped);
        CHECK(t, tk_box_is(&nc->glyphs, 11, 76, 18, 93));
        CHECK(t, tk_box_is(&nc->visible, 10, 80, 23, 95));
        CHECK(t, nc->clipped);
    }
    tk_stop(disp);
    (void)disp;
}

static void t_long_modes_dots_scroll_and_clip(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *dots = tk_label(lv_screen_active(), "AAAAAAAAAA", 10, 10);
    lv_obj_t *scroll = tk_label(lv_screen_active(), "AAAAAAAAAA", 10, 40);
    lv_obj_t *clip = tk_label(lv_screen_active(), "AAAAAAAAAA", 10, 70);
    const lvprobe_node_t *d;
    const lvprobe_node_t *s;
    const lvprobe_node_t *c;
    lv_label_set_long_mode(dots, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_size(dots, 50, TK_LINE_H);
    lv_label_set_long_mode(scroll, LV_LABEL_LONG_MODE_SCROLL);
    lv_obj_set_size(scroll, 50, TK_LINE_H);
    lv_label_set_long_mode(clip, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_size(clip, 50, TK_LINE_H);
    CHECK(t, tk_walk(t));
    d = tk_node(t, dots);
    s = tk_node(t, scroll);
    c = tk_node(t, clip);
    if (d != NULL && s != NULL && c != NULL) {
        CHECK(t, d->dotted);
        CHECK_EQ_STR(t, d->text, "AA...");
        CHECK_EQ_STR(t, d->full_text, "AAAAAAAAAA");
        CHECK_EQ_I64(t, d->natural.x, 100);
        CHECK_EQ_I64(t, d->laid_out.x, 50);
        CHECK_EQ_I64(t, d->laid_out.y, TK_LINE_H);
        CHECK_EQ_I64(t, d->lines, 1);
        CHECK(t, tk_box_is(&d->glyphs, 11, 12, 52, 23));
        CHECK(t, !d->clipped);
        CHECK(t, !s->dotted && s->long_mode == LV_LABEL_LONG_MODE_SCROLL);
        CHECK_EQ_I64(t, s->laid_out.x, 100);
        CHECK_EQ_I64(t, s->lines, 1);
        CHECK(t, tk_box_is(&s->glyphs, 11, 42, 108, 53));
        CHECK(t, tk_box_is(&s->visible, 10, 40, 59, 55));
        CHECK(t, s->clipped);
        CHECK_EQ_I64(t, c->lines, 1);
        CHECK(t, tk_box_is(&c->glyphs, 11, 72, 108, 83));
        CHECK(t, tk_box_is(&c->visible, 10, 70, 59, 85));
        CHECK(t, c->clipped);
    }
    tk_stop(disp);
}

static void t_a_wrapped_label_has_two_lines(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *label = tk_label(lv_screen_active(), "AAAA AAAA", 10, 10);
    const lvprobe_node_t *n;
    lv_obj_set_width(label, 50);
    CHECK(t, tk_walk(t));
    n = tk_node(t, label);
    if (n != NULL) {
        CHECK_EQ_I64(t, n->lines, 2);
        CHECK_EQ_I64(t, n->laid_out.x, 40);
        CHECK_EQ_I64(t, n->laid_out.y, 2 * TK_LINE_H);
        CHECK_EQ_I64(t, n->natural.x, 90);
        CHECK_EQ_I64(t, n->natural.y, TK_LINE_H);
        CHECK(t, tk_box_is(&n->coords, 10, 10, 59, 41));
        CHECK(t, tk_box_is(&n->glyphs, 11, 12, 48, 39));
        CHECK(t, !n->clipped);
    }
    tk_stop(disp);
}

static void t_recolor_empty_spaces_missing_and_align(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *recolor = tk_label(lv_screen_active(), "#ff0000 AA#", 10, 10);
    lv_obj_t *empty = tk_label(lv_screen_active(), "", 10, 40);
    lv_obj_t *spaces = tk_label(lv_screen_active(), "   ", 10, 70);
    lv_obj_t *missing = tk_label(lv_screen_active(), "AB", 10, 100);
    lv_obj_t *centred = tk_label(lv_screen_active(), "AA", 10, 130);
    const lvprobe_node_t *n;
    lv_label_set_recolor(recolor, true);
    lv_obj_set_width(centred, 60);
    lv_obj_set_style_text_align(centred, LV_TEXT_ALIGN_CENTER, 0);
    CHECK(t, tk_walk(t));
    n = tk_node(t, recolor);
    if (n != NULL) {
        CHECK_EQ_I64(t, n->natural.x, 20);
        CHECK(t, tk_box_is(&n->glyphs, 11, 12, 28, 23));
        CHECK_EQ_I64(t, n->align, LV_TEXT_ALIGN_AUTO);
        CHECK_EQ_I64(t, n->align_drawn, LV_TEXT_ALIGN_LEFT);
    }
    n = tk_node(t, empty);
    CHECK(t, n != NULL && !n->has_glyphs && !n->clipped && n->text[0] == '\0');
    n = tk_node(t, spaces);
    CHECK(t, n != NULL && !n->drawn && !n->has_glyphs && !n->clipped && n->natural.x == 0);
    CHECK(t, n != NULL && tk_box_is(&n->coords, 10, 70, 9, 85));
    n = tk_node(t, missing);
    CHECK(t, n != NULL && n->missing == 1u && n->has_glyphs);
    n = tk_node(t, centred);
    if (n != NULL) {
        CHECK_EQ_I64(t, n->align_drawn, LV_TEXT_ALIGN_CENTER);
        CHECK(t, tk_box_is(&n->glyphs, 31, 132, 48, 143));
    }
    tk_stop(disp);
}

/* drawn = 0: content box cut while the padding shows (clipped), wholly outside (clipped), text opacity 0 and hidden
 * (not clipped). */
static void t_labels_lvgl_does_not_draw(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *row = tk_box(lv_screen_active(), 10, 10, 100, 15, 0xFFFFFFu);
    lv_obj_t *padded = tk_label(row, "AA", 0, 0);
    lv_obj_t *outside = tk_label(lv_screen_active(), "AA", 400, 10);
    lv_obj_t *faint = tk_label(lv_screen_active(), "AA", 10, 100);
    lv_obj_t *hidden = tk_label(lv_screen_active(), "AA", 10, 130);
    const lvprobe_node_t *n;
    lv_obj_set_style_pad_top(padded, 20, 0);
    lv_obj_set_style_text_opa(faint, LV_OPA_TRANSP, 0);
    lv_obj_set_hidden(hidden, true);
    CHECK(t, tk_walk(t));
    n = tk_node(t, padded);
    CHECK(t, n != NULL && !n->drawn && n->clipped && tk_box_is(&n->coords, 10, 10, 29, 45));
    n = tk_node(t, outside);
    CHECK(t, n != NULL && !n->drawn && n->clipped);
    n = tk_node(t, faint);
    CHECK(t, n != NULL && !n->drawn && !n->clipped);
    n = tk_node(t, hidden);
    CHECK(t, n != NULL && !n->drawn && !n->clipped && n->hidden);
    tk_stop(disp);
}

CTEST_SUITE("lvprobe_label", { "a_label_in_a_box_too_small_is_clipped", t_a_label_in_a_box_too_small_is_clipped },
            { "a_label_cut_by_its_parent_is_clipped", t_a_label_cut_by_its_parent_is_clipped },
            { "a_cyrillic_glyph_in_a_tight_row_is_clipped", t_a_cyrillic_glyph_in_a_tight_row_is_clipped },
            { "long_modes_dots_scroll_and_clip", t_long_modes_dots_scroll_and_clip },
            { "a_wrapped_label_has_two_lines", t_a_wrapped_label_has_two_lines },
            { "recolor_empty_spaces_missing_and_align", t_recolor_empty_spaces_missing_and_align },
            { "labels_lvgl_does_not_draw", t_labels_lvgl_does_not_draw })
