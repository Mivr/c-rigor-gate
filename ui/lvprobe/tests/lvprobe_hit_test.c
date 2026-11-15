/* gate//ui/lvprobe through its public header: hit injection through LVGL's pointer indev (U02). */
#include "ui/lvprobe/tests/testkit.h"

static int g_clicks;
static int g_singles;
static int g_doubles;
static int g_triples;
static int g_marker;
static int g_product_reads;

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
    lv_obj_t *button = lv_button_create(lv_screen_active());
    lv_obj_set_size(button, 100, 50);
    lv_obj_center(button);
    lv_obj_add_event_cb(button, count_clicks, LV_EVENT_ALL, NULL);
    return button;
}

static void t_a_transparent_clickable_overlay_steals_the_tap(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *button = button_at_centre();
    lv_obj_t *overlay = lv_obj_create(lv_screen_active());
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
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == button);
    CHECK(t, hit.clicked && hit.obj == button);
    CHECK_EQ_I64(t, hit.node, tk_index(button));
    CHECK_EQ_I64(t, g_clicks, 1);
    tk_stop(disp);
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
    tk_stop(disp);
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
    tk_stop(disp);
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
    tk_stop(disp);
}

static void t_a_tap_during_a_screen_load_animation_is_blocked(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *next;
    lvprobe_hit_t hit;
    (void)button_at_centre();
    CHECK(t, tk_walk(t));
    next = lv_obj_create(NULL);
    lv_screen_load_anim(next, LV_SCREEN_LOAD_ANIM_FADE_IN, 300, 0, false);
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_ERR_BLOCKED);
    CHECK_EQ_I64(t, g_clicks, 0);
    tk_stop(disp);
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
    lv_indev_t *indev = lv_indev_create();
    lv_obj_t *button;
    lvprobe_hit_t hit;
    lv_point_t where = {0, 0};
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, product_read);
    lv_indev_set_user_data(indev, &g_marker);
    lv_indev_set_display(indev, disp);
    lvprobe_close(&tk_probe);
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, indev, tk_scratch, (size_t)TK_W * TK_H), LVPROBE_OK);
    button = button_at_centre();
    CHECK(t, tk_walk(t));
    g_product_reads = 0;
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, TK_W / 2, TK_H / 2, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked && hit.obj == button);
    lv_indev_get_point(indev, &where);
    CHECK(t, where.x == TK_W / 2 && where.y == TK_H / 2);
    CHECK_EQ_I64(t, g_product_reads, 0);
    CHECK(t, lv_indev_get_read_cb(indev) == product_read);
    CHECK(t, lv_indev_get_user_data(indev) == &g_marker);
    lvprobe_close(&tk_probe);
    CHECK(t, lv_indev_get_read_cb(indev) == product_read);
    lv_indev_delete(indev);
    lv_display_delete(disp);
    lv_deinit();
}

CTEST_SUITE("lvprobe_hit",
            { "a_transparent_clickable_overlay_steals_the_tap", t_a_transparent_clickable_overlay_steals_the_tap },
            { "a_disabled_target_is_pressed_but_not_clicked", t_a_disabled_target_is_pressed_but_not_clicked },
            { "three_taps_are_three_single_clicks", t_three_taps_are_three_single_clicks },
            { "a_point_outside_the_display_is_refused", t_a_point_outside_the_display_is_refused },
            { "a_tap_during_a_screen_load_animation_is_blocked", t_a_tap_during_a_screen_load_animation_is_blocked },
            { "taps_go_through_the_products_indev", t_taps_go_through_the_products_indev })
