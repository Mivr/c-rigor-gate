/* gate//ui/lvprobe: the line-oriented text encoder (6) of the walk (1), the verdict facts (2) and the frame facts
 * (4). One fact per line, fixed field order; the format is in docs/ui-lvprobe.md. Truncation is an error. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

typedef struct {
    char *buf;
    size_t cap;
    size_t len;
    bool ok;
} wr_t;

static void put_c(wr_t *w, char c)
{
    if (!w->ok || w->len + 1u >= w->cap) {
        w->ok = false; /* one byte stays free for the NUL */
        return;
    }
    w->buf[w->len] = c;
    w->len++;
}

static void put_s(wr_t *w, const char *s)
{
    size_t i;
    for (i = 0; s[i] != '\0' && w->ok; i++) {
        put_c(w, s[i]);
    }
}

static void put_u(wr_t *w, uint64_t v)
{
    char digits[20];
    size_t n = 0;
    do {
        digits[n] = (char)('0' + (int)(v % 10u));
        n++;
        v /= 10u;
    } while (v != 0u && n < sizeof digits);
    while (n > 0u) {
        n--;
        put_c(w, digits[n]);
    }
}

static void put_i(wr_t *w, int64_t v)
{
    if (v < 0) {
        put_c(w, '-');
        put_u(w, (uint64_t)(-(v + 1)) + 1u);
    } else {
        put_u(w, (uint64_t)v);
    }
}

static void put_hex(wr_t *w, uint32_t v, int digits)
{
    static const char hex[] = "0123456789abcdef";
    int i;
    for (i = digits - 1; i >= 0; i--) {
        put_c(w, hex[(v >> (4 * i)) & 0xFu]);
    }
}

/* Always the four numbers, an empty box (a zero-size object) included. */
static void put_coords(wr_t *w, const lv_area_t *a)
{
    put_i(w, a->x1);
    put_c(w, ',');
    put_i(w, a->y1);
    put_c(w, ',');
    put_i(w, a->x2);
    put_c(w, ',');
    put_i(w, a->y2);
}

static void put_box(wr_t *w, bool has, const lv_area_t *a)
{
    if (!has || lvp_box_empty(a)) {
        put_c(w, '-');
        return;
    }
    put_i(w, a->x1);
    put_c(w, ',');
    put_i(w, a->y1);
    put_c(w, ',');
    put_i(w, a->x2);
    put_c(w, ',');
    put_i(w, a->y2);
}

/* Length of the valid UTF-8 sequence at `s` (1..4), or 0 when it is not one (overlong, surrogate, > U+10FFFF,
 * truncated or a stray continuation byte). */
static size_t utf8_len(const unsigned char *s)
{
    size_t n;
    size_t i;
    uint32_t cp;
    if (s[0] < 0x80u) {
        return 1;
    }
    n = (s[0] & 0xE0u) == 0xC0u ? 2u : (s[0] & 0xF0u) == 0xE0u ? 3u : (s[0] & 0xF8u) == 0xF0u ? 4u : 0u;
    if (n == 0u) {
        return 0;
    }
    cp = (uint32_t)s[0] & (0x7Fu >> n);
    for (i = 1; i < n; i++) {
        if ((s[i] & 0xC0u) != 0x80u) {
            return 0;
        }
        cp = (cp << 6) | ((uint32_t)s[i] & 0x3Fu);
    }
    if ((n == 2u && cp < 0x80u) || (n == 3u && cp < 0x800u) || (n == 4u && cp < 0x10000u) || cp > 0x10FFFFu ||
        (cp >= 0xD800u && cp <= 0xDFFFu)) {
        return 0;
    }
    return n;
}

/* `"` and `\` get a `\`; bytes < 0x20, 0x7f and bytes that are not part of valid UTF-8 become `\xHH`; valid
 * UTF-8 sequences are copied. */
static void put_text(wr_t *w, const char *s)
{
    const unsigned char *u = (const unsigned char *)s;
    size_t i = 0;
    put_c(w, '"');
    while (u[i] != 0u && w->ok) {
        size_t n = utf8_len(&u[i]);
        size_t k;
        if (u[i] == '"' || u[i] == '\\') {
            put_c(w, '\\');
            put_c(w, (char)u[i]);
            n = 1;
        } else if (n == 0u || u[i] < 0x20u || u[i] == 0x7fu) {
            put_s(w, "\\x");
            put_hex(w, u[i], 2);
            n = 1;
        } else {
            for (k = 0; k < n; k++) {
                put_c(w, (char)u[i + k]);
            }
        }
        i += n;
    }
    put_c(w, '"');
}

static void put_key_i(wr_t *w, const char *key, int64_t v)
{
    put_c(w, ' ');
    put_s(w, key);
    put_c(w, '=');
    put_i(w, v);
}

static void put_key_hex(wr_t *w, const char *key, uint32_t v, int digits)
{
    put_c(w, ' ');
    put_s(w, key);
    put_c(w, '=');
    put_hex(w, v, digits);
}

static void put_key_box(wr_t *w, const char *key, bool has, const lv_area_t *a)
{
    put_c(w, ' ');
    put_s(w, key);
    put_c(w, '=');
    put_box(w, has, a);
}

static void line_node(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "node ");
    put_u(w, i);
    put_key_i(w, "parent", n->parent);
    put_key_i(w, "depth", n->depth);
    put_s(w, " class=");
    put_text(w, n->class_name);
    put_s(w, " box=");
    put_coords(w, &n->coords);
    put_key_i(w, "hidden", n->hidden ? 1 : 0);
    put_key_i(w, "clickable", n->clickable ? 1 : 0);
    put_key_i(w, "clip", n->clip);
    put_key_i(w, "scroll", n->scroll);
    put_key_i(w, "scroll_x", n->scroll_x);
    put_key_i(w, "scroll_y", n->scroll_y);
    put_key_hex(w, "bg", n->bg_rgb, 6);
    put_key_i(w, "bg_opa", n->bg_opa);
    put_key_i(w, "bg_opa_drawn", n->bg_opa_drawn);
    put_key_i(w, "bg_grad", n->bg_grad ? 1 : 0);
    put_key_i(w, "bg_image", n->bg_image ? 1 : 0);
    put_c(w, '\n');
}

static void line_label(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "label ");
    put_u(w, i);
    if (n->font_id == LVPROBE_FONT_UNMAPPED) {
        put_s(w, " font=-");
    } else {
        put_key_i(w, "font", n->font_id);
    }
    put_key_i(w, "line_h", n->line_height);
    put_key_i(w, "align", n->align);
    put_key_i(w, "align_drawn", n->align_drawn);
    put_key_i(w, "long", n->long_mode);
    put_key_i(w, "dotted", n->dotted ? 1 : 0);
    put_key_i(w, "lines", n->lines);
    put_key_i(w, "natural_w", n->natural.x);
    put_key_i(w, "natural_h", n->natural.y);
    put_key_i(w, "laid_w", n->laid_out.x);
    put_key_i(w, "laid_h", n->laid_out.y);
    put_s(w, " text=");
    put_text(w, n->text);
    put_s(w, " full_text=");
    put_text(w, n->full_text);
    put_c(w, '\n');
}

static void line_fit(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "fit ");
    put_u(w, i);
    put_key_i(w, "drawn", n->drawn ? 1 : 0);
    put_key_box(w, "glyphs", n->has_glyphs, &n->glyphs);
    put_key_box(w, "visible", n->drawn, &n->visible);
    put_key_i(w, "missing", n->missing);
    put_key_i(w, "clipped", n->clipped ? 1 : 0);
    put_c(w, '\n');
}

static void line_ink(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "ink ");
    put_u(w, i);
    if (n->unstable) {
        put_s(w, " unstable=1\n");
        return;
    }
    put_s(w, " unstable=0");
    put_key_i(w, "count", n->ink);
    put_key_box(w, "box", n->ink > 0u, &n->ink_box);
    put_key_hex(w, "ink_lo", n->ink_lo, 6);
    put_key_hex(w, "ink_hi", n->ink_hi, 6);
    put_key_hex(w, "bg_lo", n->bg_lo, 6);
    put_key_hex(w, "bg_hi", n->bg_hi, 6);
    put_c(w, '\n');
}

static void lines_head(wr_t *w, const lvprobe_t *p)
{
    put_s(w, "lvprobe/1 nodes=");
    put_u(w, p->count);
    put_c(w, '\n');
    if (p->has_frame) {
        put_s(w, "frame");
        put_key_i(w, "w", p->frame_w);
        put_key_i(w, "h", p->frame_h);
        put_key_hex(w, "crc", p->frame_crc, 8);
        put_c(w, '\n');
    }
}

lvprobe_status_t lvprobe_encode(const lvprobe_t *p, char *buf, size_t cap, size_t *len)
{
    wr_t w;
    uint16_t i;
    if (p == NULL || !p->open || buf == NULL || len == NULL) {
        return LVPROBE_ERR_ARG;
    }
    w.buf = buf;
    w.cap = cap;
    w.len = 0;
    w.ok = true;
    lines_head(&w, p);
    for (i = 0; i < p->count && w.ok; i++) {
        const lvprobe_node_t *n = &p->nodes[i];
        line_node(&w, n, i);
        if (n->is_label) {
            line_label(&w, n, i);
            line_fit(&w, n, i);
        }
        if (n->has_ink || n->unstable) {
            line_ink(&w, n, i);
        }
        if (n->has_region) {
            put_s(&w, "region ");
            put_u(&w, i);
            put_key_hex(&w, "hash", n->region_hash, 8);
            put_c(&w, '\n');
        }
    }
    *len = w.ok ? w.len : 0u;
    if (cap > 0u) {
        buf[w.ok ? w.len : 0u] = '\0';
    }
    return w.ok ? LVPROBE_OK : LVPROBE_ERR_TRUNC;
}
