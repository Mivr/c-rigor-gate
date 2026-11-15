/* gate//ui/lvprobe through its public header: the tree walk, the `clipped` verdict, ink, the encoder (U02). */
#include <stddef.h>
#include <stdint.h>

#include "ctest/ctest.h"
#include "lvgl.h"
#include "lvgl_gate.h"
#include "ui/lvprobe/lvprobe.h"

enum { W = 320, H = 240, CYR_LINE_H = 16, ENC_BYTES = 65536 };

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(W, H)];
static lv_draw_buf_t g_draw_buf;
static uint32_t g_scratch[W * H];
static lvprobe_t g_probe;
static char g_enc[ENC_BYTES];

/* A one-glyph test font: U+0419 (Cyrillic Й, breve on top), 8 x 14 px at 1 bpp in a 16 px line, baseline 2 px above
 * the bottom of the line. The glyph box spans line rows 0..13 (14 rows). */
static const uint8_t g_cyr_bitmap[] = {0x24u, 0x18u, 0x00u, 0x81u, 0x81u, 0x83u, 0x85u,
                                       0x89u, 0x91u, 0xA1u, 0xC1u, 0x81u, 0x81u, 0x81u};
static const lv_font_fmt_txt_glyph_dsc_t g_cyr_glyphs[] = {
    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 0, .adv_w = 160, .box_w = 8, .box_h = 14, .ofs_x = 1, .ofs_y = 0},
};
static const lv_font_fmt_txt_cmap_t g_cyr_cmaps[] = {
    {.range_start = 0x419, .range_length = 1, .glyph_id_start = 1, .unicode_list = NULL, .glyph_id_ofs_list = NULL,
     .list_length = 0, .type = LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY},
};
static const lv_font_fmt_txt_dsc_t g_cyr_dsc = {
    .glyph_bitmap = g_cyr_bitmap, .glyph_dsc = g_cyr_glyphs, .cmaps = g_cyr_cmaps, .kern_dsc = NULL,
    .kern_scale = 0, .cmap_num = 1, .bpp = 1, .kern_classes = 0, .bitmap_format = 0,
};
static const lv_font_t g_cyr = {
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt, .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = CYR_LINE_H, .base_line = 2, .subpx = LV_FONT_SUBPX_NONE, .static_bitmap = 1, .dsc = &g_cyr_dsc,
};

static lv_display_t *start(ctest_t *t)
{
    lv_display_t *disp;
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    disp = lvgl_gate_test_display_create(W, H, g_frame, sizeof g_frame, &g_draw_buf);
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        lv_deinit();
        return NULL;
    }
    lv_obj_set_style_bg_color(lv_screen_active(), lv_color_hex(0xFFFFFFu), 0);
    if (lvprobe_open(&g_probe, disp, g_scratch, (size_t)W * H) != LVPROBE_OK) {
        CHECK(t, 0);
        lv_display_delete(disp);
        lv_deinit();
        return NULL;
    }
    return disp;
}

static void stop(lv_display_t *disp)
{
    lvprobe_close(&g_probe);
    lv_display_delete(disp);
    lv_deinit();
}

static lv_obj_t *label_at(lv_obj_t *parent, const char *text, int32_t x, int32_t y)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_pos(label, x, y);
    return label;
}

static const lvprobe_node_t *node_of(ctest_t *t, const lv_obj_t *obj)
{
    int32_t at = lvprobe_find(&g_probe, obj);
    CHECK(t, at != LVPROBE_NONE);
    return lvprobe_node(&g_probe, at == LVPROBE_NONE ? 0xFFFFu : (uint16_t)at);
}

static int contains(const char *hay, size_t len, const char *needle)
{
    size_t i;
    size_t j;
    for (i = 0; i < len; i++) {
        for (j = 0; needle[j] != '\0' && i + j < len && hay[i + j] == needle[j]; j++) {
        }
        if (needle[j] == '\0') {
            return 1;
        }
    }
    return 0;
}

static void t_a_label_in_a_box_too_small_is_clipped(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *tight;
    lv_obj_t *fits;
    const lvprobe_node_t *a;
    const lvprobe_node_t *b;
    if (disp == NULL) {
        return;
    }
    tight = label_at(lv_screen_active(), "Hello", 10, 10);
    lv_obj_set_size(tight, 80, 8);
    fits = label_at(lv_screen_active(), "Hello", 10, 40);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    a = node_of(t, tight);
    b = node_of(t, fits);
    if (a == NULL || b == NULL) {
        stop(disp);
        return;
    }
    CHECK(t, a->is_label && a->drawn && a->has_glyphs);
    CHECK(t, a->clipped);
    CHECK(t, a->glyphs.y2 > a->visible.y2);
    CHECK(t, b->is_label && b->drawn && b->has_glyphs);
    CHECK(t, !b->clipped);
    CHECK(t, b->glyphs.y1 >= b->visible.y1 && b->glyphs.y2 <= b->visible.y2);
    CHECK_EQ_I64(t, b->lines, 1);
    CHECK_EQ_I64(t, b->natural.x, b->laid_out.x);
    CHECK_EQ_I64(t, b->line_height, lv_font_get_line_height(LV_FONT_DEFAULT));
    CHECK_EQ_STR(t, b->text, "Hello");
    CHECK_EQ_STR(t, b->class_name, "lv_label");
    stop(disp);
}

static void t_a_label_cut_by_its_parent_is_clipped(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *box;
    lv_obj_t *label;
    const lvprobe_node_t *n;
    if (disp == NULL) {
        return;
    }
    box = lv_obj_create(lv_screen_active());
    lv_obj_remove_style_all(box);
    lv_obj_set_pos(box, 10, 10);
    lv_obj_set_size(box, 40, 40);
    label = label_at(box, "Hello", 20, 0);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    n = node_of(t, label);
    if (n == NULL) {
        stop(disp);
        return;
    }
    CHECK(t, n->drawn && n->has_glyphs);
    CHECK_EQ_I64(t, n->clip, lvprobe_find(&g_probe, box));
    CHECK_EQ_I64(t, n->parent, lvprobe_find(&g_probe, box));
    CHECK(t, n->visible.x2 <= 49);
    CHECK(t, n->glyphs.x2 > 49);
    CHECK(t, n->clipped);
    stop(disp);
}

static void t_a_cyrillic_glyph_in_a_tight_row_is_clipped(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *tight;
    lv_obj_t *row;
    const lvprobe_node_t *a;
    const lvprobe_node_t *b;
    if (disp == NULL) {
        return;
    }
    CHECK_EQ_I64(t, lvprobe_map_font(&g_probe, &g_cyr, 7), LVPROBE_OK);
    tight = label_at(lv_screen_active(), "\xD0\x99", 10, 10);
    lv_obj_set_style_text_font(tight, &g_cyr, 0);
    lv_obj_set_size(tight, 40, 10);
    row = label_at(lv_screen_active(), "\xD0\x99", 10, 60);
    lv_obj_set_style_text_font(row, &g_cyr, 0);
    lv_obj_set_size(row, 40, CYR_LINE_H);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    a = node_of(t, tight);
    b = node_of(t, row);
    if (a == NULL || b == NULL) {
        stop(disp);
        return;
    }
    CHECK_EQ_U64(t, a->font_id, 7);
    CHECK_EQ_I64(t, a->line_height, CYR_LINE_H);
    CHECK(t, a->has_glyphs && b->has_glyphs);
    CHECK_EQ_I64(t, a->glyphs.y2 - a->glyphs.y1 + 1, 14);
    CHECK_EQ_I64(t, a->glyphs.x2 - a->glyphs.x1 + 1, 8);
    CHECK(t, a->clipped);
    CHECK(t, !b->clipped);
    CHECK_EQ_I64(t, b->glyphs.y1, 60);
    CHECK_EQ_I64(t, b->lines, 1);
    stop(disp);
}

static void t_a_hidden_label_has_no_ink(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *shown;
    lv_obj_t *hidden;
    const lvprobe_node_t *a;
    const lvprobe_node_t *b;
    uint32_t crc;
    if (disp == NULL) {
        return;
    }
    shown = label_at(lv_screen_active(), "Hello", 10, 10);
    hidden = label_at(lv_screen_active(), "Hello", 10, 40);
    lv_obj_set_hidden(hidden, true);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_frame(&g_probe), LVPROBE_OK);
    crc = lvprobe_frame_crc(&g_probe);
    CHECK_EQ_I64(t, lvprobe_ink(&g_probe, (uint16_t)lvprobe_find(&g_probe, shown)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&g_probe, (uint16_t)lvprobe_find(&g_probe, hidden)), LVPROBE_OK);
    a = node_of(t, shown);
    b = node_of(t, hidden);
    if (a == NULL || b == NULL) {
        stop(disp);
        return;
    }
    CHECK(t, a->has_ink && a->ink > 20u);
    CHECK(t, a->ink_box.x1 >= a->coords.x1 && a->ink_box.x2 <= a->coords.x2);
    CHECK(t, a->ink_box.y1 >= a->coords.y1 && a->ink_box.y2 <= a->coords.y2);
    CHECK(t, a->ink_lo != a->bg_hi);
    CHECK_EQ_U64(t, a->bg_hi, 0xFFFFFFu);
    CHECK(t, b->hidden && b->has_ink);
    CHECK_EQ_U64(t, b->ink, 0);
    CHECK(t, !b->clipped && !b->drawn);
    CHECK(t, lv_obj_is_hidden(hidden) && !lv_obj_is_hidden(shown));
    CHECK_EQ_I64(t, lvprobe_frame(&g_probe), LVPROBE_OK);
    CHECK_EQ_U64(t, lvprobe_frame_crc(&g_probe), crc);
    stop(disp);
}

static void t_encoder_truncation_is_an_error(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *label;
    size_t len = 0;
    size_t again = 0;
    if (disp == NULL) {
        return;
    }
    label = label_at(lv_screen_active(), "Say \"hi\"", 10, 10);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_frame(&g_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&g_probe, (uint16_t)lvprobe_find(&g_probe, label)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_encode(&g_probe, g_enc, sizeof g_enc, &len), LVPROBE_OK);
    CHECK(t, len > 100u && len < sizeof g_enc);
    CHECK(t, contains(g_enc, len, "lvprobe/1 nodes="));
    CHECK(t, contains(g_enc, len, "frame w=320 h=240 crc="));
    CHECK(t, contains(g_enc, len, " text=\"Say \\\"hi\\\"\"\n"));
    CHECK(t, contains(g_enc, len, "\nink "));
    CHECK(t, contains(g_enc, len, "\nregion "));
    CHECK_EQ_U64(t, (unsigned char)g_enc[len], 0);
    CHECK_EQ_I64(t, lvprobe_encode(&g_probe, g_enc, len, &again), LVPROBE_ERR_TRUNC);
    CHECK_EQ_U64(t, again, 0);
    CHECK_EQ_U64(t, (unsigned char)g_enc[0], 0);
    CHECK_EQ_I64(t, lvprobe_encode(&g_probe, g_enc, 10, &again), LVPROBE_ERR_TRUNC);
    CHECK_EQ_I64(t, lvprobe_encode(&g_probe, g_enc, len + 1u, &again), LVPROBE_OK);
    CHECK_EQ_U64(t, again, len);
    stop(disp);
}

CTEST_SUITE("lvprobe_tree", { "a_label_in_a_box_too_small_is_clipped", t_a_label_in_a_box_too_small_is_clipped },
            { "a_label_cut_by_its_parent_is_clipped", t_a_label_cut_by_its_parent_is_clipped },
            { "a_cyrillic_glyph_in_a_tight_row_is_clipped", t_a_cyrillic_glyph_in_a_tight_row_is_clipped },
            { "a_hidden_label_has_no_ink", t_a_hidden_label_has_no_ink },
            { "encoder_truncation_is_an_error", t_encoder_truncation_is_an_error })
