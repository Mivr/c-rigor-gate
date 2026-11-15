#include "selftest/ui_canary_product/canary.h"

#include <stddef.h>

#include "lvgl_gate.h"

/* The variants (the intent that selects each, docs/ui-judges.md "Canaries"). */
enum { V_CLEAN, V_OCCLUDED, V_OVERLAY, V_SMALL, V_SPACING, V_BOUNDS, V_OVERLAP, V_FONT, V_HIERARCHY, V_RAW, V_WRAP,
       V_OVERFLOW, V_CLIPPED, V_DOTS, V_UNMEASURABLE, V_GLYPH, V_UNMATCHED };
enum { N_TITLE, N_BODY, N_OK, N_BACK };

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(CANARY_W, CANARY_H)];
static lv_draw_buf_t g_draw_buf;
static lv_display_t *g_disp;
static canary_node_t g_nodes[CANARY_NODES];
static unsigned g_count;
static unsigned g_variant;

/* The title of each variant: every state has its own abstraction key (the key reads the scene only, and two variants
 * differ only in how they are drawn). */
static const char *const g_titles[CANARY_VARIANTS] = {
    "Canary", "Canary 1", "Canary 2", "Canary 3", "Canary 4", "Canary 5", "Canary 6", "Canary 7", "Canary 8",
    "Canary 9", "Canary 10", "Canary 11", "Canary 12", "Canary 13", "Canary 14", "Canary 15", "Canary 16",
};

/* The clean scene: a title, a body text and two buttons, every rect in display pixels. */
static const canary_node_t g_base[] = {
    {"title", "title", "Canary", 8, 8, 200, 24, "-", "title", "1", "-", "default", CANARY_LABEL},
    {"body", "body", "All clear", 8, 40, 200, 24, "-", "body", "2", "-", "default", CANARY_LABEL},
    {"ok", "key_label", "OK", 8, 100, 100, 50, "100:0", "btn", "2", "-", "single_line", CANARY_BUTTON},
    {"back", "key_label", "Back", 200, 100, 100, 50, "101:0", "btn", "2", "-", "single_line", CANARY_BUTTON},
};

static void add(canary_node_t node)
{
    if (g_count < CANARY_NODES) {
        g_nodes[g_count] = node;
        g_count++;
    }
}

/* The scene table of a variant: the clean scene with exactly one change. */
static void scene_of(unsigned v)
{
    static const canary_node_t cover = {"cover", "panel", "", 60, 90, 80, 70, "-", "-", "-", "-", "-", CANARY_PANEL};
    static const canary_node_t veil = {"veil", "layer", "", 0, 90, 160, 70, "-", "-", "-", "modal", "-", CANARY_LAYER};
    static const canary_node_t edge = {"edge", "panel", "", 280, 200, 80, 30, "-", "-", "-", "-", "-", CANARY_PANEL};
    static const canary_node_t ghost = {"ghost", "panel", "", 250, 8, 40, 40, "-", "-", "-", "-", "-", CANARY_GHOST};
    unsigned i;
    g_count = 0;
    for (i = 0; i < sizeof g_base / sizeof g_base[0]; i++) {
        add(g_base[i]);
    }
    g_nodes[N_TITLE].text = g_titles[v];
    g_nodes[N_OK].h = v == V_SMALL ? 30 : g_nodes[N_OK].h;
    g_nodes[N_BACK].x = v == V_SPACING ? 108 : g_nodes[N_BACK].x;
    g_nodes[N_BODY].y = v == V_OVERLAP ? 20 : g_nodes[N_BODY].y;
    g_nodes[N_BODY].style = v == V_FONT ? "caption" : v == V_HIERARCHY ? "headline" : g_nodes[N_BODY].style;
    g_nodes[N_BODY].text = v == V_RAW ? "" : v == V_OVERFLOW ? "Body text that is long" : v == V_DOTS ? "Body text that is long"
                           : v == V_GLYPH ? "\xd0\x99" : g_nodes[N_BODY].text;
    g_nodes[N_BODY].wrap = v == V_WRAP ? "-" : v == V_OVERFLOW ? "single_line" : g_nodes[N_BODY].wrap;
    g_nodes[N_BODY].w = v == V_OVERFLOW ? 100 : v == V_DOTS ? 60 : g_nodes[N_BODY].w;
    g_nodes[N_BODY].h = v == V_OVERFLOW ? 40 : v == V_DOTS ? 16 : g_nodes[N_BODY].h;
    if (v == V_OCCLUDED) {
        add(cover);
    } else if (v == V_OVERLAY) {
        add(veil);
    } else if (v == V_BOUNDS) {
        add(edge);
    } else if (v == V_UNMATCHED) {
        add(ghost);
    }
}

static lv_obj_t *place(lv_obj_t *obj, const canary_node_t *n)
{
    lv_obj_set_pos(obj, n->x, n->y);
    lv_obj_set_size(obj, n->w, n->h);
    return obj;
}

static void build_label(lv_obj_t *screen, const canary_node_t *n)
{
    lv_obj_t *label = place(lv_label_create(screen), n);
    lv_label_set_text(label, n->text);
    if (g_variant == V_DOTS && n == &g_nodes[N_BODY]) {
        lv_label_set_long_mode(label, LV_LABEL_LONG_MODE_DOTS);
    }
    if (g_variant == V_UNMEASURABLE && n == &g_nodes[N_BODY]) {
        lv_obj_set_style_drop_shadow_opa(label, LV_OPA_COVER, 0);   /* drawn through a sub-layer: not measured */
        lv_obj_set_style_drop_shadow_radius(label, 4, 0);
    }
}

static void build_button(lv_obj_t *screen, const canary_node_t *n)
{
    lv_obj_t *button = place(lv_button_create(screen), n);
    lv_obj_t *label = lv_label_create(button);
    lv_label_set_text(label, n->text);
    if (g_variant == V_CLIPPED && n == &g_nodes[N_OK]) {
        lv_obj_align(label, LV_ALIGN_BOTTOM_MID, 0, 22);   /* below the button's bottom edge: the button clips it */
    } else {
        lv_obj_center(label);
    }
}

static void build_panel(lv_obj_t *screen, const canary_node_t *n)
{
    lv_obj_t *panel = place(lv_obj_create(screen), n);
    lv_obj_remove_style_all(panel);
    lv_obj_set_pos(panel, n->x, n->y);
    lv_obj_set_size(panel, n->w, n->h);
    if (n->kind == CANARY_PANEL) {
        lv_obj_set_style_bg_color(panel, lv_color_hex(0x404040u), 0);
        lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
        lv_obj_set_clickable(panel, false);
    } else {
        lv_obj_set_clickable(panel, true);     /* a transparent layer that takes taps */
    }
}

static void build(void)
{
    lv_obj_t *screen = lv_screen_active();
    unsigned i;
    lv_obj_clean(screen);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0xFFFFFFu), 0);
    lv_obj_set_scrollable(screen, false);
    for (i = 0; i < g_count; i++) {
        const canary_node_t *n = &g_nodes[i];
        if (n->kind == CANARY_LABEL) {
            build_label(screen, n);
        } else if (n->kind == CANARY_BUTTON) {
            build_button(screen, n);
        } else if (n->kind != CANARY_GHOST) {
            build_panel(screen, n);
        }
    }
}

bool canary_show(unsigned v)
{
    if (v >= CANARY_VARIANTS || g_disp == NULL) {
        return false;
    }
    g_variant = v;
    scene_of(v);
    build();
    canary_draw();
    return true;
}

static void stop(void)
{
    if (g_disp != NULL) {
        lv_display_delete(g_disp);
        lv_deinit();
        g_disp = NULL;
    }
}

bool canary_start(void)
{
    stop();
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    g_disp = lvgl_gate_test_display_create(CANARY_W, CANARY_H, g_frame, sizeof g_frame, &g_draw_buf);
    if (g_disp == NULL) {
        return false;
    }
    return canary_show(V_CLEAN);
}

lv_display_t *canary_display(void)
{
    return g_disp;
}

unsigned canary_count(void)
{
    return g_count;
}

bool canary_node(unsigned i, canary_node_t *out)
{
    if (i >= g_count) {
        return false;
    }
    *out = g_nodes[i];
    return true;
}

void canary_step(uint32_t ms)
{
    lv_tick_inc(ms);
    (void)lv_timer_handler();
}

void canary_draw(void)
{
    lv_refr_now(g_disp);
}
