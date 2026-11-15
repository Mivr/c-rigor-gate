/* gate//ui/lvprobe through its public header: hit injection, frame facts, the lifecycle log (U02). */
#include <stddef.h>
#include <stdint.h>

#include "ctest/ctest.h"
#include "lvgl.h"
#include "lvgl_gate.h"
#include "ui/lvprobe/lvprobe.h"

enum { W = 320, H = 240, BOX = 50, MANY = 70 };

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(W, H)];
static lv_draw_buf_t g_draw_buf;
static uint32_t g_scratch[W * H];
static lvprobe_t g_probe;
static uint8_t g_before[BOX * BOX * 4];
static uint8_t g_after[BOX * BOX * 4];
static lvprobe_life_t g_life[LVPROBE_LIFE_CAP];
static int g_button_clicks;

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

static void on_button(lv_event_t *e)
{
    if (lv_event_get_code(e) == LV_EVENT_CLICKED) {
        g_button_clicks++;
    }
}

static lv_obj_t *plain_box(lv_obj_t *parent, int32_t x, int32_t y, int32_t w, int32_t h, uint32_t rgb)
{
    lv_obj_t *obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, w, h);
    lv_obj_set_style_bg_color(obj, lv_color_hex(rgb), 0);
    lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
    return obj;
}

static void t_a_transparent_clickable_overlay_steals_the_tap(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *button;
    lv_obj_t *overlay;
    const lvprobe_node_t *o;
    lvprobe_hit_t hit;
    if (disp == NULL) {
        return;
    }
    button = lv_button_create(lv_screen_active());
    lv_obj_set_size(button, 100, 50);
    lv_obj_center(button);
    lv_obj_add_event_cb(button, on_button, LV_EVENT_CLICKED, NULL);
    overlay = lv_obj_create(lv_screen_active());
    lv_obj_set_size(overlay, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_opa(overlay, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(overlay, 0, 0);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    o = lvprobe_node(&g_probe, (uint16_t)lvprobe_find(&g_probe, overlay));
    CHECK(t, o != NULL);
    if (o != NULL) {
        CHECK(t, o->clickable && o->bg_opa == LV_OPA_TRANSP);
        CHECK(t, o->coords.x1 == 0 && o->coords.y1 == 0 && o->coords.x2 == W - 1 && o->coords.y2 == H - 1);
    }
    CHECK_EQ_I64(t, lvprobe_hit(&g_probe, W / 2, H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked && hit.obj == overlay);
    CHECK_EQ_I64(t, hit.node, lvprobe_find(&g_probe, overlay));
    CHECK_EQ_I64(t, g_button_clicks, 0);
    lv_obj_set_clickable(overlay, false);
    CHECK_EQ_I64(t, lvprobe_hit(&g_probe, W / 2, H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked && hit.obj == button);
    CHECK_EQ_I64(t, hit.node, lvprobe_find(&g_probe, button));
    CHECK_EQ_I64(t, g_button_clicks, 1);
    stop(disp);
}

static size_t differing_pixels(void)
{
    size_t n = 0;
    size_t i;
    for (i = 0; i < sizeof g_before; i += 4u) {
        n += (g_before[i] != g_after[i] || g_before[i + 1u] != g_after[i + 1u] || g_before[i + 2u] != g_after[i + 2u])
                 ? 1u
                 : 0u;
    }
    return n;
}

static void t_one_pixel_changes_the_crc_and_the_region_hash(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *box;
    lv_obj_t *dot;
    lv_obj_t *other;
    uint32_t crc;
    uint32_t box_hash;
    uint32_t other_hash;
    const lv_area_t area = {20, 20, 20 + BOX - 1, 20 + BOX - 1};
    size_t len = 0;
    if (disp == NULL) {
        return;
    }
    box = plain_box(lv_screen_active(), 20, 20, BOX, BOX, 0x808080u);
    dot = plain_box(box, 10, 10, 1, 1, 0x808080u);
    other = plain_box(lv_screen_active(), 200, 100, 30, 30, 0x2040A0u);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_frame(&g_probe), LVPROBE_OK);
    crc = lvprobe_frame_crc(&g_probe);
    box_hash = lvprobe_node(&g_probe, (uint16_t)lvprobe_find(&g_probe, box))->region_hash;
    other_hash = lvprobe_node(&g_probe, (uint16_t)lvprobe_find(&g_probe, other))->region_hash;
    CHECK_EQ_I64(t, lvprobe_crop(&g_probe, &area, g_before, sizeof g_before, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, len, sizeof g_before);
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(disp);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_frame(&g_probe), LVPROBE_OK);
    CHECK_EQ_U64(t, lvprobe_frame_crc(&g_probe), crc);
    CHECK_EQ_U64(t, lvprobe_node(&g_probe, (uint16_t)lvprobe_find(&g_probe, box))->region_hash, box_hash);
    lv_obj_set_style_bg_color(dot, lv_color_hex(0x000000u), 0);
    lv_refr_now(disp);
    CHECK_EQ_I64(t, lvprobe_frame(&g_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_crop(&g_probe, &area, g_after, sizeof g_after, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, differing_pixels(), 1);
    CHECK(t, lvprobe_frame_crc(&g_probe) != crc);
    CHECK(t, lvprobe_node(&g_probe, (uint16_t)lvprobe_find(&g_probe, box))->region_hash != box_hash);
    CHECK_EQ_U64(t, lvprobe_node(&g_probe, (uint16_t)lvprobe_find(&g_probe, other))->region_hash, other_hash);
    CHECK_EQ_I64(t, lvprobe_crop(&g_probe, &area, g_after, sizeof g_after - 1u, &len), LVPROBE_ERR_TRUNC);
    stop(disp);
}

static void t_the_lifecycle_log_reports_create_and_delete(ctest_t *t)
{
    lv_display_t *disp = start(t);
    lv_obj_t *victim;
    lv_obj_t *tmp;
    uint16_t n = 0;
    uint32_t lost = 0;
    int32_t screen;
    int32_t victim_at;
    if (disp == NULL) {
        return;
    }
    victim = plain_box(lv_screen_active(), 0, 0, 10, 10, 0x00FF00u);
    CHECK_EQ_I64(t, lvprobe_walk(&g_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_life(&g_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    screen = lvprobe_find(&g_probe, lv_screen_active());
    victim_at = lvprobe_find(&g_probe, victim);
    CHECK(t, screen != LVPROBE_NONE && victim_at != LVPROBE_NONE);
    tmp = lv_label_create(lv_screen_active());
    lv_obj_delete(tmp);
    lv_obj_delete(victim);
    CHECK_EQ_I64(t, lvprobe_life(&g_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 3);
    CHECK_EQ_U64(t, lost, 0);
    CHECK(t, g_life[0].created == 1u && g_life[0].node == LVPROBE_NONE && g_life[0].parent == screen);
    CHECK_EQ_STR(t, g_life[0].class_name, "lv_label");
    CHECK(t, g_life[1].created == 0u && g_life[1].node == LVPROBE_NONE && g_life[1].parent == screen);
    CHECK_EQ_STR(t, g_life[1].class_name, "lv_label");
    CHECK(t, g_life[2].created == 0u && g_life[2].node == victim_at);
    CHECK(t, g_life[0].seq < g_life[1].seq && g_life[1].seq < g_life[2].seq);
    CHECK(t, lvprobe_node(&g_probe, (uint16_t)victim_at)->obj == NULL);
    CHECK_EQ_I64(t, lvprobe_ink(&g_probe, (uint16_t)victim_at), LVPROBE_ERR_GONE);
    CHECK_EQ_I64(t, lvprobe_life(&g_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 0);
    stop(disp);
}

static void t_a_full_lifecycle_ring_reports_overflow(ctest_t *t)
{
    lv_display_t *disp = start(t);
    uint16_t n = 0;
    uint32_t lost = 0;
    int i;
    if (disp == NULL) {
        return;
    }
    for (i = 0; i < MANY; i++) {
        (void)plain_box(lv_screen_active(), i, 0, 1, 1, 0u);
    }
    CHECK_EQ_I64(t, lvprobe_life(&g_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_ERR_OVERFLOW);
    CHECK_EQ_U64(t, n, LVPROBE_LIFE_CAP);
    CHECK_EQ_U64(t, lost, MANY - LVPROBE_LIFE_CAP);
    CHECK_EQ_I64(t, lvprobe_life(&g_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 0);
    stop(disp);
}

CTEST_SUITE("lvprobe_io",
            { "a_transparent_clickable_overlay_steals_the_tap", t_a_transparent_clickable_overlay_steals_the_tap },
            { "one_pixel_changes_the_crc_and_the_region_hash", t_one_pixel_changes_the_crc_and_the_region_hash },
            { "the_lifecycle_log_reports_create_and_delete", t_the_lifecycle_log_reports_create_and_delete },
            { "a_full_lifecycle_ring_reports_overflow", t_a_full_lifecycle_ring_reports_overflow })
