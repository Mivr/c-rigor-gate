/* The fixture switches of the frame toy (app.h): each breaks the model interface on purpose, so the selftest sees the
 * probe refuse it. */
#include "selftest/ui_frame_product/app.h"

#include "lvgl_gate.h"

enum { SECOND = 16 };

static uint8_t g_second_frame[LVGL_GATE_TEST_BUF_BYTES(SECOND, SECOND)];
static lv_draw_buf_t g_second_buf;
static lv_display_t *g_second;
static uint32_t g_ticks;
static uint32_t g_clock;

void app_fixture_reset(void)
{
    g_second = NULL;   /* lv_deinit deleted it */
    g_ticks = 0;
    g_clock = 0;
    lv_tick_set_cb(NULL);
}

lv_display_t *app_second_display(void)
{
    lv_display_t *keep = lv_display_get_default();
    if (g_second == NULL) {
        g_second = lvgl_gate_test_display_create(SECOND, SECOND, g_second_frame, sizeof g_second_frame, &g_second_buf);
        lv_display_set_default(keep);
    }
    return g_second;
}

bool app_extra_pointer(void)
{
    lv_indev_t *i = lv_indev_create();
    if (i == NULL) {
        return false;
    }
    lv_indev_set_type(i, LV_INDEV_TYPE_POINTER);
    lv_indev_set_display(i, lv_display_get_default());
    lv_indev_set_mode(i, LV_INDEV_MODE_EVENT);
    return true;
}

static uint32_t moving(void)
{
    g_ticks += 7u;
    return g_ticks;
}

void app_moving_tick(void)
{
    lv_tick_set_cb(moving);
}

static uint32_t clock_now(void)
{
    return g_clock;
}

void app_rare_clock(void)
{
    g_clock = lv_tick_get();
    lv_tick_set_cb(clock_now);
}

void app_clock_moves(void)
{
    g_clock += 1u;
}
