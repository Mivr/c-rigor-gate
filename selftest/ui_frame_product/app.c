#include "selftest/ui_frame_product/app.h"

#include <stddef.h>

#include "lvgl_gate.h"

enum { EVENTS = 16, WORK = 8 };

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(APP_BIG_W, APP_BIG_H)];   /* the small display uses its start */
static lv_draw_buf_t g_draw_buf;
static lv_display_t *g_disp;
static lv_indev_t *g_indev;
static lv_obj_t *g_objs[APP_NODES];      /* title, button, notice, fit */
static lv_obj_t *g_button_label;
static lv_obj_t *g_bar;
static lv_obj_t *g_overlay;
static lv_obj_t *g_added;
static lv_point_t g_touch;
static bool g_touch_down;
static app_event_t g_events[EVENTS];
static unsigned g_event_count;
static app_work_t g_work[WORK];
static unsigned g_work_count;

/* One glyph, U+0419 (Й), as a solid 8x14 box: a font that has the Cyrillic glyph it shows. */
static const uint8_t g_bitmap[14] = {0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu,
                                     0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu};
static const lv_font_fmt_txt_glyph_dsc_t g_glyphs[] = {
    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 0, .adv_w = 160, .box_w = 8, .box_h = 14, .ofs_x = 1, .ofs_y = 0},
};
static const lv_font_fmt_txt_cmap_t g_cmaps[] = {
    {.range_start = 0x419, .range_length = 1, .glyph_id_start = 1, .unicode_list = NULL, .glyph_id_ofs_list = NULL,
     .list_length = 0, .type = LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY},
};
static const lv_font_fmt_txt_dsc_t g_dsc = {
    .glyph_bitmap = g_bitmap, .glyph_dsc = g_glyphs, .cmaps = g_cmaps, .kern_dsc = NULL,
    .kern_scale = 0, .cmap_num = 1, .bpp = 1, .kern_classes = 0, .bitmap_format = 0,
};
static const lv_font_t g_font_ii = {
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt, .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = 16, .base_line = 2, .subpx = LV_FONT_SUBPX_NONE, .static_bitmap = 1, .dsc = &g_dsc,
};

static void read_touch(lv_indev_t *indev, lv_indev_data_t *data)
{
    (void)indev;
    data->point = g_touch;
    data->state = g_touch_down ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static void record(app_event_t e)
{
    if (g_event_count < EVENTS) {   /* a session of the selftest never queues more than EVENTS */
        g_events[g_event_count] = e;
        g_event_count++;
    }
}

static void queue(app_work_t w)
{
    if (g_work_count < WORK) {
        g_work[g_work_count] = w;
        g_work_count++;
    }
}

static void on_button(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_PRESSED) {
        record(APP_BUTTON_PRESSED);
    } else if (code == LV_EVENT_CLICKED) {
        record(APP_BUTTON_CLICKED);
        queue(APP_WORK_PRESS);   /* the intent is queued, not run, in the handler */
    }
}

static void on_overlay(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_PRESSED) {
        record(APP_OVERLAY_PRESSED);
    } else if (code == LV_EVENT_CLICKED) {
        record(APP_OVERLAY_CLICKED);
    }
}

static void on_pointer(lv_event_t *e)
{
    if (lv_event_get_code(e) == LV_EVENT_CLICKED) {
        record(APP_POINTER_CLICKED);
    }
}

static lv_obj_t *label_at(lv_obj_t *parent, const char *text, int32_t x, int32_t y)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_label_set_text(l, text);
    lv_obj_set_pos(l, x, y);
    return l;
}

static lv_obj_t *box(lv_obj_t *screen, int32_t x, int32_t y, int32_t w, uint32_t rgb)
{
    lv_obj_t *s = lv_obj_create(screen);
    lv_obj_remove_style_all(s);
    lv_obj_set_pos(s, x, y);
    lv_obj_set_size(s, w, y == 100 ? 2 : 4);
    lv_obj_set_style_bg_color(s, lv_color_hex(rgb), 0);
    lv_obj_set_style_bg_opa(s, LV_OPA_COVER, 0);
    return s;
}

static void build_screen(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0xFFFFFFu), 0);
    g_objs[0] = label_at(screen, "Frame", 8, 4);
    g_objs[1] = lv_button_create(screen);
    lv_obj_set_pos(g_objs[1], 8, 30);
    lv_obj_set_size(g_objs[1], 90, 30);
    lv_obj_add_event_cb(g_objs[1], on_button, LV_EVENT_ALL, NULL);
    g_button_label = label_at(g_objs[1], "Press", 0, 0);
    lv_obj_center(g_button_label);
    g_objs[2] = label_at(screen, "", 8, 66);
    lv_obj_set_hidden(g_objs[2], true);
    g_objs[3] = label_at(screen, "Fit text", 100, 30);
    lv_obj_set_hidden(label_at(screen, "Hidden", 100, 50), true);
    (void)box(screen, 140, 100, 4, 0xFF0000u);
    (void)box(screen, 144, 100, 4, 0x0000FFu);
    lv_obj_set_style_text_font(label_at(screen, "\xd0\x99", 130, 4), &g_font_ii, 0);   /* "Й" */
    g_bar = box(screen, 120, 70, 0, 0x00A000u);
    g_overlay = lv_obj_create(screen);   /* last: over everything */
    lv_obj_remove_style_all(g_overlay);
    lv_obj_set_pos(g_overlay, 0, 0);
    lv_obj_set_size(g_overlay, APP_W, APP_H);
    lv_obj_set_clickable(g_overlay, false);
    lv_obj_add_event_cb(g_overlay, on_overlay, LV_EVENT_ALL, NULL);
}

static bool create_pointer(void)
{
    g_indev = lv_indev_create();
    if (g_indev == NULL) {
        return false;
    }
    lv_indev_set_type(g_indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(g_indev, read_touch);
    lv_indev_set_display(g_indev, g_disp);
    lv_indev_set_mode(g_indev, LV_INDEV_MODE_EVENT);
    return lv_indev_add_event_cb(g_indev, on_pointer, LV_EVENT_CLICKED, NULL) != NULL;
}

bool app_start(bool big)
{
    if (g_disp != NULL) {
        lv_display_delete(g_disp);
        lv_deinit();
        g_disp = NULL;
    }
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    app_fixture_reset();
    g_event_count = 0;
    g_work_count = 0;
    g_added = NULL;
    g_disp = lvgl_gate_test_display_create(big ? APP_BIG_W : APP_W, big ? APP_BIG_H : APP_H, g_frame,
                                           big ? sizeof g_frame : LVGL_GATE_TEST_BUF_BYTES(APP_W, APP_H), &g_draw_buf);
    if (g_disp == NULL || !create_pointer()) {
        return false;
    }
    lv_timer_set_period(lv_anim_get_timer(), 1);   /* animations run at every step, at the step's tick */
    build_screen();
    app_draw();
    return true;
}

lv_display_t *app_display(void)
{
    return g_disp;
}

void app_draw(void)
{
    lv_refr_now(g_disp);
}

void app_step(uint32_t ms)
{
    lv_tick_inc(ms);
    (void)lv_timer_handler();
}

void app_press(void)
{
    lv_area_t a;
    lv_obj_update_layout(g_objs[1]);
    lv_obj_get_coords(g_objs[1], &a);
    g_touch.x = (a.x1 + a.x2) / 2;
    g_touch.y = (a.y1 + a.y2) / 2;
    g_touch_down = true;
    lv_indev_read(g_indev);
    g_touch_down = false;
    lv_indev_read(g_indev);
}

void app_show_notice(bool shown)
{
    lv_label_set_text(g_objs[2], shown ? "\xd0\x93\xd0\xbe\xd1\x82\xd0\xbe\xd0\xb2\xd0\xbe" : "");   /* "Готово" */
    lv_obj_set_hidden(g_objs[2], !shown);
}

void app_set_title(const char *text)
{
    lv_label_set_text(g_objs[0], text);
}

void app_cover(bool clickable)
{
    lv_obj_set_clickable(g_overlay, clickable);
}

void app_fit(bool room)
{
    lv_obj_set_size(g_objs[3], room ? LV_SIZE_CONTENT : 20, room ? LV_SIZE_CONTENT : 8);
}

bool app_add(void)
{
    if (g_added != NULL) {
        return false;
    }
    g_added = label_at(lv_screen_active(), "New", 100, 80);
    return true;
}

void app_drop(void)
{
    if (g_added != NULL) {
        lv_obj_delete(g_added);
        g_added = NULL;
    }
}

bool app_many(void)
{
    unsigned i;
    for (i = 0; i < APP_MANY; i++) {
        lv_obj_t *l = lv_label_create(lv_screen_active());
        if (l == NULL) {
            return false;
        }
        lv_label_set_text_static(l, "abcdefghijklmnopqrstuvwxyz0123");
        lv_obj_set_hidden(l, true);
    }
    return true;
}

static void bar_width(void *obj, int32_t v)
{
    lv_obj_set_width(obj, v);
}

static void bar_done(lv_anim_t *a)
{
    (void)a;
    queue(APP_WORK_ANIM_DONE);   /* an animation callback posts work; the model runs it */
}

bool app_animate(uint32_t ms)
{
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, g_bar);
    lv_anim_set_exec_cb(&a, bar_width);
    lv_anim_set_values(&a, 0, 20);
    lv_anim_set_duration(&a, ms);
    lv_anim_set_completed_cb(&a, bar_done);
    return lv_anim_start(&a) != NULL;
}

static bool take(void *items, unsigned *count, size_t size, void *out)
{
    unsigned char *base = items;
    unsigned char *dst = out;
    size_t i;
    if (*count == 0u) {
        return false;
    }
    for (i = 0; i < size; i++) {
        dst[i] = base[i];
    }
    for (i = size; i < (size_t)*count * size; i++) {
        base[i - size] = base[i];
    }
    (*count)--;
    return true;
}

bool app_take_event(app_event_t *out)
{
    return take(g_events, &g_event_count, sizeof g_events[0], out);
}

bool app_take_work(app_work_t *out)
{
    return take(g_work, &g_work_count, sizeof g_work[0], out);
}

bool app_node(unsigned i, app_node_t *out)
{
    static const char *const keys[APP_NODES] = {"title", "button", "notice", "fit"};
    lv_obj_t *obj = i < APP_NODES ? g_objs[i] : NULL;
    if (obj == NULL) {
        return false;
    }
    lv_obj_update_layout(obj);
    out->key = keys[i];
    out->text = lv_label_get_text(i == 1u ? g_button_label : obj);
    out->x = lv_obj_get_x(obj);
    out->y = lv_obj_get_y(obj);
    out->w = lv_obj_get_width(obj);
    out->h = lv_obj_get_height(obj);
    out->hidden = lv_obj_is_hidden(obj);
    return true;
}
