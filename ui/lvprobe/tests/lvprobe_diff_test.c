/* gate//ui/lvprobe differential tests (U02): every fact the probe derives from LVGL's draw code, and every piece of
 * LVGL logic it mirrors, checked against what LVGL really rendered. The test font's glyphs are solid boxes, so the
 * rendered ink box of a black label on white is exactly the part of its glyph boxes LVGL let through. */
#include "ui/lvprobe/tests/testkit.h"

#include "src/display/lv_display_private.h"

static bool box_cut(lv_area_t *a, const lv_area_t *b)
{
    a->x1 = a->x1 > b->x1 ? a->x1 : b->x1;
    a->y1 = a->y1 > b->y1 ? a->y1 : b->y1;
    a->x2 = a->x2 < b->x2 ? a->x2 : b->x2;
    a->y2 = a->y2 < b->y2 ? a->y2 : b->y2;
    return a->x1 <= a->x2 && a->y1 <= a->y2;
}

/* The rendered ink box equals glyphs cut by the visible box and the display (the dry redraw against the render). */
static void expect_ink_is_glyphs(ctest_t *t, const lv_obj_t *label, int line)
{
    const lv_area_t screen = {0, 0, TK_W - 1, TK_H - 1};
    const lvprobe_node_t *n = tk_node(t, label);
    lv_area_t want;
    if (n == NULL) {
        return;
    }
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(label)), LVPROBE_OK);
    CHECK(t, n->drawn && n->has_glyphs && n->has_ink && n->ink > 0u);
    want = n->glyphs;
    CHECK(t, box_cut(&want, &n->visible) && box_cut(&want, &screen));
    if (!tk_box_is(&n->ink_box, want.x1, want.y1, want.x2, want.y2)) {
        CHECK_EQ_I64(t, line, n->ink_box.x1 * 1000000 + n->ink_box.y1 * 1000 + n->ink_box.x2);
        CHECK_EQ_I64(t, line, want.x1 * 1000000 + want.y1 * 1000 + want.x2);
    }
}

/* Widths put every clip edge inside a glyph (the union of the glyph boxes is a bounding box, the ink is per glyph). */
static lv_obj_t *moded(const char *text, lv_label_long_mode_t mode, int32_t y)
{
    lv_obj_t *label = tk_label(lv_screen_active(), text, 10, y);
    bool cut = mode == LV_LABEL_LONG_MODE_SCROLL || mode == LV_LABEL_LONG_MODE_SCROLL_CIRCULAR ||
               mode == LV_LABEL_LONG_MODE_CLIP;
    lv_label_set_long_mode(label, mode);
    lv_obj_set_size(label, cut ? 55 : 50, mode == LV_LABEL_LONG_MODE_WRAP ? 20 : TK_LINE_H);
    return label;
}

static void t_glyphs_match_the_render_in_every_long_mode(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *wrap = moded("AAAA AAAA", LV_LABEL_LONG_MODE_WRAP, 10);
    lv_obj_t *dots = moded("AAAAAAAAAA", LV_LABEL_LONG_MODE_DOTS, 50);
    lv_obj_t *scroll = moded("AAAAAAAAAA", LV_LABEL_LONG_MODE_SCROLL, 80);
    lv_obj_t *circular = moded("AAAAAAAAAA", LV_LABEL_LONG_MODE_SCROLL_CIRCULAR, 110);
    lv_obj_t *clip = moded("AAAAAAAAAA", LV_LABEL_LONG_MODE_CLIP, 140);
    const lvprobe_node_t *n;
    if (disp == NULL) {
        return;
    }
    CHECK(t, tk_walk(t));
    lv_anim_delete_all(); /* freeze the scrolling labels: ink is refused while an animation runs */
    expect_ink_is_glyphs(t, wrap, __LINE__);
    expect_ink_is_glyphs(t, dots, __LINE__);
    expect_ink_is_glyphs(t, scroll, __LINE__);
    expect_ink_is_glyphs(t, circular, __LINE__);
    expect_ink_is_glyphs(t, clip, __LINE__);
    n = tk_node(t, wrap); /* line count formula against the rendered rows: (lines - 1) x 16 + 12 */
    CHECK(t, n != NULL && n->lines == 2 && n->glyphs.y2 - n->glyphs.y1 + 1 == (n->lines - 1) * TK_LINE_H + 12);
    n = tk_node(t, dots); /* DOTS laid-out width against the rendered "AA...": last dot ends 8 px before it */
    CHECK(t, n != NULL && n->dotted && n->ink_box.x2 - n->coords.x1 + 8 == n->laid_out.x);
    tk_stop(t, disp);
}

static void t_glyphs_match_the_render_under_parents(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *scroller = tk_box(lv_screen_active(), 10, 10, 60, 24, 0xFFFFFFu);
    lv_obj_t *in_scroller = tk_label(scroller, "AAAA AAAA", 0, 0);
    lv_obj_t *layered = tk_box(lv_screen_active(), 10, 60, 80, 20, 0xFFFFFFu);
    lv_obj_t *in_layered = tk_label(layered, "AAA", 5, 2);
    lv_obj_t *round = tk_box(lv_screen_active(), 10, 100, 80, 40, 0xFFFFFFu);
    lv_obj_t *in_round = tk_label(round, "AAA", 20, 12);
    lv_obj_t *off = tk_label(lv_screen_active(), "AAA", -5, 200);
    lv_obj_set_width(in_scroller, 50);
    lv_obj_scroll_to_y(scroller, 10, LV_ANIM_OFF);
    lv_obj_set_style_opa_layered(layered, 128, 0);
    lv_obj_set_style_radius(round, 10, 0);
    lv_obj_set_style_clip_corner(round, true, 0);
    if (disp == NULL) {
        return;
    }
    CHECK(t, tk_walk(t));
    expect_ink_is_glyphs(t, in_scroller, __LINE__);
    expect_ink_is_glyphs(t, in_layered, __LINE__);
    expect_ink_is_glyphs(t, in_round, __LINE__);
    expect_ink_is_glyphs(t, off, __LINE__);
    tk_stop(t, disp);
}

/* The mirrored draw chain and content rule, against pixels: where the probe says LVGL draws nothing, nothing shows. */
static void t_not_drawn_means_no_pixels(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *veil = tk_box(lv_screen_active(), 10, 10, 60, 20, 0xFFFFFFu);
    lv_obj_t *under_veil = tk_label(veil, "AA", 0, 0);
    lv_obj_t *faint_parent = tk_box(lv_screen_active(), 10, 40, 60, 20, 0xFFFFFFu);
    lv_obj_t *under_faint = tk_label(faint_parent, "AA", 0, 0);
    lv_obj_t *own_faint = tk_label(lv_screen_active(), "AA", 10, 70);
    lv_obj_t *row = tk_box(lv_screen_active(), 10, 100, 100, 15, 0xFFFFFFu);
    lv_obj_t *padded = tk_label(row, "AA", 0, 0);
    const lvprobe_node_t *n;
    lv_obj_set_style_opa_layered(veil, LV_OPA_TRANSP, 0);
    lv_obj_set_style_opa(faint_parent, 1, 0);
    lv_obj_set_style_opa(own_faint, 1, 0);
    lv_obj_set_style_pad_top(padded, 20, 0);
    if (disp == NULL) {
        return;
    }
    CHECK(t, tk_walk(t));
    n = tk_node(t, under_veil);
    CHECK(t, n != NULL && !n->drawn && !n->clipped && tk_count_not(&n->coords, 0xFFFFFFu) == 0u);
    n = tk_node(t, under_faint);
    CHECK(t, n != NULL && !n->drawn && !n->clipped && tk_count_not(&n->coords, 0xFFFFFFu) == 0u);
    n = tk_node(t, own_faint);
    CHECK(t, n != NULL && !n->drawn && !n->clipped && tk_count_not(&n->coords, 0xFFFFFFu) == 0u);
    n = tk_node(t, padded);
    CHECK(t, n != NULL && !n->drawn && n->clipped && tk_count_not(&n->coords, 0xFFFFFFu) == 0u);
    tk_stop(t, disp);
}

/* bg_opa_drawn against the rendered pixel: black at that opacity over white. */
static void t_bg_opa_drawn_matches_the_pixel(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *faded = tk_box(lv_screen_active(), 10, 10, 20, 20, 0x000000u);
    lv_obj_t *layered = tk_box(lv_screen_active(), 40, 10, 20, 20, 0xFFFFFFu);
    lv_obj_t *inner = tk_box(layered, 0, 0, 20, 20, 0x000000u);
    const lvprobe_node_t *n;
    uint32_t want;
    lv_obj_set_style_opa(faded, 128, 0);
    lv_obj_set_style_opa_layered(layered, 128, 0);
    lv_obj_set_style_bg_opa(inner, 128, 0);
    if (disp == NULL) {
        return;
    }
    CHECK(t, tk_walk(t));
    n = tk_node(t, faded);
    if (n != NULL) {
        want = 0xFFu - n->bg_opa_drawn;
        CHECK(t, n->bg_opa_exact);
        CHECK_EQ_U64(t, tk_pixel(15, 15) & 0xFFu, want);
    }
    n = tk_node(t, inner); /* under an opa_layered parent LVGL composes a sub-layer: not exact, and says so */
    CHECK(t, n != NULL && !n->bg_opa_exact);
    tk_stop(t, disp);
}

/* A walk changes nothing: pool bytes, the display's layer list and the frame are as before. */
static void t_a_walk_leaves_lvgl_as_it_was(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    size_t pool;
    uint32_t layers;
    uint32_t crc;
    (void)moded("AAAA AAAA", LV_LABEL_LONG_MODE_WRAP, 10);
    (void)moded("AAAAAAAAAA", LV_LABEL_LONG_MODE_DOTS, 50);
    (void)moded("AAAAAAAAAA", LV_LABEL_LONG_MODE_SCROLL_CIRCULAR, 80);
    if (disp == NULL) {
        return;
    }
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    crc = lvprobe_frame_crc(&tk_probe);
    pool = tk_pool_used();
    layers = tk_layer_count(disp);
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_OK);
    CHECK_EQ_U64(t, tk_pool_used(), pool);
    CHECK_EQ_U64(t, tk_layer_count(disp), layers);
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_U64(t, lvprobe_frame_crc(&tk_probe), crc);
    tk_stop(t, disp);
}

/* A real anti-aliased built-in font: ink never leaves the glyph boxes LVGL placed, and it is not empty. */
static void t_an_antialiased_font_inks_inside_its_glyphs(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *label = tk_ok(lv_label_create(lv_screen_active()));
    const lvprobe_node_t *n;
    lv_label_set_text(label, "Hello 42");
    lv_obj_set_pos(label, 20, 20);
    lv_obj_set_style_text_color(label, lv_color_hex(0x000000u), 0);
    if (disp == NULL) {
        return;
    }
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(label)), LVPROBE_OK);
    n = tk_node(t, label);
    if (n != NULL) {
        CHECK(t, n->drawn && n->has_glyphs && n->ink > 0u && !n->clipped);
        CHECK(t, n->ink_box.x1 >= n->glyphs.x1 && n->ink_box.y1 >= n->glyphs.y1);
        CHECK(t, n->ink_box.x2 <= n->glyphs.x2 && n->ink_box.y2 <= n->glyphs.y2);
        CHECK_EQ_U64(t, n->ink, tk_count_not(&n->coords, 0xFFFFFFu));
    }
    tk_stop(t, disp);
}

CTEST_SUITE("lvprobe_diff",
            { "glyphs_match_the_render_in_every_long_mode", t_glyphs_match_the_render_in_every_long_mode },
            { "glyphs_match_the_render_under_parents", t_glyphs_match_the_render_under_parents },
            { "not_drawn_means_no_pixels", t_not_drawn_means_no_pixels },
            { "bg_opa_drawn_matches_the_pixel", t_bg_opa_drawn_matches_the_pixel },
            { "a_walk_leaves_lvgl_as_it_was", t_a_walk_leaves_lvgl_as_it_was },
            { "an_antialiased_font_inks_inside_its_glyphs", t_an_antialiased_font_inks_inside_its_glyphs })
