/* Gate-owned glue of the LVGL configuration (T107): the memory pool the product hands in, and a memory
 * test display. Include it next to "lvgl.h". Everything here is in LVGL's reserved namespace (lvgl_). */
#ifndef LVGL_GATE_H
#define LVGL_GATE_H

#include <stddef.h>
#include <stdint.h>

/* Hand LVGL its memory. Call once before lv_init() (and again before a new lv_init() after lv_deinit()).
 * `mem` must be 8-byte aligned and `bytes` must equal LV_MEM_SIZE (512 KiB). LVGL never allocates anywhere
 * else and never calls libc malloc. A missing, misaligned or wrong-sized pool traps in lv_init(). */
void lvgl_gate_set_pool(void *mem, size_t bytes);

/* Used by LVGL's allocator (LV_MEM_POOL_ALLOC); not for products. */
void *lvgl_gate_pool_take(size_t bytes);

/* Bytes a caller-owned render buffer needs for a display of width x height (XRGB8888, 4 bytes a pixel,
 * plus the alignment slack that lv_draw_buf_align() may skip). */
#define LVGL_GATE_TEST_BUF_BYTES(width, height) ((size_t)(width) * (size_t)(height) * 4u + 64u)

struct _lv_draw_buf_t;

/* A display that renders into memory the caller owns (no libc allocation, unlike lv_test_display_create()).
 * `buf` is a buffer of at least LVGL_GATE_TEST_BUF_BYTES(width, height) bytes, `draw_buf` caller-owned
 * storage for the draw buffer descriptor; both must outlive the display. Full-frame DIRECT rendering,
 * XRGB8888, the flush callback completes at once. Create the test inputs with lv_test_indev_create_all(). */
struct _lv_display_t *lvgl_gate_test_display_create(int32_t width, int32_t height, void *buf, size_t bytes,
                                                    struct _lv_draw_buf_t *draw_buf);

/* The pixel (x, y) of a test display as 0x00RRGGBB (XRGB8888), read from its buffer. 0 outside the display. */
uint32_t lvgl_gate_test_display_pixel(const struct _lv_draw_buf_t *draw_buf, int32_t x, int32_t y);

#endif /* LVGL_GATE_H */
