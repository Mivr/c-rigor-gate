/* Gate-owned glue for the LVGL configuration (T107). Compiled into the library with its flags; everything
 * here is in LVGL's reserved namespace (lvgl_). No libc call: the pool and the buffers belong to the product. */
#include <stddef.h>
#include <stdint.h>

#define LV_USE_PRIVATE_API 1
#include "lvgl.h"
#include "lvgl_gate.h"

static void *g_pool;
static size_t g_pool_bytes;

void lvgl_gate_set_pool(void *mem, size_t bytes)
{
    g_pool = mem;
    g_pool_bytes = bytes;
}

/* LVGL asks for exactly LV_MEM_SIZE bytes. Anything else is a product bug that must not limp on. */
void *lvgl_gate_pool_take(size_t bytes)
{
    if (g_pool == NULL || bytes != g_pool_bytes || ((uintptr_t)g_pool & 7u) != 0u) {
        __builtin_trap();
    }
    return g_pool;
}

static void flush_done(lv_display_t *disp, const lv_area_t *area, uint8_t *px)
{
    (void)area;
    (void)px;
    lv_display_flush_ready(disp);
}

lv_display_t *lvgl_gate_test_display_create(int32_t width, int32_t height, void *buf, size_t bytes,
                                            lv_draw_buf_t *draw_buf)
{
    lv_display_t *disp;

    if (width <= 0 || height <= 0 || buf == NULL || draw_buf == NULL || bytes < LVGL_GATE_TEST_BUF_BYTES(width, height)) {
        return NULL;
    }
    disp = lv_display_create(width, height);
    if (disp == NULL) {
        return NULL;
    }
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_XRGB8888);
    if (lv_draw_buf_init(draw_buf, (uint32_t)width, (uint32_t)height, LV_COLOR_FORMAT_XRGB8888, LV_STRIDE_AUTO,
                         lv_draw_buf_align(buf, LV_COLOR_FORMAT_XRGB8888), (uint32_t)bytes - 64u) != LV_RESULT_OK) {
        lv_display_delete(disp);
        return NULL;
    }
    lv_display_set_draw_buffers(disp, draw_buf, NULL);
    lv_display_set_render_mode(disp, LV_DISPLAY_RENDER_MODE_DIRECT);
    lv_display_set_flush_cb(disp, flush_done);
    return disp;
}

uint32_t lvgl_gate_test_display_pixel(const lv_draw_buf_t *draw_buf, int32_t x, int32_t y)
{
    const uint8_t *row;
    const uint32_t *px;

    if (draw_buf == NULL || x < 0 || y < 0 || (uint32_t)x >= draw_buf->header.w || (uint32_t)y >= draw_buf->header.h) {
        return 0;
    }
    row = (const uint8_t *)draw_buf->data + (size_t)y * draw_buf->header.stride;
    px = (const uint32_t *)(const void *)row;
    return px[x] & 0x00FFFFFFu;
}
