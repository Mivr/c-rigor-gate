/* gate//ui/lvprobe through its public header: ink attribution and its stability checks (U02). */
#include "ui/lvprobe/tests/testkit.h"

static int g_focus_events;
static int g_moves;

static void t_ink_of_a_box_a_label_and_a_hidden_label(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 5, 5, 10, 10, 0x000000u);
    lv_obj_t *shown = tk_label(lv_screen_active(), "AA", 40, 10);
    lv_obj_t *hidden = tk_label(lv_screen_active(), "AA", 40, 40);
    const lvprobe_node_t *n;
    uint32_t crc;
    lv_obj_set_hidden(hidden, true);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    crc = lvprobe_frame_crc(&tk_probe);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(box)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(shown)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(hidden)), LVPROBE_OK);
    n = tk_node(t, box);
    if (n != NULL) {
        CHECK_EQ_U64(t, n->ink, 100);
        CHECK(t, tk_box_is(&n->ink_box, 5, 5, 14, 14));
        CHECK_EQ_U64(t, n->ink_lo, 0x000000u);
        CHECK_EQ_U64(t, n->ink_hi, 0x000000u);
        CHECK_EQ_U64(t, n->bg_lo, 0xFFFFFFu);
        CHECK_EQ_U64(t, n->bg_hi, 0xFFFFFFu);
    }
    n = tk_node(t, shown);
    if (n != NULL) {
        CHECK_EQ_U64(t, n->ink, 192);
        CHECK_EQ_U64(t, n->ink, tk_count_not(&n->coords, 0xFFFFFFu));
        CHECK(t, tk_box_is(&n->ink_box, 41, 12, 58, 23));
    }
    n = tk_node(t, hidden);
    CHECK(t, n != NULL && n->has_ink && n->ink == 0u && !n->unstable);
    CHECK(t, lv_obj_is_hidden(hidden) && !lv_obj_is_hidden(shown));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_U64(t, lvprobe_frame_crc(&tk_probe), crc);
    tk_stop(disp);
}

/* An empty banner between two boxes of a flex column: not drawing it must not let the second box move up. */
static void t_ink_in_a_flex_column_counts_only_the_node(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *column = tk_box(lv_screen_active(), 20, 20, 100, LV_SIZE_CONTENT, 0xFFFFFFu);
    lv_obj_t *top;
    lv_obj_t *banner;
    lv_obj_t *bottom;
    const lvprobe_node_t *n;
    lv_obj_set_flex_flow(column, LV_FLEX_FLOW_COLUMN);
    top = tk_box(column, 0, 0, 100, 10, 0xFF0000u);
    banner = tk_box(column, 0, 0, 100, 20, 0xFFFFFFu);
    lv_obj_set_style_bg_opa(banner, LV_OPA_TRANSP, 0);
    bottom = tk_box(column, 0, 0, 100, 10, 0x0000FFu);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(banner)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(top)), LVPROBE_OK);
    n = tk_node(t, banner);
    CHECK(t, n != NULL && n->has_ink && n->ink == 0u && tk_box_is(&n->coords, 20, 30, 119, 49));
    n = tk_node(t, top);
    CHECK(t, n != NULL && n->ink == 1000u && tk_box_is(&n->ink_box, 20, 20, 119, 29));
    n = tk_node(t, bottom);
    CHECK(t, n != NULL && tk_box_is(&n->coords, 20, 50, 119, 59));
    tk_stop(disp);
}

static void on_focus(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_FOCUSED || code == LV_EVENT_DEFOCUSED) {
        g_focus_events++;
    }
}

static void t_ink_keeps_the_focus(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_group_t *group = lv_group_create();
    lv_obj_t *first = lv_button_create(lv_screen_active());
    lv_obj_t *second = lv_button_create(lv_screen_active());
    lv_obj_set_pos(second, 0, 100);
    lv_group_add_obj(group, first);
    lv_group_add_obj(group, second);
    lv_group_focus_obj(first);
    lv_obj_add_event_cb(first, on_focus, LV_EVENT_ALL, NULL);
    lv_obj_add_event_cb(second, on_focus, LV_EVENT_ALL, NULL);
    CHECK(t, tk_walk(t));
    g_focus_events = 0;
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(first)), LVPROBE_OK);
    CHECK(t, lv_group_get_focused(group) == first);
    CHECK_EQ_I64(t, g_focus_events, 0);
    CHECK(t, lv_obj_has_state(first, LV_STATE_FOCUSED));
    lv_group_delete(group);
    tk_stop(disp);
}

static bool g_armed;

static lv_obj_t *g_restless;

/* A product that moves an object after every refresh (once armed, after the walk). */
static void move_after_refresh(lv_event_t *e)
{
    if (g_armed && lv_event_get_code(e) == LV_EVENT_REFR_READY) {
        g_moves++;
        lv_obj_set_x(g_restless, lv_obj_get_x(g_restless) + 1);
    }
}

static void t_a_node_that_moves_when_restyled_is_unstable(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 5, 5, 10, 10, 0x000000u);
    lv_obj_t *restless = tk_box(lv_screen_active(), 200, 100, 20, 20, 0x00FF00u);
    static char text[8192];
    size_t len = 0;
    const lvprobe_node_t *n;
    g_restless = restless;
    lv_display_add_event_cb(disp, move_after_refresh, LV_EVENT_REFR_READY, NULL);
    g_armed = false;
    CHECK(t, tk_walk(t));
    g_moves = 0;
    g_armed = true;
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(box)), LVPROBE_ERR_UNSTABLE);
    CHECK(t, g_moves > 0);
    n = tk_node(t, box);
    CHECK(t, n != NULL && n->unstable && !n->has_ink && n->ink == 0u);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, text, sizeof text, &len), LVPROBE_OK);
    CHECK(t, tk_contains(text, len, " unstable=1\n"));
    CHECK(t, !tk_contains(text, len, " unstable=0"));
    tk_stop(disp);
}

static void t_ink_needs_room_a_current_walk_and_a_settled_frame(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 5, 5, 10, 10, 0x000000u);
    CHECK(t, tk_walk(t));
    lv_obj_set_style_bg_color(box, lv_color_hex(0x00FF00u), 0);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(box)), LVPROBE_ERR_UNSETTLED);
    CHECK(t, tk_walk(t));
    (void)tk_box(lv_screen_active(), 50, 5, 10, 10, 0x000000u);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(box)), LVPROBE_ERR_STALE);
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_ERR_STALE);
    lvprobe_close(&tk_probe);
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, NULL, tk_scratch, 99), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, NULL, tk_scratch, 99), LVPROBE_ERR_ARG);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(box)), LVPROBE_ERR_FULL);
    tk_stop(disp);
}

static void t_a_partial_or_double_buffered_display_is_a_format_error(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 5, 5, 10, 10, 0x000000u);
    lv_area_t corner = {0, 0, 9, 9};
    static uint8_t rgba[400];
    size_t len = 0;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    lv_display_set_render_mode(disp, LV_DISPLAY_RENDER_MODE_PARTIAL);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_ERR_FORMAT);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(box)), LVPROBE_ERR_FORMAT);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &corner, rgba, sizeof rgba, &len), LVPROBE_ERR_FORMAT);
    tk_stop(disp);
}

/* The app removes every event callback of an object (the probe's too) and deletes it: the probe sees no deletion,
 * yet it never uses the stale pointer. */
static void t_an_object_deleted_unseen_is_gone(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 5, 5, 10, 10, 0x000000u);
    uint16_t at;
    bool flushed = false;
    CHECK(t, tk_walk(t));
    at = tk_index(box);
    while (lv_obj_get_event_count(box) > 0u) {
        CHECK(t, lv_obj_remove_event(box, 0));
    }
    lv_obj_delete(box);
    CHECK_EQ_I64(t, lvprobe_settle(&tk_probe, &flushed), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, at), LVPROBE_ERR_GONE);
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    tk_stop(disp);
}

CTEST_SUITE("lvprobe_ink", { "ink_of_a_box_a_label_and_a_hidden_label", t_ink_of_a_box_a_label_and_a_hidden_label },
            { "ink_in_a_flex_column_counts_only_the_node", t_ink_in_a_flex_column_counts_only_the_node },
            { "ink_keeps_the_focus", t_ink_keeps_the_focus },
            { "a_node_that_moves_when_restyled_is_unstable", t_a_node_that_moves_when_restyled_is_unstable },
            { "ink_needs_room_a_current_walk_and_a_settled_frame", t_ink_needs_room_a_current_walk_and_a_settled_frame },
            { "an_object_deleted_unseen_is_gone", t_an_object_deleted_unseen_is_gone },
            { "a_partial_or_double_buffered_display_is_a_format_error",
              t_a_partial_or_double_buffered_display_is_a_format_error })
