/* gate//ui/lvprobe through its public header: observing a tap the product delivers to its own pointer indev (U05c).
 * The "product" here is the test: its indev reads a sample it sets, and it calls lv_indev_read itself, as a host loop
 * does. The probe injects nothing and must leave the indev as it found it. */
#include "ui/lvprobe/tests/testkit.h"

static lv_point_t g_at;
static bool g_down;
static int g_clicks;
static int g_mode;
static lv_obj_t *g_next;

static void product_read(lv_indev_t *indev, lv_indev_data_t *data)
{
    (void)indev;
    data->point = g_at;
    data->state = g_down ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

/* What a host does with one queued sample: set it and let LVGL read the indev once. */
static void deliver(lv_indev_t *indev, int32_t x, int32_t y, bool down)
{
    g_at.x = x;
    g_at.y = y;
    g_down = down;
    lv_indev_read(indev);
}

static void product_tap(lv_indev_t *indev, int32_t x, int32_t y)
{
    deliver(indev, x, y, true);
    deliver(indev, x, y, false);
}

static void count_clicks(lv_event_t *e)
{
    g_clicks += lv_event_get_code(e) == LV_EVENT_CLICKED ? 1 : 0;
}

/* A press handler that starts a screen-load animation (mode 1) or asks to wait for the release (mode 2). */
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

/* The kit's display and probe, reopened on a product pointer indev (event mode, the host reads it). */
static lv_indev_t *start_with_indev(ctest_t *t, lv_display_t **disp)
{
    lv_indev_t *indev;
    lvprobe_config_t cfg = tk_config();
    *disp = tk_start(t);
    indev = tk_ok(lv_indev_create());
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, product_read);
    lv_indev_set_display(indev, *disp);
    lv_indev_set_mode(indev, LV_INDEV_MODE_EVENT);
    lvprobe_close(&tk_probe);
    cfg.indev = indev;
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, *disp, &cfg), LVPROBE_OK);
    g_clicks = 0;
    g_mode = 0;
    return indev;
}

static lv_obj_t *button_at_centre(void)
{
    lv_obj_t *button = tk_ok(lv_button_create(lv_screen_active()));
    lv_obj_set_size(button, 100, 50);
    lv_obj_center(button);
    (void)tk_ok(lv_obj_add_event_cb(button, count_clicks, LV_EVENT_CLICKED, NULL));
    return button;
}

static void stop(ctest_t *t, lv_display_t *disp, lv_indev_t *indev)
{
    lvprobe_close(&tk_probe);
    if (indev != NULL) {
        lv_indev_delete(indev);
    }
    tk_stop(t, disp);
}

static void t_the_products_own_tap_is_observed_and_nothing_is_left_behind(ctest_t *t)
{
    lv_display_t *disp = NULL;
    lv_indev_t *indev = start_with_indev(t, &disp);
    lv_obj_t *button = button_at_centre();
    lvprobe_hit_t hit;
    uint32_t events = 0;
    size_t pool = 0;
    CHECK(t, tk_walk(t));
    events = lv_indev_get_event_count(indev);
    pool = tk_pool_used();
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    CHECK_EQ_I64(t, lv_indev_get_event_count(indev), events); /* nothing added */
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_OK); /* no sample: nothing named */
    CHECK(t, !hit.pressed && !hit.clicked && hit.pressed_node == LVPROBE_NONE && hit.node == LVPROBE_NONE);
    CHECK_EQ_I64(t, (int64_t)tk_pool_used(), (int64_t)pool); /* nothing allocated */
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == button && hit.pressed_node == tk_index(button));
    CHECK(t, hit.clicked && hit.obj == button && hit.node == tk_index(button));
    CHECK_EQ_I64(t, g_clicks, 1);
    CHECK_EQ_I64(t, lv_indev_get_event_count(indev), events);
    CHECK(t, lv_indev_get_read_cb(indev) == product_read); /* never replaced */
    CHECK_EQ_I64(t, lv_indev_get_state(indev), LV_INDEV_STATE_RELEASED);
    /* outside an observation the product's taps are not recorded, and an end without a begin is refused */
    product_tap(indev, 1, 1);
    CHECK_EQ_I64(t, g_clicks, 1);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_ERR_ARG);
    CHECK(t, hit.pressed_obj == button && hit.obj == button); /* untouched by the refused call */
    stop(t, disp, indev);
}

/* The F3b overlay takes the product's tap; a disabled target gets no LV_EVENT_PRESSED from LVGL, so it reads as none. */
static void t_an_overlay_takes_the_tap_and_a_disabled_target_sends_no_press(ctest_t *t)
{
    lv_display_t *disp = NULL;
    lv_indev_t *indev = start_with_indev(t, &disp);
    lv_obj_t *button = button_at_centre();
    lv_obj_t *overlay = tk_ok(lv_obj_create(lv_screen_active()));
    lvprobe_hit_t hit;
    lv_obj_set_size(overlay, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_opa(overlay, LV_OPA_TRANSP, 0);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == overlay && hit.pressed_node == tk_index(overlay));
    CHECK(t, hit.clicked && hit.obj == overlay && hit.node == tk_index(overlay));
    CHECK_EQ_I64(t, g_clicks, 0);
    lv_obj_set_clickable(overlay, false);
    lv_obj_add_state(button, LV_STATE_DISABLED);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_OK);
    CHECK(t, !hit.pressed && hit.pressed_obj == NULL && hit.pressed_node == LVPROBE_NONE);
    CHECK(t, !hit.clicked && hit.obj == NULL && hit.node == LVPROBE_NONE);
    CHECK_EQ_I64(t, g_clicks, 0);
    stop(t, disp, indev);
}

/* LVGL processes no press: the indev disabled, a screen-load animation running. The product's samples arrive and are
 * dropped by lv_indev_read; the observation says blocked. */
static void t_a_tap_lvgl_does_not_process_is_blocked(ctest_t *t)
{
    lv_display_t *disp = NULL;
    lv_indev_t *indev = start_with_indev(t, &disp);
    lvprobe_hit_t hit;
    lv_obj_t *button = button_at_centre();
    CHECK(t, tk_walk(t));
    lv_indev_enable(indev, false);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_ERR_BLOCKED);
    CHECK(t, !hit.pressed && !hit.clicked);
    lv_indev_enable(indev, true);
    /* blocked at the begin, but the product's own work ends the block before its samples: what LVGL did counts */
    lv_indev_enable(indev, false);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    lv_indev_enable(indev, true);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.clicked);
    g_next = tk_ok(lv_obj_create(NULL));
    CHECK(t, tk_walk(t));
    lv_screen_load_anim(g_next, LV_SCREEN_LOAD_ANIM_FADE_IN, 300, 0, false);
    lv_anim_refr_now(); /* prev_scr is set: lv_indev_read returns at once */
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_ERR_BLOCKED);
    CHECK(t, !hit.pressed && !hit.clicked);
    CHECK_EQ_I64(t, g_clicks, 1);
    lv_anim_delete_all();
    lv_screen_load(lv_obj_get_screen(button));
    stop(t, disp, indev);
}

/* A press handler starts a screen load (the release is never processed: blocked, and the indev stays as LVGL left it,
 * pressed) or asks to wait for the release (LVGL processes it and drops the click: pressed, not clicked). */
static void t_a_release_lvgl_did_not_process_is_blocked(ctest_t *t)
{
    lv_display_t *disp = NULL;
    lv_indev_t *indev = start_with_indev(t, &disp);
    lv_obj_t *button = button_at_centre();
    lvprobe_hit_t hit;
    (void)tk_ok(lv_obj_add_event_cb(button, hold_on_press, LV_EVENT_PRESSED, NULL));
    g_mode = 2;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == button && !hit.clicked);
    CHECK_EQ_I64(t, g_clicks, 0);
    g_mode = 1;
    g_next = tk_ok(lv_obj_create(NULL));
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_ERR_BLOCKED);
    CHECK(t, hit.pressed && hit.pressed_obj == button && !hit.clicked);
    CHECK_EQ_I64(t, lv_indev_get_state(indev), LV_INDEV_STATE_PRESSED); /* LVGL's state, not the probe's to undo */
    CHECK(t, lv_obj_has_state(button, LV_STATE_PRESSED));
    g_mode = 0;
    lv_anim_delete_all();
    lv_screen_load(lv_obj_get_screen(button));
    stop(t, disp, indev);
}

/* More than one press or click is not one tap; the probe never picks one of them. */
static void t_two_taps_are_not_one(ctest_t *t)
{
    lv_display_t *disp = NULL;
    lv_indev_t *indev = start_with_indev(t, &disp);
    lvprobe_hit_t hit;
    (void)button_at_centre();
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W / 2, TK_H / 2), LVPROBE_OK);
    product_tap(indev, TK_W / 2, TK_H / 2);
    product_tap(indev, TK_W / 2, TK_H / 2);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_ERR_UNSTABLE);
    CHECK_EQ_I64(t, g_clicks, 2);
    stop(t, disp, indev);
}

static void t_the_preconditions_are_checked(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_indev_t *indev = NULL;
    lvprobe_hit_t hit;
    lv_obj_t *box = NULL;
    CHECK(t, tk_walk(t));
    /* the kit's probe created its own indev: there is no tap of the product's to observe */
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 10, 10), LVPROBE_ERR_FORMAT);
    tk_stop(t, disp);
    indev = start_with_indev(t, &disp);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, -1, 10), LVPROBE_ERR_ARG);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, TK_W, 10), LVPROBE_ERR_ARG);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 10, TK_H), LVPROBE_ERR_ARG);
    CHECK_EQ_I64(t, lvprobe_observe_begin(NULL, 10, 10), LVPROBE_ERR_ARG);
    box = tk_box(lv_screen_active(), 0, 0, 10, 10, 0xFF0000u); /* created after the walk */
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 10, 10), LVPROBE_ERR_STALE);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 20, 20), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 20, 20), LVPROBE_ERR_ARG);   /* already observing */
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, 20, 20, &hit), LVPROBE_ERR_ARG);       /* no injection meanwhile */
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, NULL), LVPROBE_ERR_ARG);
    product_tap(indev, 20, 20); /* beside the box: the screen takes it */
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_OK);
    CHECK(t, hit.pressed && hit.pressed_obj == lv_screen_active() && hit.clicked && hit.obj == lv_screen_active());
    CHECK(t, hit.node == tk_index(lv_screen_active()) && tk_index(box) != 0xFFFFu);
    /* a product that removes every callback of its indev removes the probe's listener: refused, never a silent tap */
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 20, 20), LVPROBE_OK);
    CHECK(t, lv_indev_remove_event(indev, 0));
    CHECK_EQ_I64(t, lv_indev_get_event_count(indev), 0);
    product_tap(indev, 20, 20);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_ERR_LVGL);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 20, 20), LVPROBE_ERR_LVGL);
    stop(t, disp, indev);
}

/* An observation left open is ended by close (the callback removed); a product that deletes its indev during the tap
 * makes the end GONE, and the probe touches that indev no more (close included). */
static void t_close_and_a_deleted_indev_leave_nothing(ctest_t *t)
{
    lv_display_t *disp = NULL;
    lv_indev_t *indev = start_with_indev(t, &disp);
    lvprobe_hit_t hit;
    lvprobe_config_t cfg = tk_config();
    uint32_t events = 0;
    CHECK(t, tk_walk(t));
    events = lv_indev_get_event_count(indev);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 5, 5), LVPROBE_OK);
    lvprobe_close(&tk_probe);
    CHECK_EQ_I64(t, lv_indev_get_event_count(indev), events - 1u); /* the probe's listener, and nothing else */
    cfg.indev = indev;
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, &cfg), LVPROBE_OK);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 5, 5), LVPROBE_OK);
    lv_indev_delete(indev);
    CHECK_EQ_I64(t, lvprobe_observe_end(&tk_probe, &hit), LVPROBE_ERR_GONE);
    CHECK_EQ_I64(t, lvprobe_observe_begin(&tk_probe, 5, 5), LVPROBE_ERR_ARG); /* no indev any more */
    stop(t, disp, NULL);
}

CTEST_SUITE("lvprobe_observe",
            { "the_products_own_tap_is_observed_and_nothing_is_left_behind",
              t_the_products_own_tap_is_observed_and_nothing_is_left_behind },
            { "an_overlay_takes_the_tap_and_a_disabled_target_sends_no_press",
              t_an_overlay_takes_the_tap_and_a_disabled_target_sends_no_press },
            { "a_tap_lvgl_does_not_process_is_blocked", t_a_tap_lvgl_does_not_process_is_blocked },
            { "a_release_lvgl_did_not_process_is_blocked", t_a_release_lvgl_did_not_process_is_blocked },
            { "two_taps_are_not_one", t_two_taps_are_not_one },
            { "the_preconditions_are_checked", t_the_preconditions_are_checked },
            { "close_and_a_deleted_indev_leave_nothing", t_close_and_a_deleted_indev_leave_nothing })
