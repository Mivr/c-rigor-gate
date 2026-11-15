/* gate//ui/lvprobe through its public header: hit injection through LVGL's pointer indev (U02). */
#include "ui/lvprobe/tests/testkit.h"

static int g_clicks;
static int g_singles;
static int g_doubles;
static int g_triples;
static int g_marker;
static int g_product_reads;
static bool g_user_data_ok;

static void check_user_data(lv_event_t *e)
{
    if (lv_event_get_code(e) == LV_EVENT_PRESSED) {
        g_user_data_ok = lv_indev_get_user_data(lv_indev_active()) == &g_marker;
    }
}


static void count_clicks(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    g_clicks += code == LV_EVENT_CLICKED ? 1 : 0;
    g_singles += code == LV_EVENT_SINGLE_CLICKED ? 1 : 0;
    g_doubles += code == LV_EVENT_DOUBLE_CLICKED ? 1 : 0;
    g_triples += code == LV_EVENT_TRIPLE_CLICKED ? 1 : 0;
}

static lv_obj_t *button_at_centre(void)
{
    lv_obj_t *button = tk_ok(lv_button_create(lv_screen_active()));
    lv_obj_set_size(button, 100, 50);
    lv_obj_center(button);
    (void)tk_ok(lv_obj_add_event_cb(button, count_clicks, LV_EVENT_ALL, NULL));
    return button;
}

static void t_a_transparent_clickable_overlay_steals_the_tap(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *button = button_at_centre();
    lv_obj_t *overlay = tk_ok(lv_obj_create(lv_screen_active()));
    const lvprobe_node_t *o;
    lvprobe_hit_t hit;
    lv_obj_set_size(overlay, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_opa(overlay, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(overlay, 0, 0);
    CHECK(t, tk_walk(t));
    o = tk_node(t, overlay);
    CHECK(t, o != NULL && o->clickable && o->bg_opa_drawn == 0u && tk_box_is(&o->coords, 0, 0, TK_W - 1, TK_H - 1));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == overlay && hit.pressed_node == tk_index(overlay));
    CHECK(t, hit.clicked && hit.obj == overlay);
    CHECK_EQ_I64(t, hit.node, tk_index(overlay));
    CHECK_EQ_I64(t, g_clicks, 0);
    lv_obj_set_clickable(overlay, false);
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_ERR_STALE); /* a flag changed */
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == button);
    CHECK(t, hit.clicked && hit.obj == button);
    CHECK_EQ_I64(t, hit.node, tk_index(button));
    CHECK_EQ_I64(t, g_clicks, 1);
    tk_stop(t, disp);
}

static void t_a_disabled_target_is_pressed_but_not_clicked(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *button = button_at_centre();
    lvprobe_hit_t hit;
    lv_obj_add_state(button, LV_STATE_DISABLED);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == button && hit.pressed_node == tk_index(button));
    CHECK(t, !hit.clicked && hit.obj == NULL && hit.node == LVPROBE_NONE);
    CHECK_EQ_I64(t, g_clicks, 0);
    tk_stop(t, disp);
}

static void t_three_taps_are_three_single_clicks(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lvprobe_hit_t hit;
    int i;
    (void)button_at_centre();
    CHECK(t, tk_walk(t));
    g_clicks = 0;
    for (i = 0; i < 3; i++) {
        CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
        CHECK(t, hit.clicked);
    }
    CHECK_EQ_I64(t, g_clicks, 3);
    CHECK_EQ_I64(t, g_singles, 3);
    CHECK_EQ_I64(t, g_doubles, 0);
    CHECK_EQ_I64(t, g_triples, 0);
    tk_stop(t, disp);
}

static void t_a_point_outside_the_display_is_refused(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lvprobe_hit_t hit;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, -1, 10, &hit), LVPROBE_ERR_ARG);
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W, 10, &hit), LVPROBE_ERR_ARG);
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, 10, TK_H, &hit), LVPROBE_ERR_ARG);
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W - 1, TK_H - 1, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked && hit.obj == lv_screen_active());
    tk_stop(t, disp);
}

static void t_a_tap_during_a_screen_load_animation_is_blocked(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *next;
    lvprobe_hit_t hit;
    int32_t node = 0;
    lv_obj_t *found = NULL;
    (void)button_at_centre();
    lv_test_indev_create_all();
    next = tk_ok(lv_obj_create(NULL));
    CHECK(t, tk_walk(t));
    lv_screen_load_anim(next, LV_SCREEN_LOAD_ANIM_FADE_IN, 300, 0, false);
    /* Only scr_to_load is set (the animation has not started): LVGL still processes taps, and so does the probe. */
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked);
    CHECK_EQ_I64(t, g_clicks, 1);
    lv_anim_refr_now(); /* the animation starts: prev_scr is set, lv_indev_read returns at once */
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_ERR_BLOCKED);
    CHECK_EQ_I64(t, lvprobe_hit_test(&tk_probe, TK_W / 2, TK_H / 2, &node, &found), LVPROBE_ERR_BLOCKED);
    CHECK_EQ_I64(t, g_clicks, 1);
    lv_test_mouse_click_at(TK_W / 2, TK_H / 2); /* LVGL's own test mouse agrees: nothing is clicked either */
    CHECK_EQ_I64(t, g_clicks, 1);
    lv_test_indev_delete_all();
    tk_stop(t, disp);
}

static void product_read(lv_indev_t *indev, lv_indev_data_t *data)
{
    (void)indev;
    g_product_reads++;
    data->point.x = 0;
    data->point.y = 0;
    data->state = LV_INDEV_STATE_RELEASED;
}

static void t_taps_go_through_the_products_indev(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_indev_t *indev = tk_ok(lv_indev_create());
    lvprobe_config_t cfg = tk_config();
    lv_obj_t *button;
    lvprobe_hit_t hit;
    lv_point_t where = {0, 0};
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, product_read);
    lv_indev_set_user_data(indev, &g_marker);
    lv_indev_set_display(indev, disp);
    lvprobe_close(&tk_probe);
    cfg.indev = indev;
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, &cfg), LVPROBE_OK);
    button = button_at_centre();
    (void)tk_ok(lv_obj_add_event_cb(button, check_user_data, LV_EVENT_PRESSED, NULL));
    g_user_data_ok = false;
    CHECK(t, tk_walk(t));
    g_product_reads = 0;
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked && hit.obj == button);
    lv_indev_get_point(indev, &where);
    CHECK(t, where.x == TK_W / 2 && where.y == TK_H / 2);
    CHECK_EQ_I64(t, g_product_reads, 0);
    CHECK(t, g_user_data_ok); /* the product's handler saw its own user data during the tap */
    CHECK(t, lv_indev_get_read_cb(indev) == product_read);
    CHECK(t, lv_indev_get_user_data(indev) == &g_marker);
    lvprobe_close(&tk_probe);
    CHECK(t, lv_indev_get_read_cb(indev) == product_read);
    lv_indev_delete(indev);
    lv_display_delete(disp);
    lv_deinit();
}

static int g_events;
static lv_obj_t *g_next;
static int g_mode;

static int g_hit_tests;

static void count_all(lv_event_t *e)
{
    (void)e;
    g_events++;
}

static void count_hit_test(lv_event_t *e)
{
    g_hit_tests += lv_event_get_code(e) == LV_EVENT_HIT_TEST ? 1 : 0;
}

/* The query agrees with the injected tap (F3b overlay, a disabled target) and sends no event. */
static void t_the_hit_query_agrees_with_the_tap_and_fires_nothing(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *button = button_at_centre();
    lv_obj_t *overlay = tk_ok(lv_obj_create(lv_screen_active()));
    lvprobe_hit_t hit;
    int32_t node = 0;
    lv_obj_t *obj = NULL;
    lv_obj_t *fancy = tk_box(lv_screen_active(), TK_W / 2 - 5, TK_H / 2 - 5, 10, 10, 0x00FF00u);
    lv_obj_set_size(overlay, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_opa(overlay, LV_OPA_TRANSP, 0);
    lv_obj_move_to_index(fancy, 0); /* under the overlay: the search asks it nothing */
    lv_obj_set_adv_hittest(overlay, true);
    (void)tk_ok(lv_obj_add_event_cb(overlay, count_hit_test, LV_EVENT_HIT_TEST, NULL));
    (void)tk_ok(lv_obj_add_event_cb(overlay, count_all, LV_EVENT_ALL, NULL));
    (void)tk_ok(lv_obj_add_event_cb(button, count_all, LV_EVENT_ALL, NULL));
    (void)tk_ok(lv_obj_add_event_cb(lv_screen_active(), count_all, LV_EVENT_ALL, NULL));
    CHECK(t, tk_walk(t));
    g_events = 0;
    g_hit_tests = 0;
    CHECK_EQ_I64(t, lvprobe_hit_test(&tk_probe, TK_W / 2, TK_H / 2, &node, &obj), LVPROBE_OK);
    CHECK_EQ_I64(t, g_events, g_hit_tests); /* only LVGL's own LV_EVENT_HIT_TEST to the ADV_HITTEST overlay */
    CHECK(t, g_hit_tests > 0);
    CHECK(t, obj == overlay && node == tk_index(overlay));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed_obj == obj && hit.obj == obj);
    lv_obj_set_clickable(overlay, false);
    lv_obj_add_state(button, LV_STATE_DISABLED);
    CHECK(t, tk_walk(t));
    g_events = 0;
    CHECK_EQ_I64(t, lvprobe_hit_test(&tk_probe, TK_W / 2, TK_H / 2, &node, &obj), LVPROBE_OK);
    CHECK_EQ_I64(t, g_events, 0);
    CHECK(t, obj == button && node == tk_index(button));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed_obj == obj && !hit.clicked);
    CHECK_EQ_I64(t, lvprobe_hit_test(&tk_probe, -1, 0, &node, &obj), LVPROBE_ERR_ARG);
    tk_stop(t, disp);
}

/* A product PRESSED handler that starts a screen-load animation (mode 1) or asks to wait for the release (mode 2). */
static void hold_on_press(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_PRESSED) {
        return;
    }
    if (g_mode == 1) {
        lv_screen_load_anim(g_next, LV_SCREEN_LOAD_ANIM_FADE_IN, 300, 0, false);
        lv_anim_refr_now();
    } else if (g_mode == 2) {
        lv_indev_wait_release(lv_indev_active());
    }
}

static void t_a_release_lvgl_did_not_process_is_blocked(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *button = button_at_centre();
    lvprobe_hit_t hit;
    int mode;
    (void)tk_ok(lv_obj_add_event_cb(button, hold_on_press, LV_EVENT_PRESSED, NULL));
    for (mode = 1; mode <= 2; mode++) {
        g_mode = mode;
        g_next = tk_ok(lv_obj_create(NULL));
        CHECK(t, tk_walk(t));
        g_clicks = 0;
        /* mode 1: the release is never processed (prev_scr); mode 2: LVGL processes it and drops the click */
        CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), mode == 1 ? LVPROBE_ERR_BLOCKED : LVPROBE_OK);
        CHECK(t, hit.pressed && hit.pressed_obj == button && !hit.clicked);
        CHECK_EQ_I64(t, g_clicks, 0);
        CHECK(t, !lv_obj_has_state(button, LV_STATE_PRESSED));
        CHECK_EQ_I64(t, lv_indev_get_state(tk_probe.cfg.indev), LV_INDEV_STATE_RELEASED);
        if (mode == 1) {
            lv_anim_delete_all();
            lv_screen_load(lv_obj_get_screen(button));
        }
    }
    g_mode = 0;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked && hit.obj == button);
    tk_stop(t, disp);
}

CTEST_SUITE("lvprobe_hit",
            { "a_transparent_clickable_overlay_steals_the_tap", t_a_transparent_clickable_overlay_steals_the_tap },
            { "a_disabled_target_is_pressed_but_not_clicked", t_a_disabled_target_is_pressed_but_not_clicked },
            { "three_taps_are_three_single_clicks", t_three_taps_are_three_single_clicks },
            { "a_point_outside_the_display_is_refused", t_a_point_outside_the_display_is_refused },
            { "a_tap_during_a_screen_load_animation_is_blocked", t_a_tap_during_a_screen_load_animation_is_blocked },
            { "taps_go_through_the_products_indev", t_taps_go_through_the_products_indev },
            { "the_hit_query_agrees_with_the_tap_and_fires_nothing", t_the_hit_query_agrees_with_the_tap_and_fires_nothing },
            { "a_release_lvgl_did_not_process_is_blocked", t_a_release_lvgl_did_not_process_is_blocked })
