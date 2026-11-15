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

/* `"`, `\` and bytes < 0x20 or 0x7f are escaped; every other byte (UTF-8 included) is copied. */
static void put_text(wr_t *w, const char *s)
{
    size_t i;
    put_c(w, '"');
    for (i = 0; s[i] != '\0' && w->ok; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '"' || c == '\\') {
            put_c(w, '\\');
            put_c(w, (char)c);
        } else if (c < 0x20u || c == 0x7fu) {
            put_s(w, "\\x");
            put_hex(w, c, 2);
        } else {
            put_c(w, (char)c);
        }
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

static void line_node(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "node ");
    put_u(w, i);
    put_key_i(w, "parent", n->parent);
    put_key_i(w, "depth", n->depth);
    put_s(w, " class=");
    put_s(w, n->class_name);
    put_s(w, " box=");
    put_box(w, true, &n->coords);
    put_key_i(w, "hidden", n->hidden ? 1 : 0);
    put_key_i(w, "clickable", n->clickable ? 1 : 0);
    put_key_i(w, "clip", n->clip);
    put_s(w, " bg=");
    put_hex(w, n->bg_rgb, 6);
    put_key_i(w, "bg_opa", n->bg_opa);
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
    put_key_i(w, "long", n->long_mode);
    put_key_i(w, "lines", n->lines);
    put_key_i(w, "natural_w", n->natural.x);
    put_key_i(w, "natural_h", n->natural.y);
    put_key_i(w, "laid_w", n->laid_out.x);
    put_key_i(w, "laid_h", n->laid_out.y);
    put_s(w, " text=");
    put_text(w, n->text);
    put_c(w, '\n');
}

static void line_fit(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "fit ");
    put_u(w, i);
    put_key_i(w, "drawn", n->drawn ? 1 : 0);
    put_s(w, " glyphs=");
    put_box(w, n->has_glyphs, &n->glyphs);
    put_s(w, " visible=");
    put_box(w, n->drawn, &n->visible);
    put_key_i(w, "clipped", n->clipped ? 1 : 0);
    put_c(w, '\n');
}

static void line_ink(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "ink ");
    put_u(w, i);
    put_key_i(w, "count", n->ink);
    put_s(w, " box=");
    put_box(w, n->ink > 0u, &n->ink_box);
    put_s(w, " ink_lo=");
    put_hex(w, n->ink_lo, 6);
    put_s(w, " ink_hi=");
    put_hex(w, n->ink_hi, 6);
    put_s(w, " bg_lo=");
    put_hex(w, n->bg_lo, 6);
    put_s(w, " bg_hi=");
    put_hex(w, n->bg_hi, 6);
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
        put_s(w, " crc=");
        put_hex(w, p->frame_crc, 8);
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
        if (n->has_ink) {
            line_ink(&w, n, i);
        }
        if (n->has_region) {
            put_s(&w, "region ");
            put_u(&w, i);
            put_s(&w, " hash=");
            put_hex(&w, n->region_hash, 8);
            put_c(&w, '\n');
        }
    }
    *len = w.ok ? w.len : 0u;
    if (cap > 0u) {
        buf[w.ok ? w.len : 0u] = '\0';
    }
    return w.ok ? LVPROBE_OK : LVPROBE_ERR_TRUNC;
}
