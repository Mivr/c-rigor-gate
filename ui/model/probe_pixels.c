/* `ink` and `crop` (U05a; docs/ui-model.md, "Frame facts"): the ink records of lvprobe's hide/re-render differential,
 * and the RGBA of a region of the current frame. Static memory only; no recursion. */
#include <string.h>

#include "ui/model/probe.h"

static char g_scratch[UIM_BUF_MAX];   /* one node's encoding (ink), or the RGBA bytes of a crop */

static bool starts(const char *s, const char *prefix)
{
    size_t i;
    for (i = 0; prefix[i] != '\0'; i++) {
        if (s[i] != prefix[i]) {
            return false;
        }
    }
    return true;
}

/* Copies the `ink` or `noink` line of node `i` (lvprobe's encoding of the node, filtered) to out[*at..]. */
static lvprobe_status_t ink_line(const probe_t *p, uint16_t i, char *out, size_t cap, size_t *at)
{
    size_t len = 0;
    size_t k = 0;
    lvprobe_status_t st = lvprobe_encode_node(p->lv, i, g_scratch, sizeof g_scratch, &len);
    while (st == LVPROBE_OK && k < len) {
        size_t end = k;
        while (end < len && g_scratch[end] != '\n') {
            end++;
        }
        if (end < len && (starts(&g_scratch[k], "ink\t") || starts(&g_scratch[k], "noink\t"))) {
            if (end + 1u - k >= cap - *at) {
                return LVPROBE_ERR_TRUNC;
            }
            memcpy(out + *at, &g_scratch[k], end + 1u - k);
            *at += end + 1u - k;
            return LVPROBE_OK;
        }
        k = end + 1u;
    }
    return st == LVPROBE_OK ? LVPROBE_ERR_ARG : st;   /* measured, yet no ink line: the probe's own error */
}

/* One node: unstable or unsettled is settled and retried once (a settle that flushed makes the last frame's checksum
 * older than the buffer: the frame is dropped); still unstable or transformed is data (`noink`). */
static lvprobe_status_t ink_one(probe_t *p, uint16_t i)
{
    unsigned t;
    bool flushed = false;
    lvprobe_status_t st = lvprobe_ink(p->lv, i);
    for (t = 0; t < PROBE_INK_RETRIES && (st == LVPROBE_ERR_UNSTABLE || st == LVPROBE_ERR_UNSETTLED); t++) {
        st = probe_lv_settle(p, &flushed);
        p->framed = p->framed && !flushed;
        st = st == LVPROBE_OK ? lvprobe_ink(p->lv, i) : st;
    }
    return (st == LVPROBE_ERR_UNSTABLE || st == LVPROBE_ERR_UNSUPPORTED) ? LVPROBE_OK : st;
}

static bool is_root(const probe_t *p, uint16_t i)
{
    const lvprobe_node_t *n = lvprobe_node(p->lv, i);
    return n == NULL || n->parent == LVPROBE_NONE;
}

/* The ink lines of nodes [first, last) but the roots into the payload; `*at` bytes. */
static lvprobe_status_t ink_range(probe_t *p, uint16_t first, uint16_t last, size_t *at)
{
    size_t cap = 0;
    char *out = probe_payload(&cap);
    uint16_t i;
    lvprobe_status_t st = LVPROBE_OK;
    for (i = first; i < last && st == LVPROBE_OK; i++) {
        st = is_root(p, i) ? LVPROBE_OK : ink_one(p, i);
        st = (st == LVPROBE_OK && !is_root(p, i)) ? ink_line(p, i, out, cap, at) : st;
    }
    return st;
}

/* `ink`: every node of the walk but the roots, in walk order; `ink <i>`: node i. Poisons on error (it refreshes). */
bool probe_cmd_ink(probe_t *p, char **arg)
{
    uint64_t want = 0;
    uint16_t count = lvprobe_count(p->lv);
    size_t cap = 0;
    char *out = probe_payload(&cap);
    size_t at = 0;
    long lines = 0;
    uint32_t tick = 0;
    lvprobe_status_t st;
    if (arg[0] != NULL && !probe_parse_u64(arg[0], &want)) {
        return probe_reply_err("ink", "bad-arguments");
    }
    if (!p->framed) {
        return probe_reply_err("ink", "no-frame");
    }
    if (arg[0] != NULL && (want >= count || is_root(p, (uint16_t)want))) {
        return probe_reply_err("ink", "bad-arguments");   /* no such node, or a screen or layer root */
    }
    tick = lv_tick_get();
    st = arg[0] != NULL ? ink_range(p, (uint16_t)want, (uint16_t)(want + 1u), &at) : ink_range(p, 0, count, &at);
    st = (st == LVPROBE_OK && lv_tick_get() != tick) ? LVPROBE_ERR_FORMAT : st;
    if (st != LVPROBE_OK) {
        return probe_fatal(p, probe_why(st));
    }
    lines = probe_check_records(NULL, out, at);
    return lines >= 0 ? probe_reply_lines("ink", (size_t)lines, at) : probe_fatal(p, "internal");
}

/* `x y w h` inside the display, its hex rows (8 w digits and an LF each, and the NUL of the hex writer) within `cap`. */
static bool crop_box(const probe_t *p, const uint64_t v[4], size_t cap, lv_area_t *box)
{
    uint64_t dw = (uint64_t)lv_display_get_horizontal_resolution(p->disp);
    uint64_t dh = (uint64_t)lv_display_get_vertical_resolution(p->disp);
    if (v[2] == 0u || v[3] == 0u || v[0] >= dw || v[1] >= dh || v[2] > dw - v[0] || v[3] > dh - v[1] ||
        8u * v[2] + 1u > (cap - 1u) / v[3]) {
        return false;
    }
    box->x1 = (int32_t)v[0];
    box->y1 = (int32_t)v[1];
    box->x2 = (int32_t)(v[0] + v[2] - 1u);
    box->y2 = (int32_t)(v[1] + v[3] - 1u);
    return true;
}

/* RGBA8888 of a region of the current frame, one line of lowercase hex per row. Read-only: errors do not poison. */
bool probe_cmd_crop(probe_t *p, char **arg)
{
    uint64_t v[4];
    size_t cap = 0;
    char *out = probe_payload(&cap);
    size_t len = 0;
    size_t at = 0;
    size_t row = 0;
    lv_area_t box;
    unsigned k;
    uint32_t tick = 0;
    lvprobe_status_t st;
    for (k = 0; k < 4u; k++) {
        if (!probe_parse_u64(arg[k], &v[k])) {
            return probe_reply_err("crop", "bad-arguments");
        }
    }
    if (!p->framed) {
        return probe_reply_err("crop", "no-frame");
    }
    if (!crop_box(p, v, cap, &box)) {
        return probe_reply_err("crop", "bad-arguments");
    }
    row = (size_t)v[2] * 4u;
    tick = lv_tick_get();
    st = lvprobe_crop(p->lv, &box, (uint8_t *)(void *)g_scratch, sizeof g_scratch, &len);
    if (st != LVPROBE_OK || len != row * (size_t)v[3] || lv_tick_get() != tick) {
        return probe_refuse(p, st != LVPROBE_OK ? "internal" : len != row * (size_t)v[3] ? "internal" : "model-contract");
    }
    for (k = 0; k < v[3]; k++) {
        probe_to_hex((const unsigned char *)&g_scratch[(size_t)k * row], row, out + at);
        at += 2u * row;
        out[at++] = '\n';
    }
    return probe_reply_lines("crop", (size_t)v[3], at);
}
