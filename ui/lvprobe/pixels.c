/* gate//ui/lvprobe: frame facts (4) from the display's one full-size buffer: frame CRC, region hashes, crops. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/display/lv_display_private.h"

#define FNV_BASIS 2166136261u
#define FNV_PRIME 16777619u

/* DIRECT render mode into one buffer of the display's size, XRGB8888: then the buffer is the frame. */
const lv_draw_buf_t *lvp_frame_buf(const lvprobe_t *p)
{
    const lv_display_t *d = p->disp;
    const lv_draw_buf_t *b = d->buf_1;
    if (d->render_mode != LV_DISPLAY_RENDER_MODE_DIRECT || b == NULL || d->buf_2 != NULL || d->buf_act != b ||
        b->data == NULL || b->header.cf != LV_COLOR_FORMAT_XRGB8888) {
        return NULL;
    }
    if ((int32_t)b->header.w != lv_display_get_horizontal_resolution(p->disp) ||
        (int32_t)b->header.h != lv_display_get_vertical_resolution(p->disp)) {
        return NULL;
    }
    return b;
}

uint32_t lvp_pixel(const lv_draw_buf_t *b, int32_t x, int32_t y)
{
    const uint8_t *px = b->data + (size_t)y * b->header.stride + (size_t)x * 4u;
    return ((uint32_t)px[2] << 16) | ((uint32_t)px[1] << 8) | (uint32_t)px[0];
}

bool lvp_clip_to_frame(const lv_draw_buf_t *b, const lv_area_t *in, lv_area_t *out)
{
    lv_area_t frame;
    frame.x1 = 0;
    frame.y1 = 0;
    frame.x2 = (int32_t)b->header.w - 1;
    frame.y2 = (int32_t)b->header.h - 1;
    *out = *in;
    return lvp_box_cut(out, &frame);
}

static uint32_t fnv_pixel(uint32_t h, uint32_t rgb)
{
    h = (h ^ (rgb & 0xFFu)) * FNV_PRIME;
    h = (h ^ ((rgb >> 8) & 0xFFu)) * FNV_PRIME;
    return (h ^ ((rgb >> 16) & 0xFFu)) * FNV_PRIME;
}

static uint32_t hash_box(const lv_draw_buf_t *b, const lv_area_t *box)
{
    uint32_t h = FNV_BASIS;
    lv_area_t a;
    int32_t x;
    int32_t y;
    if (lvp_box_empty(box) || !lvp_clip_to_frame(b, box, &a)) {
        return h;
    }
    for (y = a.y1; y <= a.y2; y++) {
        for (x = a.x1; x <= a.x2; x++) {
            h = fnv_pixel(h, lvp_pixel(b, x, y));
        }
    }
    return h;
}

lvprobe_status_t lvprobe_frame(lvprobe_t *p)
{
    const lv_draw_buf_t *b;
    lv_area_t all;
    uint16_t i;
    lvprobe_status_t st = lvp_current(p, true);
    if (st != LVPROBE_OK) {
        return st;
    }
    b = lvp_frame_buf(p);
    if (b == NULL) {
        return LVPROBE_ERR_FORMAT;
    }
    lvp_display_area(p, &all);
    p->frame_crc = hash_box(b, &all);
    p->frame_w = (int32_t)b->header.w;
    p->frame_h = (int32_t)b->header.h;
    p->has_frame = true;
    for (i = 0; i < p->count; i++) {
        p->cfg.nodes[i].region_hash = hash_box(b, &p->cfg.nodes[i].coords);
        p->cfg.nodes[i].has_region = true;
    }
    return LVPROBE_OK;
}

uint32_t lvprobe_frame_crc(const lvprobe_t *p)
{
    return (p != NULL && p->has_frame) ? p->frame_crc : 0u;
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
    if (p->disp_gone) {
        return LVPROBE_ERR_GONE;
    }
    b = lvp_frame_buf(p);
    if (b == NULL) {
        return LVPROBE_ERR_FORMAT;
    }
    if (lvp_box_empty(box) || !lvp_clip_to_frame(b, box, &a) || !lvp_box_in(box, &a)) {
        return LVPROBE_ERR_ARG;
    }
    if ((size_t)lv_area_get_size(&a) > cap / 4u) {
        return LVPROBE_ERR_TRUNC;
    }
    for (y = a.y1; y <= a.y2; y++) {
        for (x = a.x1; x <= a.x2; x++) {
            uint32_t rgb = lvp_pixel(b, x, y);
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
