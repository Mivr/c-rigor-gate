#include "selftest/ui_product/toy.h"

#include <stddef.h>

#include "lvgl_gate.h"

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(TOY_W, TOY_H)];
static lv_draw_buf_t g_draw_buf;
static lv_display_t *g_disp;
static lv_obj_t *g_title;
static lv_obj_t *g_button;
static lv_obj_t *g_button_label;
static lv_obj_t *g_notice;
static lv_obj_t *g_scrim;           /* the notice's transparent scrim over the whole screen: clickable while it shows */
static lv_indev_t *g_indev;         /* the product's pointer */
static lv_point_t g_touch;
static bool g_touch_down;
static uint64_t g_notice_due = UINT64_MAX;
static bool g_pressed;

static void read_touch(lv_indev_t *indev, lv_indev_data_t *data)
{
    (void)indev;
    data->point = g_touch;
    data->state = g_touch_down ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static void on_click(lv_event_t *e)
{
    if (lv_event_get_code(e) == LV_EVENT_CLICKED) {
        g_pressed = true;
    }
}

static void build_screen(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0xFFFFFFu), 0);
    g_title = lv_label_create(screen);
    lv_label_set_text(g_title, "Toy");
    lv_obj_set_pos(g_title, 8, 8);
    g_button = lv_button_create(screen);
    lv_obj_set_pos(g_button, 8, 40);
    lv_obj_set_size(g_button, 100, 36);
    lv_obj_add_event_cb(g_button, on_click, LV_EVENT_CLICKED, NULL);
    g_button_label = lv_label_create(g_button);
    lv_label_set_text(g_button_label, "Press");
    lv_obj_center(g_button_label);
    g_notice = lv_label_create(screen);
    lv_label_set_text(g_notice, "");
    lv_obj_set_pos(g_notice, 8, 90);
    lv_obj_set_hidden(g_notice, true);
    g_scrim = lv_obj_create(screen);   /* last: on top of the button (the F3b canary while the notice shows) */
    lv_obj_remove_style_all(g_scrim);
    lv_obj_set_pos(g_scrim, 0, 0);
    lv_obj_set_size(g_scrim, TOY_W, TOY_H);
    lv_obj_set_clickable(g_scrim, false);
}

/* The product's own pointer indev, read only when the app taps (event mode). */
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

static void stop(void)
{
    if (g_disp != NULL) {
        lv_display_delete(g_disp);
        lv_deinit();
        g_disp = NULL;
        g_indev = NULL;
    }
}

bool toy_start(void)
{
    stop();
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    g_notice_due = UINT64_MAX;
    g_pressed = false;
    g_disp = lvgl_gate_test_display_create(TOY_W, TOY_H, g_frame, sizeof g_frame, &g_draw_buf);
    if (g_disp == NULL || !create_pointer()) {
        return false;
    }
    build_screen();
    toy_draw();
    return true;
}

lv_display_t *toy_display(void)
{
    return g_disp;
}

void toy_press(void)
{
    lv_area_t box;
    if (g_button == NULL || g_indev == NULL) {
        return;
    }
    lv_obj_update_layout(g_button);
    lv_obj_get_coords(g_button, &box);
    g_touch.x = (box.x1 + box.x2) / 2;
    g_touch.y = (box.y1 + box.y2) / 2;
    g_pressed = false;
    g_touch_down = true;
    lv_indev_read(g_indev);
    g_touch_down = false;
    lv_indev_read(g_indev);
}

void toy_show_notice(const char *text, uint64_t now_ms)
{
    lv_label_set_text(g_notice, text);
    lv_obj_set_hidden(g_notice, false);
    lv_obj_set_clickable(g_scrim, true);
    g_notice_due = now_ms + TOY_NOTICE_MS;
}

void toy_hide_notice(void)
{
    lv_obj_set_hidden(g_notice, true);
    lv_obj_set_clickable(g_scrim, false);
    g_notice_due = UINT64_MAX;
}

uint64_t toy_notice_due(void)
{
    return g_notice_due;
}

void toy_step(uint32_t ms)
{
    lv_tick_inc(ms);
    (void)lv_timer_handler();
}

bool toy_node(unsigned i, toy_node_t *out)
{
    static const char *const keys[TOY_NODES] = {"title", "button", "notice"};
    static const char *const roles[TOY_NODES] = {"label", "button", "label"};
    lv_obj_t *objs[TOY_NODES];
    objs[0] = g_title;
    objs[1] = g_button;
    objs[2] = g_notice;
    if (i >= TOY_NODES || objs[i] == NULL) {
        return false;
    }
    lv_obj_update_layout(objs[i]);
    out->key = keys[i];
    out->role = roles[i];
    out->text = i == 1u ? lv_label_get_text(g_button_label) : lv_label_get_text(objs[i]);
    out->x = lv_obj_get_x(objs[i]);
    out->y = lv_obj_get_y(objs[i]);
    out->w = lv_obj_get_width(objs[i]);
    out->h = lv_obj_get_height(objs[i]);
    out->hidden = i == 2u && lv_obj_is_hidden(g_notice);
    return true;
}

bool toy_notice_shown(void)
{
    return !lv_obj_is_hidden(g_notice);
}

bool toy_take_press(void)
{
    bool was = g_pressed;
    g_pressed = false;
    return was;
}

void toy_draw(void)
{
    lv_refr_now(g_disp);
}
