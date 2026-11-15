/* gate//ui/lvprobe through its public header: settling, the walk, node facts and every capacity limit (U02).
 * The label subclass is built with LVGL's class API (LVGL's private class structure), not with the probe's. */
#include "ui/lvprobe/tests/testkit.h"
#include "src/core/lv_obj_private.h"

#include "src/core/lv_obj_class_private.h"
#include "src/widgets/label/lv_label_private.h"

enum { MANY_OBJECTS = 520, DEEP = 33, LONG_TEXT = 1000, TEXTS = 17 };

static char g_long[LONG_TEXT + 1];
static lv_font_t g_fonts[LVPROBE_MAX_FONTS + 1];
static int g_flushes;

static const lv_obj_class_t g_my_label_class = {
    .base_class = &lv_label_class,
    .name = "my_label",
    .instance_size = sizeof(lv_label_t),
};

static void count_flush(lv_event_t *e)
{
    g_flushes += lv_event_get_code(e) == LV_EVENT_FLUSH_START ? 1 : 0;
}

static void t_the_walk_needs_a_settled_frame_and_flushes_nothing(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    bool flushed = false;
    if (disp == NULL) {
        return;
    }
    (void)tk_ok(lv_display_add_event_cb(disp, count_flush, LV_EVENT_FLUSH_START, NULL));
    (void)tk_label(lv_screen_active(), "AA", 10, 10);
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_ERR_UNSETTLED);
    CHECK_EQ_I64(t, lvprobe_settle(&tk_probe, &flushed), LVPROBE_OK);
    CHECK(t, flushed);
    CHECK_EQ_I64(t, lvprobe_settle(&tk_probe, &flushed), LVPROBE_OK);
    CHECK(t, !flushed);
    g_flushes = 0;
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, g_flushes, 0);
    CHECK_EQ_I64(t, lvprobe_settle(&tk_probe, &flushed), LVPROBE_OK);
    CHECK(t, !flushed);
    tk_stop(t, disp);
}

static void t_top_and_sys_layer_objects_are_walked(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *on_top = tk_box(lv_layer_top(), 1, 2, 3, 4, 0x00FF00u);
    lv_obj_t *on_sys = tk_label(lv_layer_sys(), "A", 5, 6);
    const lvprobe_node_t *a;
    const lvprobe_node_t *b;
    CHECK(t, tk_walk(t));
    a = tk_node(t, on_top);
    b = tk_node(t, on_sys);
    if (a != NULL && b != NULL) {
        CHECK_EQ_I64(t, a->parent, tk_index(lv_layer_top()));
        CHECK_EQ_I64(t, a->depth, 1);
        CHECK(t, tk_box_is(&a->coords, 1, 2, 3, 5));
        CHECK_EQ_I64(t, b->parent, tk_index(lv_layer_sys()));
        CHECK(t, b->is_label && b->drawn);
        CHECK(t, tk_index(lv_layer_bottom()) < tk_index(lv_screen_active()));
        CHECK(t, tk_index(lv_screen_active()) < tk_index(lv_layer_top()));
        CHECK(t, tk_index(lv_layer_top()) < tk_index(on_top) && tk_index(on_top) < tk_index(lv_layer_sys()));
    }
    tk_stop(t, disp);
}

static void t_bg_facts_are_what_is_drawn(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *faded = tk_box(lv_screen_active(), 0, 0, 50, 50, 0x123456u);
    lv_obj_t *child = tk_box(faded, 0, 0, 10, 10, 0x654321u);
    lv_obj_t *layered = tk_box(lv_screen_active(), 60, 0, 50, 50, 0x000000u);
    lv_obj_t *inner = tk_box(layered, 0, 0, 10, 10, 0x000000u);
    lv_obj_t *fancy = tk_box(lv_screen_active(), 120, 0, 50, 50, 0x000000u);
    const lvprobe_node_t *n;
    lv_obj_set_style_opa(faded, 128, 0);
    lv_obj_set_style_opa_layered(layered, 128, 0);
    lv_obj_set_style_bg_opa(inner, 128, 0);
    lv_obj_set_style_bg_grad_dir(fancy, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_bg_image_src(fancy, LV_SYMBOL_OK, 0);
    CHECK(t, tk_walk(t));
    n = tk_node(t, faded);
    CHECK(t, n != NULL && n->bg_rgb == 0x123456u && n->bg_opa == 255u && n->bg_opa_drawn == 127u);
    n = tk_node(t, child);
    CHECK(t, n != NULL && n->bg_rgb == 0x654321u && n->bg_opa_drawn == 127u);
    n = tk_node(t, layered); /* LVGL treats a factor at or above LV_OPA_MAX as opaque: 255 x 128 is 128 */
    CHECK(t, n != NULL && n->bg_opa_drawn == 128u);
    n = tk_node(t, inner);
    CHECK(t, n != NULL && n->bg_opa == 128u && n->bg_opa_drawn == 64u);
    n = tk_node(t, fancy);
    CHECK(t, n != NULL && n->bg_grad && n->bg_image);
    n = tk_node(t, layered);
    CHECK(t, n != NULL && !n->bg_grad && !n->bg_image);
    tk_stop(t, disp);
}

static void t_an_item_scrolled_out_has_its_scroll_context(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *list = tk_box(lv_screen_active(), 0, 100, 100, 50, 0xFFFFFFu);
    lv_obj_t *item = tk_box(list, 0, 60, 100, 20, 0xFF0000u);
    lv_obj_t *gone = tk_box(list, 0, 0, 100, 20, 0x00FF00u);
    lv_obj_t *plain = tk_box(lv_screen_active(), 200, 0, 10, 10, 0xFF0000u);
    const lvprobe_node_t *n;
    lv_obj_scroll_to_y(list, 30, LV_ANIM_OFF);
    CHECK(t, tk_walk(t));
    n = tk_node(t, item);
    if (n != NULL) {
        CHECK_EQ_I64(t, n->scroll, tk_index(list));
        CHECK_EQ_I64(t, n->scroll_x, 0);
        CHECK_EQ_I64(t, n->scroll_y, 30);
        CHECK(t, tk_box_is(&n->coords, 0, 130, 99, 149));
        CHECK_EQ_I64(t, n->clip, LVPROBE_NONE);
    }
    n = tk_node(t, gone);
    CHECK(t, n != NULL && n->scroll == tk_index(list) && n->scroll_y == 30 && n->clip == tk_index(list));
    CHECK(t, n != NULL && tk_box_is(&n->coords, 0, 70, 99, 89));
    n = tk_node(t, plain);
    CHECK(t, n != NULL && n->scroll == LVPROBE_NONE && n->scroll_y == 0);
    tk_stop(t, disp);
}

static void t_a_label_subclass_is_a_label(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *mine = tk_ok(lv_obj_class_create_obj(&g_my_label_class, lv_screen_active()));
    const lvprobe_node_t *n;
    lv_obj_class_init_obj(mine);
    lv_label_set_text(mine, "AA");
    lv_obj_set_style_text_font(mine, &tk_mono, 0);
    CHECK(t, tk_walk(t));
    n = tk_node(t, mine);
    CHECK(t, n != NULL && n->is_label && n->drawn && n->has_glyphs);
    if (n != NULL) {
        CHECK_EQ_STR(t, n->class_name, "my_label");
        CHECK_EQ_STR(t, n->text, "AA");
    }
    tk_stop(t, disp);
}

static void t_every_capacity_limit_is_an_error(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *parent = lv_screen_active();
    lv_obj_t *box;
    int i;
    uint16_t n = 0;
    uint32_t lost = 0;
    static lvprobe_life_t life[LVPROBE_DEFAULT_LIFE];
    for (i = 0; i <= LVPROBE_MAX_FONTS; i++) {
        g_fonts[i] = tk_mono;
        CHECK_EQ_I64(t, lvprobe_map_font(&tk_probe, &g_fonts[i], (uint16_t)i),
                     i < LVPROBE_MAX_FONTS ? LVPROBE_OK : LVPROBE_ERR_FULL);
    }
    for (i = 0; i < DEEP; i++) {
        parent = tk_box(parent, 0, 0, 10, 10, 0u);
    }
    CHECK(t, !tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_ERR_FULL);
    lv_obj_clean(lv_screen_active());
    for (i = 0; i < LONG_TEXT; i++) {
        g_long[i] = 'A';
    }
    for (i = 0; i < TEXTS; i++) {
        (void)tk_label(lv_screen_active(), g_long, 0, 0);
    }
    CHECK(t, !tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_ERR_FULL);
    lv_obj_clean(lv_screen_active());
    for (i = 0; i < MANY_OBJECTS; i++) {
        box = tk_box(lv_screen_active(), 0, 0, 1, 1, 0u);
        (void)box;
    }
    CHECK(t, !tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_ERR_FULL);
    CHECK_EQ_U64(t, lvprobe_count(&tk_probe), 0);
    lv_obj_clean(lv_screen_active());
    for (i = 0; i <= LVPROBE_DEFAULT_SCREENS; i++) {
        (void)tk_ok(lv_obj_create(NULL));
    }
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, life, LVPROBE_DEFAULT_LIFE, &n, &lost), LVPROBE_ERR_FULL);
    tk_stop(t, disp);
}

/* A label LVGL draws through a sub-layer (drop shadow) is unsupported on its own: the walk goes on, a sibling label is
 * still exact, and nothing in LVGL changes. */
static void t_a_label_with_a_drop_shadow_is_unsupported(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *label = tk_label(lv_screen_active(), "AA", 10, 10);
    lv_obj_t *sibling = tk_label(lv_screen_active(), "AA", 10, 40);
    const lvprobe_node_t *n;
    size_t pool;
    uint32_t layers;
    bool flushed = false;
    lv_obj_set_style_drop_shadow_opa(label, LV_OPA_COVER, 0);
    lv_obj_set_style_drop_shadow_radius(label, 4, 0);
    CHECK(t, tk_walk(t));
    pool = tk_pool_used();
    layers = tk_layer_count(disp);
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_OK);
    n = tk_node(t, label);
    CHECK(t, n != NULL && n->unsupported && !n->drawn && !n->has_glyphs && !n->clipped);
    n = tk_node(t, sibling);
    CHECK(t, n != NULL && !n->unsupported && n->drawn && tk_box_is(&n->glyphs, 11, 42, 28, 53));
    CHECK_EQ_U64(t, tk_pool_used(), pool);
    CHECK_EQ_U64(t, tk_layer_count(disp), layers);
    CHECK_EQ_I64(t, lvprobe_settle(&tk_probe, &flushed), LVPROBE_OK);
    CHECK(t, !flushed);
    tk_stop(t, disp);
}

/* The dry redraw leaves LVGL's `rendered` marks as they were, on the label and on its children (a label laid out but
 * never drawn stays unrendered). */
static void t_the_walk_does_not_mark_labels_rendered(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *label;
    lv_obj_t *child;
    const lvprobe_node_t *n;
    lv_display_enable_invalidation(disp, false);
    label = tk_label(lv_screen_active(), "AA", 10, 10);
    child = tk_box(label, 0, 0, 4, 4, 0x00FF00u);
    CHECK(t, tk_walk(t));
    CHECK_EQ_U64(t, label->rendered, 0);
    CHECK_EQ_U64(t, child->rendered, 0);
    n = tk_node(t, label);
    CHECK(t, n != NULL && n->drawn && n->has_glyphs);
    lv_display_enable_invalidation(disp, true);
    tk_stop(t, disp);
}

/* A rotated display: taps, the query and coords would disagree. */
static void t_a_rotated_display_is_a_format_error(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lvprobe_config_t cfg = tk_config();
    lvprobe_close(&tk_probe);
    lv_display_set_rotation(disp, LV_DISPLAY_ROTATION_90);
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, &cfg), LVPROBE_ERR_FORMAT);
    lv_display_set_rotation(disp, LV_DISPLAY_ROTATION_0);
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, &cfg), LVPROBE_OK);
    tk_stop(t, disp);
}

/* Reparenting, reordering and flag changes since the walk make it stale for ink, taps and the query. */
static void t_tree_changes_without_events_make_the_walk_stale(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *a = tk_box(lv_screen_active(), 10, 10, 20, 20, 0xFF0000u);
    lv_obj_t *b = tk_box(lv_screen_active(), 40, 10, 20, 20, 0x00FF00u);
    lvprobe_hit_t hit;
    int32_t node = 0;
    lv_obj_t *obj = NULL;
    CHECK(t, tk_walk(t));
    lv_obj_set_parent(a, b);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(b)), LVPROBE_ERR_STALE);
    lv_obj_set_parent(a, lv_screen_active());
    CHECK(t, tk_walk(t));
    lv_obj_move_to_index(a, 0);
    CHECK_EQ_I64(t, lvprobe_hit(&tk_probe, 15, 15, &hit), LVPROBE_ERR_STALE);
    CHECK(t, tk_walk(t));
    lv_obj_set_clickable(b, false); /* no LVGL event: found by comparing the walked flags at use time */
    CHECK_EQ_I64(t, lvprobe_hit_test(&tk_probe, 45, 15, &node, &obj), LVPROBE_ERR_STALE);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(b)), LVPROBE_ERR_STALE);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_hit_test(&tk_probe, 45, 15, &node, &obj), LVPROBE_OK);
    tk_stop(t, disp);
}

/* After a failed or stale walk the encoder refuses: a failed walk is no empty tree. */
static void t_the_encoder_refuses_a_failed_or_stale_walk(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    static char text[4096];
    size_t len = 7;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, text, sizeof text, &len), LVPROBE_OK);
    (void)tk_box(lv_screen_active(), 10, 10, 20, 20, 0xFF0000u);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, text, sizeof text, &len), LVPROBE_ERR_STALE);
    CHECK_EQ_I64(t, lvprobe_walk(&tk_probe), LVPROBE_ERR_UNSETTLED);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, text, sizeof text, &len), LVPROBE_ERR_STALE);
    CHECK_EQ_I64(t, lvprobe_encode_head(&tk_probe, text, sizeof text, &len), LVPROBE_ERR_STALE);
    CHECK_EQ_U64(t, len, 0);
    tk_stop(t, disp);
}

CTEST_SUITE("lvprobe_walk",
            { "the_walk_needs_a_settled_frame_and_flushes_nothing", t_the_walk_needs_a_settled_frame_and_flushes_nothing },
            { "top_and_sys_layer_objects_are_walked", t_top_and_sys_layer_objects_are_walked },
            { "bg_facts_are_what_is_drawn", t_bg_facts_are_what_is_drawn },
            { "an_item_scrolled_out_has_its_scroll_context", t_an_item_scrolled_out_has_its_scroll_context },
            { "a_label_subclass_is_a_label", t_a_label_subclass_is_a_label },
            { "every_capacity_limit_is_an_error", t_every_capacity_limit_is_an_error },
            { "a_label_with_a_drop_shadow_is_unsupported", t_a_label_with_a_drop_shadow_is_unsupported },
            { "the_walk_does_not_mark_labels_rendered", t_the_walk_does_not_mark_labels_rendered },
            { "a_rotated_display_is_a_format_error", t_a_rotated_display_is_a_format_error },
            { "tree_changes_without_events_make_the_walk_stale", t_tree_changes_without_events_make_the_walk_stale },
            { "the_encoder_refuses_a_failed_or_stale_walk", t_the_encoder_refuses_a_failed_or_stale_walk })
