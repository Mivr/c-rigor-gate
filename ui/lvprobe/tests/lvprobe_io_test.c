/* gate//ui/lvprobe through its public header: frame facts, crops, the lifecycle log and the encoder (U02). */
#include "ui/lvprobe/tests/testkit.h"

enum { BOX = 50, MANY = 70, ENC_BYTES = 65536 };

static uint8_t g_before[BOX * BOX * 4];
static uint8_t g_after[BOX * BOX * 4];
static lvprobe_life_t g_life[LVPROBE_LIFE_CAP];
static char g_enc[ENC_BYTES];

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

static uint32_t region(const lv_obj_t *obj)
{
    const lvprobe_node_t *n = lvprobe_node(&tk_probe, tk_index(obj));
    return n != NULL ? n->region_hash : 0u;
}

static void t_one_pixel_changes_the_crc_and_the_region_hash(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 20, 20, BOX, BOX, 0x808080u);
    lv_obj_t *dot = tk_box(box, 10, 10, 1, 1, 0x808080u);
    lv_obj_t *other = tk_box(lv_screen_active(), 200, 100, 30, 30, 0x2040A0u);
    const lv_area_t area = {20, 20, 20 + BOX - 1, 20 + BOX - 1};
    uint32_t crc;
    uint32_t box_hash;
    uint32_t other_hash;
    size_t len = 0;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    crc = lvprobe_frame_crc(&tk_probe);
    box_hash = region(box);
    other_hash = region(other);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &area, g_before, sizeof g_before, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, len, sizeof g_before);
    lv_obj_invalidate(lv_screen_active());
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_U64(t, lvprobe_frame_crc(&tk_probe), crc);
    CHECK_EQ_U64(t, region(box), box_hash);
    lv_obj_set_style_bg_color(dot, lv_color_hex(0x000000u), 0);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &area, g_after, sizeof g_after, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, differing_pixels(), 1);
    CHECK_EQ_U64(t, tk_pixel(30, 30), 0x000000u);
    CHECK(t, lvprobe_frame_crc(&tk_probe) != crc);
    CHECK(t, region(box) != box_hash);
    CHECK_EQ_U64(t, region(other), other_hash);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &area, g_after, sizeof g_after - 1u, &len), LVPROBE_ERR_TRUNC);
    tk_stop(disp);
}

static void t_a_crop_at_the_display_edge(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    const lv_area_t corner = {TK_W - 10, TK_H - 10, TK_W - 1, TK_H - 1};
    const lv_area_t past = {TK_W - 10, TK_H - 10, TK_W, TK_H - 1};
    size_t len = 0;
    (void)tk_box(lv_screen_active(), TK_W - 1, TK_H - 1, 1, 1, 0x0000FFu);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &corner, g_after, sizeof g_after, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, len, 400);
    CHECK(t, g_after[396] == 0u && g_after[397] == 0u && g_after[398] == 0xFFu && g_after[399] == 0xFFu);
    CHECK(t, g_after[0] == 0xFFu && g_after[1] == 0xFFu && g_after[2] == 0xFFu);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &past, g_after, sizeof g_after, &len), LVPROBE_ERR_ARG);
    CHECK_EQ_U64(t, len, 0);
    tk_stop(disp);
}

static void t_the_lifecycle_log_reports_create_and_delete(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *victim = tk_box(lv_screen_active(), 0, 0, 10, 10, 0x00FF00u);
    lv_obj_t *child = tk_box(victim, 0, 0, 5, 5, 0x00FF00u);
    lv_obj_t *tmp;
    uint16_t n = 0;
    uint32_t lost = 0;
    int32_t screen;
    int32_t victim_at;
    int32_t child_at;
    CHECK(t, tk_walk(t));
    victim_at = lvprobe_find(&tk_probe, victim);
    child_at = lvprobe_find(&tk_probe, child);
    CHECK(t, victim_at != LVPROBE_NONE && child_at != LVPROBE_NONE);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    screen = lvprobe_find(&tk_probe, lv_screen_active());
    tmp = lv_label_create(lv_screen_active());
    lv_obj_delete(tmp);
    lv_obj_delete(victim);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 4);
    CHECK_EQ_U64(t, lost, 0);
    CHECK(t, g_life[0].created == 1u && g_life[0].late == 0u && g_life[0].node == LVPROBE_NONE);
    CHECK_EQ_I64(t, g_life[0].parent, screen);
    CHECK_EQ_STR(t, g_life[0].class_name, "lv_label");
    CHECK(t, g_life[1].created == 0u && g_life[1].node == LVPROBE_NONE && g_life[1].parent == screen);
    CHECK(t, g_life[2].created == 0u && g_life[2].node == victim_at && g_life[2].parent == screen);
    CHECK(t, g_life[3].created == 0u && g_life[3].node == child_at);
    CHECK_EQ_I64(t, g_life[3].parent, g_life[2].node);
    CHECK(t, g_life[0].seq < g_life[1].seq && g_life[1].seq < g_life[2].seq && g_life[2].seq < g_life[3].seq);
    CHECK(t, lvprobe_node(&tk_probe, (uint16_t)g_life[2].node)->obj == NULL);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, (uint16_t)g_life[2].node), LVPROBE_ERR_STALE);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 0);
    tk_stop(disp);
}

static void t_a_full_lifecycle_ring_reports_overflow(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    uint16_t n = 0;
    uint32_t lost = 0;
    int i;
    for (i = 0; i < MANY; i++) {
        (void)tk_box(lv_screen_active(), i, 0, 1, 1, 0u);
    }
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_ERR_OVERFLOW);
    CHECK_EQ_U64(t, n, LVPROBE_LIFE_CAP);
    CHECK_EQ_U64(t, lost, MANY - LVPROBE_LIFE_CAP);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 0);
    tk_stop(disp);
}

static void t_a_new_screen_is_logged_late(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *screen;
    uint16_t n = 0;
    uint32_t lost = 0;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    screen = lv_obj_create(NULL);
    (void)lv_label_create(screen);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 2);
    CHECK(t, g_life[0].created == 1u && g_life[0].late == 1u && g_life[0].parent == LVPROBE_NONE);
    CHECK_EQ_STR(t, g_life[0].class_name, "lv_obj");
    CHECK(t, g_life[1].created == 1u && g_life[1].late == 1u);
    CHECK_EQ_STR(t, g_life[1].class_name, "lv_label");
    (void)lv_label_create(screen);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LVPROBE_LIFE_CAP, &n, &lost), LVPROBE_OK);
    CHECK(t, n == 1u && g_life[0].created == 1u && g_life[0].late == 0u);
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_ERR_STALE);
    tk_stop(disp);
}

static void t_the_encoder_escapes_and_truncation_is_an_error(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *label = tk_label(lv_screen_active(), "a\\b\x01\"\xD0\x99\xFFz", 10, 10);
    lv_obj_t *nothing = tk_box(lv_screen_active(), 30, 40, 0, 0, 0u);
    size_t len = 0;
    size_t again = 0;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(label)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_enc, sizeof g_enc, &len), LVPROBE_OK);
    CHECK(t, len > 100u && len < sizeof g_enc);
    CHECK(t, tk_contains(g_enc, len, "lvprobe/1 nodes="));
    CHECK(t, tk_contains(g_enc, len, "frame w=320 h=240 crc="));
    CHECK(t, tk_contains(g_enc, len, " text=\"a\\\\b\\x01\\\"\xD0\x99\\xffz\" full_text="));
    CHECK(t, tk_contains(g_enc, len, " class=\"lv_label\" "));
    CHECK(t, tk_contains(g_enc, len, " box=30,40,29,39 "));
    CHECK(t, tk_contains(g_enc, len, "\nink ") && tk_contains(g_enc, len, "\nregion "));
    CHECK_EQ_U64(t, (unsigned char)g_enc[len], 0);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_enc, len, &again), LVPROBE_ERR_TRUNC);
    CHECK_EQ_U64(t, again, 0);
    CHECK_EQ_U64(t, (unsigned char)g_enc[0], 0);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_enc, 10, &again), LVPROBE_ERR_TRUNC);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_enc, len + 1u, &again), LVPROBE_OK);
    CHECK_EQ_U64(t, again, len);
    (void)nothing;
    tk_stop(disp);
}

CTEST_SUITE("lvprobe_io",
            { "one_pixel_changes_the_crc_and_the_region_hash", t_one_pixel_changes_the_crc_and_the_region_hash },
            { "a_crop_at_the_display_edge", t_a_crop_at_the_display_edge },
            { "the_lifecycle_log_reports_create_and_delete", t_the_lifecycle_log_reports_create_and_delete },
            { "a_full_lifecycle_ring_reports_overflow", t_a_full_lifecycle_ring_reports_overflow },
            { "a_new_screen_is_logged_late", t_a_new_screen_is_logged_late },
            { "the_encoder_escapes_and_truncation_is_an_error", t_the_encoder_escapes_and_truncation_is_an_error })
