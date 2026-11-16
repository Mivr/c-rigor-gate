#include "selftest/ui_canary_product/timed.h"

#include <stdio.h>
#include <string.h>

#include "lvgl_gate.h"

enum { LIFE_MS = 4000, EARLY_MS = 1000, BLINK_MS = 200, SILENT_MS = 1000, SECOND_MS = 1000, LAST_CHANGE_S = 5 };

/* 96 characters: 5878 ms of reading at 175 wpm, so a minimum dwell of 6878 ms (P004 3.10) against the 4 s timer */
static const char WORDY[] = "Your locker is open now. Please take all of your belongings and close the door firmly "
                            "when done.";

static uint64_t g_pool[LV_MEM_SIZE / 8];
static uint8_t g_frame[LVGL_GATE_TEST_BUF_BYTES(TIMED_W, TIMED_H)];
static lv_draw_buf_t g_draw_buf;
static lv_display_t *g_disp;

static bool add(timed_scene_t *out, const char *key, const char *role, const char *text, const int32_t rect[4])
{
    timed_node_t *n = NULL;
    int written = 0;
    if (out->count >= TIMED_NODES) {
        return false;
    }
    n = &out->nodes[out->count];
    written = snprintf(n->text, sizeof n->text, "%s", text);
    if (written < 0 || (size_t)written >= sizeof n->text) {
        return false;
    }
    n->key = key;
    n->role = role;
    n->x = rect[0];
    n->y = rect[1];
    n->w = rect[2];
    n->h = rect[3];
    out->count++;
    return true;
}

/* Whether the dialog of `v` is shown at `now`; TV_CLOCK compares its expiry, kept modulo 2^32, with the 64-bit
 * clock (the seeded defect). */
static bool dialog_shown(timed_variant_t v, uint64_t since, uint64_t now)
{
    switch (v) {
    case TV_CLEAN:
    case TV_SKIP:
    case TV_ZERO:
    case TV_START:
    case TV_WORDY:
        return now < since + LIFE_MS;
    case TV_EARLY:
        return now < since + EARLY_MS;
    case TV_NEVER:
        return true;
    case TV_CLOCK:
        return now < (uint64_t)(uint32_t)(since + LIFE_MS);
    default:
        return false;
    }
}

/* The value the countdown shows: the seconds left of the 4 s, as each variant formats them. */
static uint64_t countdown(timed_variant_t v, uint64_t since, uint64_t now)
{
    uint64_t end = since + LIFE_MS;
    uint64_t left = now < end ? end - now : 0u;
    uint64_t secs = (left + SECOND_MS - 1u) / SECOND_MS;
    switch (v) {
    case TV_SKIP:
        return 2u * ((left + 2u * SECOND_MS - 1u) / (2u * SECOND_MS));
    case TV_ZERO:
        return secs - 1u;
    case TV_START:
        return secs + 5u;
    case TV_NEVER:
        return secs > 0u ? secs : 1u;
    default:
        return secs;
    }
}

void timed_scene_at(timed_variant_t v, uint64_t since, uint64_t now, timed_scene_t *out)
{
    static const int32_t title[4] = {10, 8, 300, 24};
    static const int32_t card[4] = {60, 60, 200, 120};
    static const int32_t msg[4] = {70, 80, 180, 24};
    static const int32_t count[4] = {70, 130, 180, 24};
    static const int32_t blink[4] = {10, 200, 60, 30};
    char digits[TIMED_TEXT];
    char name[TIMED_TEXT];
    int named = snprintf(name, sizeof name, "Timed canary %u", (unsigned)v);   /* each variant its own state */
    bool ok = named > 0 && (size_t)named < sizeof name;
    out->count = 0;
    out->cls = v == TV_SILENT && now >= since + SILENT_MS ? "detail" : "main";
    ok = ok && add(out, "title", "text", name, title);
    if (dialog_shown(v, since, now)) {
        int n = snprintf(digits, sizeof digits, "%llu s", (unsigned long long)countdown(v, since, now));
        ok = ok && n > 0 && (size_t)n < sizeof digits && add(out, "card", "dialog", "", card) &&
             add(out, "msg", "text", v == TV_WORDY ? WORDY : "Saved.", msg) &&
             add(out, "count", "countdown", digits, count);
        out->cls = "dialog";
    }
    if (v == TV_BLINK && now < since + BLINK_MS) {
        ok = ok && add(out, "blink", "panel", "", blink);
    }
    if (!ok) {
        out->count = 0;   /* cannot happen with these tables; an empty scene would show it */
    }
}

uint64_t timed_next_change(timed_variant_t v, uint64_t since, uint64_t now)
{
    uint64_t k;
    if (v == TV_NONE || v == TV_FLASH) {
        return TIMED_NONE;
    }
    if (v == TV_BLINK) {
        return now < since + BLINK_MS ? since + BLINK_MS : TIMED_NONE;
    }
    for (k = 1u; k <= LAST_CHANGE_S; k++) {
        if (since + k * SECOND_MS > now) {
            return since + k * SECOND_MS;
        }
    }
    return TIMED_NONE;
}

static lv_obj_t *place(lv_obj_t *parent, const timed_node_t *n, int32_t ox, int32_t oy, bool label)
{
    lv_obj_t *obj = label ? lv_label_create(parent) : lv_obj_create(parent);
    if (obj == NULL) {
        return NULL;
    }
    if (label) {
        lv_label_set_text(obj, n->text);
    } else {
        lv_obj_remove_style_all(obj);
        lv_obj_set_style_bg_color(obj, lv_color_hex(0x404040u), 0);
        lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
    }
    lv_obj_set_pos(obj, n->x - ox, n->y - oy);
    lv_obj_set_size(obj, n->w, n->h);
    return obj;
}

bool timed_build(const timed_scene_t *scene)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_t *card = NULL;
    unsigned i;
    lv_obj_clean(screen);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0xFFFFFFu), 0);
    lv_obj_set_scrollable(screen, false);
    for (i = 0; i < scene->count; i++) {
        const timed_node_t *n = &scene->nodes[i];
        bool label = strcmp(n->role, "text") == 0 || strcmp(n->role, "countdown") == 0;
        bool inside = card != NULL && strcmp(n->key, "blink") != 0;
        lv_obj_t *obj = place(inside ? card : screen, n, inside ? 60 : 0, inside ? 60 : 0, label);
        if (obj == NULL) {
            return false;
        }
        if (strcmp(n->role, "dialog") == 0) {
            lv_obj_set_style_bg_color(obj, lv_color_hex(0xE0E0E0u), 0);
            card = obj;
        }
    }
    return true;
}

bool timed_flash_object(void)
{
    lv_obj_t *obj = lv_obj_create(lv_screen_active());
    if (obj == NULL) {
        return false;
    }
    lv_obj_delete(obj);
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

bool timed_start(void)
{
    stop();
    lvgl_gate_set_pool(g_pool, sizeof g_pool);
    lv_init();
    g_disp = lvgl_gate_test_display_create(TIMED_W, TIMED_H, g_frame, sizeof g_frame, &g_draw_buf);
    return g_disp != NULL;
}

lv_display_t *timed_display(void)
{
    return g_disp;
}

void timed_step(uint32_t ms)
{
    lv_tick_inc(ms);
    (void)lv_timer_handler();
}

void timed_draw(void)
{
    lv_refr_now(g_disp);
}
