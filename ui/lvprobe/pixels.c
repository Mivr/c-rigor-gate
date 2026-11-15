/* gate//ui/lvprobe: pixel facts (O4) from the display's active buffer: ink attribution (2), frame CRC, region
 * hashes, luminance samples and crops (4). */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/core/lv_obj_draw_private.h"
#include "src/misc/lv_area_private.h"

#define FNV_BASIS 2166136261u
#define FNV_PRIME 16777619u

/* The full-frame XRGB8888 buffer LVGL renders the display into, or NULL. */
static const lv_draw_buf_t *frame_buf(const lvprobe_t *p)
{
    const lv_draw_buf_t *b = lv_display_get_buf_active(p->disp);
    if (b == NULL || b->data == NULL || b->header.cf != LV_COLOR_FORMAT_XRGB8888) {
        return NULL;
    }
    if ((int32_t)b->header.w != lv_display_get_horizontal_resolution(p->disp) ||
        (int32_t)b->header.h != lv_display_get_vertical_resolution(p->disp)) {
        return NULL;
    }
    return b;
}

static uint32_t pixel(const lv_draw_buf_t *b, int32_t x, int32_t y)
{
    const uint8_t *px = b->data + (size_t)y * b->header.stride + (size_t)x * 4u;
    return ((uint32_t)px[2] << 16) | ((uint32_t)px[1] << 8) | (uint32_t)px[0];
}

static uint32_t luma(uint32_t rgb)
{
    return 2126u * ((rgb >> 16) & 0xFFu) + 7152u * ((rgb >> 8) & 0xFFu) + 722u * (rgb & 0xFFu);
}

static uint32_t fnv_pixel(uint32_t h, uint32_t rgb)
{
    h = (h ^ (rgb & 0xFFu)) * FNV_PRIME;
    h = (h ^ ((rgb >> 8) & 0xFFu)) * FNV_PRIME;
    return (h ^ ((rgb >> 16) & 0xFFu)) * FNV_PRIME;
}

static bool clip_to_frame(const lv_draw_buf_t *b, const lv_area_t *in, lv_area_t *out)
{
    lv_area_t frame;
    frame.x1 = 0;
    frame.y1 = 0;
    frame.x2 = (int32_t)b->header.w - 1;
    frame.y2 = (int32_t)b->header.h - 1;
    return lv_area_intersect(out, in, &frame);
}

static uint32_t hash_box(const lv_draw_buf_t *b, const lv_area_t *box)
{
    uint32_t h = FNV_BASIS;
    lv_area_t a;
    int32_t x;
    int32_t y;
    if (!clip_to_frame(b, box, &a)) {
        return h;
    }
    for (y = a.y1; y <= a.y2; y++) {
        for (x = a.x1; x <= a.x2; x++) {
            h = fnv_pixel(h, pixel(b, x, y));
        }
    }
    return h;
}

lvprobe_status_t lvprobe_frame(lvprobe_t *p)
{
    const lv_draw_buf_t *b;
    lv_area_t all;
    uint16_t i;
    if (p == NULL || !p->open) {
        return LVPROBE_ERR_ARG;
    }
    b = frame_buf(p);
    if (b == NULL) {
        return LVPROBE_ERR_FORMAT;
    }
    all.x1 = 0;
    all.y1 = 0;
    all.x2 = (int32_t)b->header.w - 1;
    all.y2 = (int32_t)b->header.h - 1;
    p->frame_crc = hash_box(b, &all);
    p->frame_w = (int32_t)b->header.w;
    p->frame_h = (int32_t)b->header.h;
    p->has_frame = true;
    for (i = 0; i < p->count; i++) {
        p->nodes[i].region_hash = hash_box(b, &p->nodes[i].coords);
        p->nodes[i].has_region = true;
    }
    return LVPROBE_OK;
}

uint32_t lvprobe_frame_crc(const lvprobe_t *p)
{
    return (p != NULL && p->has_frame) ? p->frame_crc : 0u;
}

static void save_box(const lvprobe_t *p, const lv_draw_buf_t *b, const lv_area_t *a)
{
    size_t k = 0;
    int32_t x;
    int32_t y;
    for (y = a->y1; y <= a->y2; y++) {
        for (x = a->x1; x <= a->x2; x++) {
            p->scratch[k] = pixel(b, x, y);
            k++;
        }
    }
}

static bool box_unchanged(const lvprobe_t *p, const lv_draw_buf_t *b, const lv_area_t *a)
{
    size_t k = 0;
    int32_t x;
    int32_t y;
    for (y = a->y1; y <= a->y2; y++) {
        for (x = a->x1; x <= a->x2; x++) {
            if (p->scratch[k] != pixel(b, x, y)) {
                return false;
            }
            k++;
        }
    }
    return true;
}

static void sample(uint32_t rgb, bool first, uint32_t *lo, uint32_t *hi)
{
    if (first || luma(rgb) < luma(*lo)) {
        *lo = rgb;
    }
    if (first || luma(rgb) > luma(*hi)) {
        *hi = rgb;
    }
}

/* Saved pixels (with the node) against the current ones (without it). */
static void diff_box(const lvprobe_t *p, const lv_draw_buf_t *b, const lv_area_t *a, lvprobe_node_t *n)
{
    size_t k = 0;
    int32_t x;
    int32_t y;
    bool has = false;
    for (y = a->y1; y <= a->y2; y++) {
        for (x = a->x1; x <= a->x2; x++) {
            uint32_t with = p->scratch[k];
            uint32_t without = pixel(b, x, y);
            k++;
            if (with != without) {
                lv_area_t one = {x, y, x, y};
                sample(with, n->ink == 0u, &n->ink_lo, &n->ink_hi);
                sample(without, n->ink == 0u, &n->bg_lo, &n->bg_hi);
                n->ink++;
                lvp_box_add(&n->ink_box, &has, &one);
            }
        }
    }
}

static void clear_ink(lvprobe_node_t *n)
{
    n->ink = 0;
    n->ink_box.x1 = 0;
    n->ink_box.y1 = 0;
    n->ink_box.x2 = -1;
    n->ink_box.y2 = -1;
    n->ink_lo = 0;
    n->ink_hi = 0;
    n->bg_lo = 0;
    n->bg_hi = 0;
}

static lvprobe_status_t ink_region(const lvprobe_t *p, const lv_draw_buf_t *b, lvprobe_node_t *n, lv_area_t *a,
                                   bool *any)
{
    lv_area_t box = n->coords;
    int32_t ext = lv_obj_get_ext_draw_size(n->obj);
    box.x1 -= ext;
    box.y1 -= ext;
    box.x2 += ext;
    box.y2 += ext;
    *any = clip_to_frame(b, &box, a);
    if (*any && (size_t)lv_area_get_size(a) > p->scratch_px) {
        return LVPROBE_ERR_FULL;
    }
    return LVPROBE_OK;
}

lvprobe_status_t lvprobe_ink(lvprobe_t *p, uint16_t index)
{
    const lv_draw_buf_t *b;
    lvprobe_node_t *n;
    lv_area_t a;
    bool any;
    bool was_hidden;
    lvprobe_status_t st;

    if (p == NULL || !p->open || index >= p->count) {
        return LVPROBE_ERR_ARG;
    }
    n = &p->nodes[index];
    b = frame_buf(p);
    if (n->obj == NULL) {
        return LVPROBE_ERR_GONE;
    }
    if (b == NULL) {
        return LVPROBE_ERR_FORMAT;
    }
    lv_refr_now(p->disp); /* the saved pixels must be the settled frame */
    clear_ink(n);
    st = ink_region(p, b, n, &a, &any);
    if (st != LVPROBE_OK || !any) {
        n->has_ink = st == LVPROBE_OK;
        return st;
    }
    save_box(p, b, &a);
    was_hidden = lv_obj_is_hidden(n->obj);
    lv_obj_set_hidden(n->obj, true);
    lv_refr_now(p->disp);
    diff_box(p, b, &a, n);
    if (!was_hidden) {
        lv_obj_set_hidden(n->obj, false);
    }
    lv_refr_now(p->disp);
    n->has_ink = true;
    return box_unchanged(p, b, &a) ? LVPROBE_OK : LVPROBE_ERR_UNSTABLE;
}

lvprobe_status_t lvprobe_crop(const lvprobe_t *p, const lv_area_t *box, uint8_t *rgba, size_t cap, size_t *len)
{
    const lv_draw_buf_t *b;
    lv_area_t a;
    size_t k = 0;
    int32_t x;
    int32_t y;
    if (p == NULL || !p->open || box == NULL || rgba == NULL || len == NULL) {
        return LVPROBE_ERR_ARG;
    }
    *len = 0;
    b = frame_buf(p);
    if (b == NULL) {
        return LVPROBE_ERR_FORMAT;
    }
    if (lvp_box_empty(box) || !clip_to_frame(b, box, &a) || !lvp_box_in(box, &a)) {
        return LVPROBE_ERR_ARG;
    }
    if ((size_t)lv_area_get_size(&a) > cap / 4u) {
        return LVPROBE_ERR_TRUNC;
    }
    for (y = a.y1; y <= a.y2; y++) {
        for (x = a.x1; x <= a.x2; x++) {
            uint32_t rgb = pixel(b, x, y);
            rgba[k] = (uint8_t)(rgb >> 16);
            rgba[k + 1u] = (uint8_t)(rgb >> 8);
            rgba[k + 2u] = (uint8_t)rgb;
            rgba[k + 3u] = 0xFFu;
            k += 4u;
        }
    }
    *len = k;
    return LVPROBE_OK;
}
