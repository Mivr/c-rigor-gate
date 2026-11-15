#include "selftest/ui_frame_product/app.h"

#include <stddef.h>

#include "lvgl_gate.h"

enum { EVENTS = 16 };

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(APP_W, APP_H)];
static lv_draw_buf_t g_draw_buf;
static lv_display_t *g_disp;
static lv_indev_t *g_indev;
static lv_obj_t *g_objs[APP_NODES];      /* title, button, notice, fit */
static lv_obj_t *g_button_label;
static lv_obj_t *g_overlay;
static lv_obj_t *g_added;
static lv_point_t g_touch;
static bool g_touch_down;
static bool g_clicked;
static app_event_t g_events[EVENTS];
static unsigned g_event_count;

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

static void on_button(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_PRESSED) {
        record(APP_BUTTON_PRESSED);
    } else if (code == LV_EVENT_CLICKED) {
        record(APP_BUTTON_CLICKED);
        g_clicked = true;
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

static lv_obj_t *label_at(lv_obj_t *parent, const char *text, int32_t x, int32_t y)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_label_set_text(l, text);
    lv_obj_set_pos(l, x, y);
    return l;
}

static void swatch(lv_obj_t *screen, int32_t x, uint32_t rgb)
{
    lv_obj_t *s = lv_obj_create(screen);
    lv_obj_remove_style_all(s);
    lv_obj_set_pos(s, x, 100);
    lv_obj_set_size(s, 4, 2);
    lv_obj_set_style_bg_color(s, lv_color_hex(rgb), 0);
    lv_obj_set_style_bg_opa(s, LV_OPA_COVER, 0);
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
    swatch(screen, 140, 0xFF0000u);
    swatch(screen, 144, 0x0000FFu);
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
    return true;
}

bool app_start(void)
{
    if (g_disp != NULL) {
        lv_display_delete(g_disp);
        lv_deinit();
        g_disp = NULL;
    }
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    g_event_count = 0;
    g_added = NULL;
    g_disp = lvgl_gate_test_display_create(APP_W, APP_H, g_frame, sizeof g_frame, &g_draw_buf);
    if (g_disp == NULL || !create_pointer()) {
        return false;
    }
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

bool app_press(void)
{
    lv_area_t box;
    lv_obj_update_layout(g_objs[1]);
    lv_obj_get_coords(g_objs[1], &box);
    g_touch.x = (box.x1 + box.x2) / 2;
    g_touch.y = (box.y1 + box.y2) / 2;
    g_clicked = false;
    g_touch_down = true;
    lv_indev_read(g_indev);
    g_touch_down = false;
    lv_indev_read(g_indev);
    return g_clicked;
}

void app_show_notice(void)
{
    lv_label_set_text(g_objs[2], "\xd0\x93\xd0\xbe\xd1\x82\xd0\xbe\xd0\xb2\xd0\xbe");   /* "Готово" */
    lv_obj_set_hidden(g_objs[2], false);
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

bool app_take_event(app_event_t *out)
{
    unsigned i;
    if (g_event_count == 0u) {
        return false;
    }
    *out = g_events[0];
    for (i = 1; i < g_event_count; i++) {
        g_events[i - 1u] = g_events[i];
    }
    g_event_count--;
    return true;
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
