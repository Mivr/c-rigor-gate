/* Shared setup of the gate//ui/lvprobe tests (testkit.h). */
#include "ui/lvprobe/tests/testkit.h"

#include "lvgl_gate.h"

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(TK_W, TK_H)];
static lv_draw_buf_t g_draw_buf;
lvprobe_t tk_probe;
uint32_t tk_scratch[TK_W * TK_H];

static const uint8_t g_bitmap[] = {
    0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, /* A: 12 rows of 8 */
    0xF0u,                                                                             /* .: 2x2 = 4 bits */
    0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, /* Й */
    0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu,
    0xFFu, 0xFFu, 0xFFu, 0xFFu, /* Ё: 18 rows */
};
static const lv_font_fmt_txt_glyph_dsc_t g_glyphs[] = {
    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 0, .adv_w = 160, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0},  /* ' ' */
    {.bitmap_index = 12, .adv_w = 160, .box_w = 2, .box_h = 2, .ofs_x = 1, .ofs_y = 0}, /* '.' */
    {.bitmap_index = 0, .adv_w = 160, .box_w = 8, .box_h = 12, .ofs_x = 1, .ofs_y = 0}, /* 'A' */
    {.bitmap_index = 13, .adv_w = 160, .box_w = 8, .box_h = 18, .ofs_x = 1, .ofs_y = 0}, /* U+0401 */
    {.bitmap_index = 13, .adv_w = 160, .box_w = 8, .box_h = 14, .ofs_x = 1, .ofs_y = 0}, /* U+0419 */
};
#define TK_CMAP(start, id)                                                                                  \
    {.range_start = (start), .range_length = 1, .glyph_id_start = (id), .unicode_list = NULL,              \
     .glyph_id_ofs_list = NULL, .list_length = 0, .type = LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY}
static const lv_font_fmt_txt_cmap_t g_cmaps[] = {TK_CMAP(0x20, 1), TK_CMAP(0x2E, 2), TK_CMAP(0x41, 3),
                                                 TK_CMAP(0x401, 4), TK_CMAP(0x419, 5)};
static const lv_font_fmt_txt_dsc_t g_dsc = {
    .glyph_bitmap = g_bitmap, .glyph_dsc = g_glyphs, .cmaps = g_cmaps, .kern_dsc = NULL,
    .kern_scale = 0, .cmap_num = 5, .bpp = 1, .kern_classes = 0, .bitmap_format = 0,
};
const lv_font_t tk_mono = {
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt, .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = TK_LINE_H, .base_line = 2, .subpx = LV_FONT_SUBPX_NONE, .static_bitmap = 1, .dsc = &g_dsc,
};

lv_display_t *tk_start(ctest_t *t)
{
    lv_display_t *disp;
    bool flushed = false;
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    disp = lvgl_gate_test_display_create(TK_W, TK_H, g_frame, sizeof g_frame, &g_draw_buf);
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        lv_deinit();
        return NULL;
    }
    lv_obj_set_style_bg_color(lv_screen_active(), lv_color_hex(0xFFFFFFu), 0);
    if (lvprobe_open(&tk_probe, disp, NULL, tk_scratch, (size_t)TK_W * TK_H) != LVPROBE_OK) {
        CHECK(t, 0);
        lv_display_delete(disp);
        lv_deinit();
        return NULL;
    }
    (void)lvprobe_settle(&tk_probe, &flushed);
    return disp;
}

void tk_stop(lv_display_t *disp)
{
    lvprobe_close(&tk_probe);
    lv_display_delete(disp);
    lv_deinit();
}

bool tk_walk(ctest_t *t)
{
    bool flushed = true;
    int i;
    for (i = 0; i < 4 && flushed; i++) {
        CHECK_EQ_I64(t, lvprobe_settle(&tk_probe, &flushed), LVPROBE_OK);
    }
    CHECK(t, !flushed);
    return lvprobe_walk(&tk_probe) == LVPROBE_OK;
}

const lvprobe_node_t *tk_node(ctest_t *t, const lv_obj_t *obj)
{
    int32_t at = lvprobe_find(&tk_probe, obj);
    CHECK(t, at != LVPROBE_NONE);
    return at == LVPROBE_NONE ? NULL : lvprobe_node(&tk_probe, (uint16_t)at);
}

uint16_t tk_index(const lv_obj_t *obj)
{
    int32_t at = lvprobe_find(&tk_probe, obj);
    return at == LVPROBE_NONE ? 0xFFFFu : (uint16_t)at;
}

lv_obj_t *tk_label(lv_obj_t *parent, const char *text, int32_t x, int32_t y)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_pos(label, x, y);
    lv_obj_set_style_text_font(label, &tk_mono, 0);
    lv_obj_set_style_text_color(label, lv_color_hex(0x000000u), 0);
    return label;
}

lv_obj_t *tk_box(lv_obj_t *parent, int32_t x, int32_t y, int32_t w, int32_t h, uint32_t rgb)
{
    lv_obj_t *obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, w, h);
    lv_obj_set_style_bg_color(obj, lv_color_hex(rgb), 0);
    lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
    return obj;
}

uint32_t tk_pixel(int32_t x, int32_t y)
{
    return lvgl_gate_test_display_pixel(&g_draw_buf, x, y);
}

uint32_t tk_count_not(const lv_area_t *box, uint32_t rgb)
{
    uint32_t n = 0;
    int32_t x;
    int32_t y;
    for (y = box->y1; y <= box->y2; y++) {
        for (x = box->x1; x <= box->x2; x++) {
            n += tk_pixel(x, y) != rgb ? 1u : 0u;
        }
    }
    return n;
}

bool tk_contains(const char *hay, size_t len, const char *needle)
{
    size_t i;
    size_t j;
    for (i = 0; i < len; i++) {
        for (j = 0; needle[j] != '\0' && i + j < len && hay[i + j] == needle[j]; j++) {
        }
        if (needle[j] == '\0') {
            return true;
        }
    }
    return false;
}

bool tk_box_is(const lv_area_t *a, int32_t x1, int32_t y1, int32_t x2, int32_t y2)
{
    return a->x1 == x1 && a->y1 == y1 && a->x2 == x2 && a->y2 == y2;
}
