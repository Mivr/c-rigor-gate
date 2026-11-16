#include "selftest/ui_canary_product/canary.h"

#include <stddef.h>

#include "lvgl_gate.h"

/* The variants (the intent that selects each, docs/ui-judges.md "Canaries"). */
enum { V_CLEAN, V_OCCLUDED, V_OVERLAY, V_SMALL, V_SPACING, V_BOUNDS, V_OVERLAP, V_FONT, V_HIERARCHY, V_RAW, V_WRAP,
       V_OVERFLOW, V_CLIPPED, V_DOTS, V_UNMEASURABLE, V_GLYPH, V_UNMATCHED, V_TOGGLE, V_TEXT, V_SHRUNK, V_MODAL,
       V_FAKE_INERT, V_UNREACHABLE, V_WRAP_CONTRA,
       /* U07: one variant per check of the ui-render judge (docs/ui-judges-render.md, "Canaries") */
       V_INVISIBLE, V_CONTRAST, V_DISABLED, V_CLICK, V_HIDDEN, V_LONG, V_ALIGN, V_LINE, V_NOINK,
       /* U07 fix-up 1 */
       V_COVERED, V_BTN_TEXT, V_FILL };
enum { N_TITLE, N_BODY, N_OK, N_BACK, N_BG, N_EN };
/* Style tokens of canary.toml: title 1, body 2, caption 3, button 5, language on 6 / off 7, a small and a big body. */
enum { T_TITLE = 1, T_BODY = 2, T_CAPTION = 3, T_BUTTON = 5, T_LANG_ON = 6, T_LANG_OFF = 7, T_SMALL = 8, T_BIG = 9 };

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(CANARY_W, CANARY_H)];
static lv_draw_buf_t g_draw_buf;
static lv_display_t *g_disp;
static canary_node_t g_nodes[CANARY_NODES];
static unsigned g_count;
static unsigned g_variant;

/* A font of one glyph, `x` as a solid 6x8 box, with a line height of 10 px: smaller than every style's (V_SHRUNK). */
static const uint8_t g_bitmap[6] = {0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu};
static const lv_font_fmt_txt_glyph_dsc_t g_glyphs[] = {
    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 0, .adv_w = 112, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
};
static const lv_font_fmt_txt_cmap_t g_cmaps[] = {
    {.range_start = 0x78, .range_length = 1, .glyph_id_start = 1, .unicode_list = NULL, .glyph_id_ofs_list = NULL,
     .list_length = 0, .type = LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY},
};
static const lv_font_fmt_txt_dsc_t g_dsc = {
    .glyph_bitmap = g_bitmap, .glyph_dsc = g_glyphs, .cmaps = g_cmaps, .kern_dsc = NULL,
    .kern_scale = 0, .cmap_num = 1, .bpp = 1, .kern_classes = 0, .bitmap_format = 0,
};
static const lv_font_t g_font_small = {
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt, .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = 10, .base_line = 2, .subpx = LV_FONT_SUBPX_NONE, .static_bitmap = 1, .dsc = &g_dsc,
};
/* The same glyph with a line height of 20 px: larger than every style's 16 (V_LINE, U07). */
static const lv_font_t g_font_tall = {
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt, .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = 20, .base_line = 2, .subpx = LV_FONT_SUBPX_NONE, .static_bitmap = 1, .dsc = &g_dsc,
};

/* The title of each variant: every state has its own abstraction key (the key reads the scene only, and some variants
 * differ only in how they are drawn). */
static const char *const g_titles[CANARY_VARIANTS] = {
    "Canary", "Canary 1", "Canary 2", "Canary 3", "Canary 4", "Canary 5", "Canary 6", "Canary 7", "Canary 8",
    "Canary 9", "Canary 10", "Canary 11 title far too long for one line", "Canary 12", "Canary 13", "Canary 14",
    "Canary 15", "Canary 16", "Canary 17", "Canary 18", "Canary 19", "Canary 20", "Canary 21", "Canary 22",
    "Canary 23", "Canary 24", "Canary 25", "Canary 26", "Canary 27", "Canary 28", "Canary 29", "Canary 30",
    "Canary 31", "Canary 32", "Canary 33", "Canary 34", "Canary 35",
};

/* The clean scene: a title, a body text, two buttons and the BG/EN switch, every rect in display pixels. */
static const canary_node_t g_base[] = {
    {"title", "text", "Canary", 8, 8, 200, 24, "-", "-", T_TITLE, CANARY_LABEL, true, 0, false, false, NULL},
    {"body", "text", "All clear", 8, 40, 200, 24, "-", "-", T_BODY, CANARY_LABEL, true, 0, false, false, NULL},
    {"ok", "button", "OK", 8, 100, 100, 50, "100:0", "-", T_BUTTON, CANARY_BUTTON, true, 0, false, false, NULL},
    {"back", "button", "Back", 200, 100, 100, 50, "101:0", "-", T_BUTTON, CANARY_BUTTON, true, 0, false, false, NULL},
    {"lang_bg", "button", "BG", 216, 8, 48, 48, "8:0", "-", T_LANG_ON, CANARY_BUTTON, true, 0, false, false, NULL},
    {"lang_en", "button", "EN", 272, 8, 48, 48, "8:1", "-", T_LANG_OFF, CANARY_BUTTON, true, 0, false, false, NULL},
};
static const canary_node_t g_cover = {"cover", "panel", "", 60, 90, 80, 70, "-", "-", 0, CANARY_PANEL, true, 255,
                                      false, false, NULL};
static const canary_node_t g_veil = {"veil", "dialog", "", 0, 90, 160, 70, "-", "-", 0, CANARY_PANEL, true, 40, false,
                                     false, NULL};   /* a modal card that is not clickable: it shields nothing */
static const canary_node_t g_edge = {"edge", "panel", "", 280, 200, 80, 30, "-", "-", 0, CANARY_PANEL, true, 255,
                                     false, false, NULL};
static const canary_node_t g_ghost = {"ghost", "button", "", 250, 170, 60, 60, "102:0", "-", T_BUTTON, CANARY_GHOST,
                                      true, 0, false, false, NULL};
static const canary_node_t g_scrim = {"scrim", "scrim", "", 0, 0, 320, 240, "104:0", "-", 0, CANARY_PANEL, true, 82,
                                      true, false, NULL};   /* dimmed and clickable: the background is inert (R7) */
static const canary_node_t g_dialog = {"dialog", "dialog", "", 60, 60, 200, 120, "-", "-", 0, CANARY_PANEL, true,
                                       255, true, false, NULL};
static const canary_node_t g_close = {"close", "button", "Close", 100, 120, 100, 50, "103:0", "-", T_BUTTON,
                                      CANARY_BUTTON, true, 0, false, true, NULL};
static const canary_node_t g_blocker = {"blocker", "panel", "", 0, 0, 320, 240, "-", "I", 0, CANARY_PANEL, false, 0,
                                        false, false, NULL};   /* a bare inert panel: grants nothing */
static const canary_node_t g_bscrim = {"bscrim", "scrim", "", 120, 170, 200, 60, "105:0", "-", 0, CANARY_PANEL, true,
                                       0, true, false, NULL};
static const canary_node_t g_bcard = {"bcard", "banner", "", 120, 170, 200, 60, "-", "-", 0, CANARY_PANEL, true, 255,
                                      true, false, NULL};   /* the card has its scrim's rectangle: no tap reaches the scrim */

static void add(canary_node_t node)
{
    if (g_count < CANARY_NODES) {
        g_nodes[g_count] = node;
        g_count++;
    }
}

/* The body text's changes. */
static void body_of(unsigned v, canary_node_t *body)
{
    body->y = v == V_OVERLAP ? 20 : body->y;
    body->wrap = v == V_WRAP_CONTRA ? "single_line" : NULL;
    body->token = v == V_FONT ? T_SMALL : v == V_HIERARCHY ? T_BIG : v == V_WRAP ? T_CAPTION : body->token;
    body->text = v == V_RAW ? "" : v == V_DOTS ? "Body text that is long" : v == V_GLYPH ? "\xd0\x99"
                 : v == V_SHRUNK || v == V_LINE ? "xx" : body->text;
    body->w = v == V_DOTS ? 60 : body->w;
    body->h = v == V_DOTS ? 16 : body->h;
}

/* The scene table of a variant: the clean scene with exactly one change. */
static void scene_of(unsigned v)
{
    unsigned i;
    g_count = 0;
    for (i = 0; i < sizeof g_base / sizeof g_base[0]; i++) {
        add(g_base[i]);
    }
    g_nodes[N_TITLE].text = g_titles[v];
    g_nodes[N_TITLE].h = v == V_OVERFLOW ? 32 : g_nodes[N_TITLE].h;
    g_nodes[N_OK].h = v == V_SMALL ? 30 : g_nodes[N_OK].h;
    g_nodes[N_BACK].x = v == V_SPACING ? 108 : g_nodes[N_BACK].x;
    g_nodes[N_BACK].enabled = v != V_DISABLED;                  /* disabled in the scene, still clickable in LVGL */
    g_nodes[N_BACK].flags = v == V_DISABLED ? "D" : g_nodes[N_BACK].flags;
    body_of(v, &g_nodes[N_BODY]);
    if (v == V_OCCLUDED) {
        add(g_cover);
    } else if (v == V_OVERLAY) {
        add(g_veil);
    } else if (v == V_BOUNDS) {
        add(g_edge);
    } else if (v == V_UNMATCHED) {
        add(g_ghost);
    } else if (v == V_MODAL) {
        add(g_scrim);
        add(g_dialog);
        add(g_close);
    } else if (v == V_FAKE_INERT) {
        add(g_cover);
        add(g_blocker);
    } else if (v == V_UNREACHABLE) {
        add(g_bscrim);
        add(g_bcard);
    }
}

/* Positions `obj` at the node's rect in display pixels, inside a parent whose top left corner is at (ox, oy). */
static lv_obj_t *place(lv_obj_t *obj, const canary_node_t *n, int32_t ox, int32_t oy)
{
    lv_obj_set_pos(obj, n->x - ox, n->y - oy);
    lv_obj_set_size(obj, n->w, n->h);
    return obj;
}

/* U07: the body label's defect of each ui-render variant. */
static void render_defect(lv_obj_t *label)
{
    if (g_variant == V_INVISIBLE) {
        lv_obj_set_style_text_opa(label, LV_OPA_TRANSP, 0);   /* a text that paints no pixel */
    } else if (g_variant == V_CONTRAST) {
        lv_obj_set_style_text_color(label, lv_color_hex(0xBBBBBBu), 0);   /* light grey on white: 1.9:1 */
    } else if (g_variant == V_CLICK) {
        lv_obj_set_clickable(label, true);   /* a text without an intent that takes taps */
    } else if (g_variant == V_HIDDEN) {
        lv_obj_set_hidden(label, true);      /* hidden in LVGL, shown in the scene */
    } else if (g_variant == V_LONG) {
        lv_label_set_long_mode(label, LV_LABEL_LONG_MODE_CLIP);  /* the scope `default` wraps */
    } else if (g_variant == V_ALIGN) {
        lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_LEFT, 0);   /* the role's alignment is centre */
    } else if (g_variant == V_LINE) {
        lv_obj_set_style_text_font(label, &g_font_tall, 0);
    } else if (g_variant == V_FILL) {   /* #222 text on the label's own opaque #000 fill: 1.3:1 */
        lv_obj_set_style_bg_color(label, lv_color_hex(0x000000u), 0);
        lv_obj_set_style_bg_opa(label, LV_OPA_COVER, 0);
        lv_obj_set_style_text_color(label, lv_color_hex(0x222222u), 0);
    }
}

static void build_label(lv_obj_t *screen, const canary_node_t *n)
{
    lv_obj_t *label = place(lv_label_create(screen), n, 0, 0);
    bool body = n == &g_nodes[N_BODY];
    lv_label_set_text(label, body && g_variant == V_TEXT ? "All clean" : n->text);   /* V_TEXT: another text drawn */
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);   /* every role of canary.toml is centred (U07) */
    if (body && g_variant == V_DOTS) {
        lv_label_set_long_mode(label, LV_LABEL_LONG_MODE_DOTS);
    }
    if (body && g_variant == V_SHRUNK) {
        lv_obj_set_style_text_font(label, &g_font_small, 0);
    }
    if (body && g_variant == V_UNMEASURABLE) {
        lv_obj_set_style_drop_shadow_opa(label, LV_OPA_COVER, 0);   /* drawn through a sub-layer: not measured */
        lv_obj_set_style_drop_shadow_radius(label, 4, 0);
    }
    if (body) {
        render_defect(label);
    }
}

static void build_button(lv_obj_t *parent, const canary_node_t *n, int32_t ox, int32_t oy)
{
    lv_obj_t *button = place(lv_button_create(parent), n, ox, oy);
    lv_obj_t *label = lv_label_create(button);
    bool on = n->token == T_LANG_ON || (g_variant == V_TOGGLE && n == &g_nodes[N_EN]);
    lv_label_set_text(label, n->text);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    if (n->token == T_LANG_ON || n->token == T_LANG_OFF) {
        lv_obj_set_style_bg_color(button, lv_color_hex(on ? 0x2B4678u : 0x282A2Fu), 0);   /* the selection's fill */
    } else {
        lv_obj_set_style_bg_color(button, lv_color_hex(0x0D47A1u), 0);   /* white text on it: 8.6:1 (U07) */
    }
    if (g_variant == V_BTN_TEXT && n == &g_nodes[N_OK]) {
        lv_obj_set_style_text_opa(label, LV_OPA_TRANSP, 0);   /* the button's fill paints, its label nothing */
    }
    if (g_variant == V_NOINK && n == &g_nodes[N_OK]) {
        lv_obj_set_style_transform_scale(button, 257, 0);   /* transformed: lvprobe measures no ink (U07) */
    }
    if (g_variant == V_CLIPPED && n == &g_nodes[N_OK]) {
        lv_obj_align(label, LV_ALIGN_BOTTOM_MID, 0, 22);   /* below the button's bottom edge: the button clips it */
    } else {
        lv_obj_center(label);
    }
}

static lv_obj_t *build_panel(lv_obj_t *screen, const canary_node_t *n)
{
    lv_obj_t *panel = lv_obj_create(screen);
    lv_obj_remove_style_all(panel);
    (void)place(panel, n, 0, 0);
    if (n->opa > 0u) {
        lv_obj_set_style_bg_color(panel, lv_color_hex(0x404040u), 0);
        lv_obj_set_style_bg_opa(panel, n->opa, 0);
    }
    lv_obj_set_clickable(panel, n->clickable);
    return panel;
}

static void build(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_t *card = screen;
    const canary_node_t *card_node = NULL;
    unsigned i;
    lv_obj_clean(screen);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0xFFFFFFu), 0);
    lv_obj_set_scrollable(screen, false);
    for (i = 0; i < g_count; i++) {
        const canary_node_t *n = &g_nodes[i];
        if (n->kind == CANARY_LABEL) {
            build_label(screen, n);
        } else if (n->kind == CANARY_BUTTON) {
            bool inside = n->in_card && card_node != NULL;
            build_button(inside ? card : screen, n, inside ? card_node->x : 0, inside ? card_node->y : 0);
        } else if (n->kind == CANARY_PANEL) {
            lv_obj_t *panel = build_panel(screen, n);
            if (n->opa == LV_OPA_COVER && n->clickable) {
                card = panel;
                card_node = n;
            }
        }
    }
    if (g_variant == V_COVERED) {   /* an opaque object the scene does not have, over the whole title */
        lv_obj_t *cover = lv_obj_create(screen);
        lv_obj_remove_style_all(cover);
        lv_obj_set_pos(cover, 4, 4);
        lv_obj_set_size(cover, 208, 32);
        lv_obj_set_style_bg_color(cover, lv_color_hex(0x808080u), 0);
        lv_obj_set_style_bg_opa(cover, LV_OPA_COVER, 0);
        lv_obj_set_clickable(cover, false);
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
