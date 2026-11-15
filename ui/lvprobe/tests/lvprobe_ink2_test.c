/* gate//ui/lvprobe through its public header: ink when the product moves under it (U02 fix-up 3). */
#include "ui/lvprobe/tests/testkit.h"

#include "src/core/lv_obj_private.h"

enum { FLAT = 508 };

static lv_obj_t *g_victim;
static lv_obj_t *g_column;
static int g_armed;
static char g_text[16384];
static size_t g_len;

/* A product that deletes an object from a refresh handler (a toast deleting itself). */
static void delete_on_refresh(lv_event_t *e)
{
    if (g_armed > 0 && lv_event_get_code(e) == LV_EVENT_REFR_START && g_victim != NULL) {
        g_armed--;
        lv_obj_delete(g_victim);
        g_victim = NULL;
    }
}

static void t_a_node_deleted_during_ink_is_gone(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *toast = tk_box(lv_screen_active(), 10, 10, 30, 30, 0x000000u);
    uint16_t at;
    CHECK(t, tk_ok(lv_display_add_event_cb(disp, delete_on_refresh, LV_EVENT_REFR_START, NULL)) != NULL);
    CHECK(t, tk_walk(t));
    at = tk_index(toast);
    g_victim = toast;
    g_armed = 1;
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, at), LVPROBE_ERR_GONE);
    CHECK(t, g_victim == NULL && lvprobe_node(&tk_probe, at)->obj == NULL && !lvprobe_node(&tk_probe, at)->has_ink);
    tk_stop(t, disp);
}

static void hide_on_click(lv_event_t *e)
{
    if (lv_event_get_code(e) == LV_EVENT_CLICKED) {
        lv_obj_set_hidden(g_victim, true);
    }
}

/* The product hides a banner after the walk: ink refuses (STALE) and the banner stays hidden. */
static void t_ink_never_unhides_what_the_product_hid(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *button = tk_ok(lv_button_create(lv_screen_active()));
    lv_obj_t *banner = tk_box(lv_screen_active(), 150, 10, 100, 30, 0x000000u);
    lvprobe_hit_t hit;
    bool flushed = true;
    g_victim = banner;
    (void)tk_ok(lv_obj_add_event_cb(button, hide_on_click, LV_EVENT_CLICKED, NULL));
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, 5, 5, &hit), LVPROBE_OK);
    CHECK(t, hit.clicked && lv_obj_is_hidden(banner));
    CHECK_EQ_I64(t, lvprobe_settle(&tk_probe, &flushed), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(banner)), LVPROBE_ERR_STALE);
    CHECK(t, lv_obj_is_hidden(banner) && banner->hidden == 1u);
    tk_stop(t, disp);
}

/* Once, at the first refresh after arming: a product that marks a flex column for layout while ink measures. */
static void relayout_once(lv_event_t *e)
{
    if (g_armed > 0 && lv_event_get_code(e) == LV_EVENT_REFR_START) {
        g_armed--;
        lv_obj_mark_layout_as_dirty(g_column);
    }
}

static void t_siblings_are_back_after_an_unstable_ink(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *banner;
    lv_obj_t *below;
    lv_area_t before;
    lv_area_t after;
    g_column = tk_box(lv_screen_active(), 20, 20, 100, LV_SIZE_CONTENT, 0xFFFFFFu);
    lv_obj_set_flex_flow(g_column, LV_FLEX_FLOW_COLUMN);
    banner = tk_box(g_column, 0, 0, 100, 20, 0xFF0000u);
    below = tk_box(g_column, 0, 0, 100, 10, 0x0000FFu);
    CHECK(t, tk_ok(lv_display_add_event_cb(disp, relayout_once, LV_EVENT_REFR_START, NULL)) != NULL);
    CHECK(t, tk_walk(t));
    lv_obj_get_coords(below, &before);
    g_armed = 1;
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(banner)), LVPROBE_ERR_UNSTABLE);
    lv_obj_get_coords(below, &after);
    CHECK(t, tk_box_is(&after, before.x1, before.y1, before.x2, before.y2));
    CHECK(t, !lv_obj_is_hidden(banner) && banner->hidden == 0u);
    tk_stop(t, disp);
}

static void t_ink_is_refused_while_an_animation_runs(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 10, 10, 30, 30, 0x000000u);
    lv_anim_t a;
    CHECK(t, tk_walk(t));
    lv_anim_init(&a);
    lv_anim_set_var(&a, box);
    lv_anim_set_values(&a, 0, 100);
    lv_anim_set_duration(&a, 1000);
    lv_anim_set_exec_cb(&a, NULL);
    CHECK(t, tk_ok(lv_anim_start(&a)) != NULL);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(box)), LVPROBE_ERR_UNSTABLE);
    CHECK(t, tk_node(t, box)->unstable && box->hidden == 0u);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_text, sizeof g_text, &g_len), LVPROBE_OK);
    CHECK(t, tk_contains(g_text, g_len, "\nnoink\t"));
    CHECK(t, tk_contains(g_text, g_len, "\tunstable\n"));
    CHECK(t, lv_anim_delete(box, NULL));
    tk_stop(t, disp);
}

/* Hiding the last item of a scrollable list changes the list's scrollbar inside the item's box: not the item's ink.
 * A middle item changes no scrollbar and is measured. */
static void t_a_scrollbar_change_makes_ink_unstable(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *list = tk_box(lv_screen_active(), 10, 10, 120, 80, 0xFFFFFFu);
    lv_obj_t *mid = NULL;
    lv_obj_t *last;
    int i;
    lv_obj_set_scrollbar_mode(list, LV_SCROLLBAR_MODE_AUTO); /* drawn while the content overflows */
    lv_obj_set_style_width(list, 4, LV_PART_SCROLLBAR);
    lv_obj_set_style_bg_opa(list, LV_OPA_COVER, LV_PART_SCROLLBAR);
    lv_obj_set_style_bg_color(list, lv_color_hex(0x000000u), LV_PART_SCROLLBAR);
    (void)i;
    mid = tk_box(list, 0, 0, 100, 30, 0x0000FFu);
    last = tk_box(list, 0, 60, 120, 30, 0x0000FFu); /* the only overflow: without it there is no scrollbar */
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(mid)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(last)), LVPROBE_ERR_UNSTABLE);
    CHECK(t, tk_node(t, last)->unstable && !tk_node(t, mid)->unstable);
    tk_stop(t, disp);
}

static void t_a_transformed_node_is_not_inked(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *turned = tk_box(lv_screen_active(), 50, 50, 40, 20, 0x000000u);
    lv_obj_t *child = tk_box(turned, 0, 0, 10, 10, 0xFF0000u);
    static char text[8192];
    size_t len = 0;
    lv_obj_set_style_transform_rotation(turned, 300, 0);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(turned)), LVPROBE_ERR_UNSUPPORTED);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(child)), LVPROBE_ERR_UNSUPPORTED);
    CHECK(t, tk_node(t, child)->ink_unsupported && !tk_node(t, child)->has_ink);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, text, sizeof text, &len), LVPROBE_OK);
    CHECK(t, tk_contains(text, len, "\tunsupported") == false && tk_contains(text, len, "\ttransformed\n"));
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(lv_screen_active())), LVPROBE_ERR_ARG); /* a root: refused */
    tk_stop(t, disp);
}

/* An opaque cover hides a label LVGL never drew; inking the cover reveals it, and its `rendered` mark comes back. */
static void t_ink_restores_rendered_marks(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *label = tk_label(lv_screen_active(), "AA", 10, 10);
    lv_obj_t *cover;
    CHECK(t, tk_walk(t));
    label->rendered = 0; /* as if the cover had been there from the first frame */
    cover = tk_box(lv_screen_active(), 0, 0, 100, 60, 0x000000u);
    CHECK(t, tk_walk(t));
    label->rendered = 0;
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(cover)), LVPROBE_OK);
    CHECK_EQ_U64(t, tk_node(t, cover)->ink, 100u * 60u - 192u);
    CHECK_EQ_U64(t, label->rendered, 0);
    tk_stop(t, disp);
}

/* 512 nodes in one flat parent, every one inked: liveness is one traversal and a binary search per call. */
static void t_inking_512_nodes_is_not_quadratic(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    uint16_t i;
    uint32_t ok = 0;
    for (i = 0; i < FLAT; i++) {
        (void)tk_box(lv_screen_active(), (int32_t)(i % 64u) * 5, (int32_t)(i / 64u) * 5, 4, 4, 0x000000u);
    }
    CHECK(t, tk_walk(t));
    CHECK_EQ_U64(t, lvprobe_count(&tk_probe), LVPROBE_DEFAULT_NODES);
    for (i = 0; i < lvprobe_count(&tk_probe); i++) {
        if (lvprobe_node(&tk_probe, i)->parent != LVPROBE_NONE) {
            ok += lvprobe_ink(&tk_probe, i) == LVPROBE_OK ? 1u : 0u;
        }
    }
    CHECK_EQ_U64(t, ok, FLAT);
    CHECK_EQ_U64(t, lvprobe_node(&tk_probe, tk_index(lv_obj_get_child(lv_screen_active(), 0)))->ink, 16u);
    tk_stop(t, disp);
}

CTEST_SUITE("lvprobe_ink2", { "a_node_deleted_during_ink_is_gone", t_a_node_deleted_during_ink_is_gone },
            { "ink_never_unhides_what_the_product_hid", t_ink_never_unhides_what_the_product_hid },
            { "siblings_are_back_after_an_unstable_ink", t_siblings_are_back_after_an_unstable_ink },
            { "ink_is_refused_while_an_animation_runs", t_ink_is_refused_while_an_animation_runs },
            { "a_scrollbar_change_makes_ink_unstable", t_a_scrollbar_change_makes_ink_unstable },
            { "a_transformed_node_is_not_inked", t_a_transformed_node_is_not_inked },
            { "ink_restores_rendered_marks", t_ink_restores_rendered_marks },
            { "inking_512_nodes_is_not_quadratic", t_inking_512_nodes_is_not_quadratic })
