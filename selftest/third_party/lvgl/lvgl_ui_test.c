/* Throwaway product test of the LVGL self-test (T107): the gate-owned library through its public headers.
 * Product rules apply to this file (sealed flags, static memory, no libc allocation). */
#include <stddef.h>
#include <stdint.h>

#include "ctest/ctest.h"
#include "lvgl.h"
#include "lvgl_gate.h"

enum { W = 320, H = 240, BTN_X = 20, BTN_Y = 120, BTN_W = 120, BTN_H = 60 };

#define GREEN 0x00AA00u
#define WHITE 0x00FFFFFFu

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(W, H)];
static lv_draw_buf_t g_draw_buf;
static int g_clicks;
static lv_obj_t *g_button;
static lv_obj_t *g_label;

static void on_click(lv_event_t *e)
{
    if (lv_event_get_code(e) == LV_EVENT_CLICKED) {
        g_clicks++;
    }
}

static size_t used_bytes(void)
{
    lv_mem_monitor_t mon;
    lv_mem_monitor(&mon);
    return mon.total_size - mon.free_size;
}

static size_t live_allocations(void)
{
    lv_mem_monitor_t mon;
    lv_mem_monitor(&mon);
    return (size_t)mon.used_cnt;
}

static size_t peak_bytes(void)
{
    lv_mem_monitor_t mon;
    lv_mem_monitor(&mon);
    return (size_t)mon.max_used;
}

static lv_display_t *start(void)
{
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    g_clicks = 0;
    return lvgl_gate_test_display_create(W, H, g_frame, sizeof g_frame, &g_draw_buf);
}

static void build_scene(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(WHITE), 0);
    g_button = lv_button_create(screen);
    lv_obj_set_pos(g_button, BTN_X, BTN_Y);
    lv_obj_set_size(g_button, BTN_W, BTN_H);
    lv_obj_set_style_bg_color(g_button, lv_color_hex(GREEN), 0);
    lv_obj_set_style_bg_opa(g_button, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(g_button, 0, 0);
    lv_obj_set_style_shadow_width(g_button, 0, 0);
    lv_obj_add_event_cb(g_button, on_click, LV_EVENT_CLICKED, NULL);
    g_label = lv_label_create(screen);
    lv_label_set_text(g_label, "Hello 42");
    lv_obj_set_pos(g_label, 20, 20);
    lv_obj_set_style_text_color(g_label, lv_color_hex(0), 0);
}

static void stop(lv_display_t *disp)
{
    lv_test_indev_delete_all();
    lv_display_delete(disp);
    lv_deinit();
}

static uint32_t frame_crc(void)
{
    uint32_t h = 2166136261u;
    int32_t x;
    int32_t y;
    for (y = 0; y < H; y++) {
        for (x = 0; x < W; x++) {
            h = (h ^ lvgl_gate_test_display_pixel(&g_draw_buf, x, y)) * 16777619u;
        }
    }
    return h;
}

static int count_not_white(int32_t x0, int32_t y0, int32_t x1, int32_t y1)
{
    int n = 0;
    int32_t x;
    int32_t y;
    for (y = y0; y < y1; y++) {
        for (x = x0; x < x1; x++) {
            n += lvgl_gate_test_display_pixel(&g_draw_buf, x, y) != WHITE ? 1 : 0;
        }
    }
    return n;
}

static void t_draws_a_label_and_a_button(ctest_t *t)
{
    lv_display_t *disp = start();
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        return;
    }
    build_scene();
    lv_test_wait(400);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, 0, 0), WHITE);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, W - 1, H - 1), WHITE);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, BTN_X + BTN_W / 2, BTN_Y + BTN_H / 2), GREEN);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, BTN_X + 1, BTN_Y + 1), GREEN);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, BTN_X + BTN_W, BTN_Y + BTN_H), WHITE);
    CHECK(t, count_not_white(20, 20, 100, 40) > 20);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, -1, 0), 0);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, 0, H), 0);
    CHECK_EQ_I64(t, (long)lv_obj_get_child_count(lv_screen_active()), 2);
    stop(disp);
}

static void t_the_render_is_deterministic(ctest_t *t)
{
    uint32_t first;
    lv_display_t *disp = start();
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        return;
    }
    build_scene();
    lv_test_wait(400);
    first = frame_crc();
    lv_obj_invalidate(lv_screen_active());
    lv_test_wait(100);
    CHECK_EQ_U64(t, frame_crc(), first);
    lv_label_set_text(g_label, "Hello 43");
    lv_test_wait(100);
    CHECK(t, frame_crc() != first);
    stop(disp);
}

static void t_a_click_reaches_the_event_callback(ctest_t *t)
{
    lv_display_t *disp = start();
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        return;
    }
    build_scene();
    lv_test_indev_create_all();
    lv_test_wait(400);
    lv_test_mouse_click_at(BTN_X + BTN_W / 2, BTN_Y + BTN_H / 2);
    CHECK_EQ_I64(t, g_clicks, 1);
    lv_test_mouse_click_at(2, 2);
    CHECK_EQ_I64(t, g_clicks, 1);
    lv_test_mouse_click_at(BTN_X + 5, BTN_Y + 5);
    CHECK_EQ_I64(t, g_clicks, 2);
    lv_test_wait(400);
    CHECK_EQ_U64(t, lvgl_gate_test_display_pixel(&g_draw_buf, BTN_X + BTN_W / 2, BTN_Y + BTN_H / 2), GREEN);
    stop(disp);
}

/* One build, render, click and delete of the scene. */
static void cycle(void)
{
    build_scene();
    lv_test_wait(400);
    lv_test_mouse_click_at(BTN_X + 10, BTN_Y + 10);
    lv_obj_delete(g_label);
    lv_obj_delete(g_button);
    lv_test_wait(400);
}

/* The first two cycles allocate what LVGL keeps for later (timers, caches). Every later cycle must end with
 * the same bytes and the same number of live allocations, and the peak of the whole run (about 9 KiB when
 * measured) stays far below the 512 KiB pool. */
static void t_everything_deleted_gives_the_memory_back(ctest_t *t)
{
    size_t baseline;
    size_t count;
    int i;
    lv_display_t *disp = start();
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        return;
    }
    lv_test_indev_create_all();
    cycle();
    cycle();
    baseline = used_bytes();
    count = live_allocations();
    for (i = 0; i < 3; i++) {
        cycle();
        CHECK_EQ_U64(t, live_allocations(), count);
        CHECK_EQ_U64(t, used_bytes(), baseline);
    }
    CHECK_EQ_I64(t, g_clicks, 5);
    CHECK(t, peak_bytes() > baseline && peak_bytes() < 16384u);
    lv_test_indev_delete_all();
    lv_display_delete(disp);
    lv_deinit();
}

static void t_allocation_past_the_pool_fails_cleanly(ctest_t *t)
{
    void *chunk[16];
    int got = 0;
    int i;
    lv_display_t *disp = start();
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        return;
    }
    CHECK(t, lv_malloc((size_t)LV_MEM_SIZE) == NULL);
    CHECK(t, lv_malloc((size_t)1 << 40) == NULL);
    for (i = 0; i < 16; i++) {
        chunk[i] = lv_malloc(64u * 1024u);
        if (chunk[i] != NULL) {
            got++;
        }
    }
    CHECK(t, got >= 4 && got < 16);
    CHECK(t, chunk[15] == NULL);
    for (i = 0; i < 16; i++) {
        if (chunk[i] != NULL) {
            lv_free(chunk[i]);
        }
    }
    CHECK(t, lv_malloc(64u * 1024u) != NULL);
    lv_display_delete(disp);
    lv_deinit();
}

static void t_tiny_ttf_refuses_garbage_without_leaking(ctest_t *t)
{
    static const uint8_t junk[64] = {1, 2, 3};
    size_t before;
    lv_font_t *font;
    lv_display_t *disp = start();
    CHECK(t, disp != NULL);
    if (disp == NULL) {
        return;
    }
    before = used_bytes();
    font = lv_tiny_ttf_create_data(junk, sizeof junk, 16);
    CHECK(t, font == NULL);
    CHECK_EQ_U64(t, used_bytes(), before);
    lv_display_delete(disp);
    lv_deinit();
}

CTEST_SUITE("lvgl", { "draws_a_label_and_a_button", t_draws_a_label_and_a_button },
            { "the_render_is_deterministic", t_the_render_is_deterministic },
            { "a_click_reaches_the_event_callback", t_a_click_reaches_the_event_callback },
            { "everything_deleted_gives_the_memory_back", t_everything_deleted_gives_the_memory_back },
            { "allocation_past_the_pool_fails_cleanly", t_allocation_past_the_pool_fails_cleanly },
            { "tiny_ttf_refuses_garbage_without_leaking", t_tiny_ttf_refuses_garbage_without_leaking })
