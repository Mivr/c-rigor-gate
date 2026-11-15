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
static uint64_t g_notice_due = UINT64_MAX;
static bool g_pressed;

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
}

static void stop(void)
{
    if (g_disp != NULL) {
        lv_display_delete(g_disp);
        lv_deinit();
        g_disp = NULL;
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
    if (g_disp == NULL) {
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
    if (g_button != NULL) {
        lv_obj_send_event(g_button, LV_EVENT_CLICKED, NULL);
    }
}

void toy_show_notice(const char *text, uint64_t now_ms)
{
    lv_label_set_text(g_notice, text);
    lv_obj_set_hidden(g_notice, false);
    g_notice_due = now_ms + TOY_NOTICE_MS;
}

void toy_hide_notice(void)
{
    lv_obj_set_hidden(g_notice, true);
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

const char *toy_title(void)
{
    return lv_label_get_text(g_title);
}

const char *toy_button_text(void)
{
    return lv_label_get_text(g_button_label);
}

const char *toy_notice_text(void)
{
    return lv_label_get_text(g_notice);
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
