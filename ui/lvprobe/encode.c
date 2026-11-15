/* gate//ui/lvprobe: the text encoder (6) of the walk (1), the verdict facts (2) and the frame facts (4), as records
 * of the ui-probe/1 grammar (docs/ui-model.md): one line per fact, LF-terminated, fields separated by single TABs in a
 * fixed order and number, only printable ASCII; inside a field `\\`, `\t`, `\n` and `\xHH` (lowercase) for every
 * other byte outside 0x20..0x7e, UTF-8 bytes included. The format is in docs/ui-lvprobe.md. Truncation is an error;
 * the writer keeps counting, so the caller learns the exact length needed. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

typedef struct {
    char *buf;
    size_t cap;
    size_t len; /* bytes the text needs so far, also past the end of the buffer */
} wr_t;

static void put_c(wr_t *w, char c)
{
    if (w->len + 1u < w->cap) { /* one byte stays free for the NUL */
        w->buf[w->len] = c;
    }
    w->len++;
}

static void put_s(wr_t *w, const char *s)
{
    size_t i;
    for (i = 0; s[i] != '\0'; i++) {
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

/* A field: the record escaping of docs/ui-model.md. */
static void put_field(wr_t *w, const char *s)
{
    const unsigned char *u = (const unsigned char *)s;
    size_t i;
    for (i = 0; u[i] != 0u; i++) {
        if (u[i] == '\\') {
            put_s(w, "\\\\");
        } else if (u[i] == '\t') {
            put_s(w, "\\t");
        } else if (u[i] == '\n') {
            put_s(w, "\\n");
        } else if (u[i] < 0x20u || u[i] > 0x7eu) {
            put_s(w, "\\x");
            put_hex(w, u[i], 2);
        } else {
            put_c(w, (char)u[i]);
        }
    }
}

static void tab(wr_t *w)
{
    put_c(w, '\t');
}

static void f_i(wr_t *w, int64_t v)
{
    tab(w);
    put_i(w, v);
}

static void f_hex(wr_t *w, uint32_t v, int digits)
{
    tab(w);
    put_hex(w, v, digits);
}

static void f_text(wr_t *w, const char *s)
{
    tab(w);
    put_field(w, s);
}

/* A label text: always the prefix `=` and then the escaped bytes, so an empty text is `=` (never an empty field) and
 * no text can be confused with a marker such as `-`. */
static void f_label_text(wr_t *w, const char *s)
{
    tab(w);
    put_c(w, '=');
    put_field(w, s);
}

/* x1,y1,x2,y2, or `-` when empty or unknown (a node's own box is always the four numbers). */
static void f_box(wr_t *w, bool has, const lv_area_t *a)
{
    tab(w);
    if (!has) {
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

/* node: 21 fields. */
static void line_node(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "node");
    f_i(w, i);
    f_i(w, n->parent);
    f_i(w, n->depth);
    f_text(w, n->class_name);
    f_i(w, n->coords.x1);
    f_i(w, n->coords.y1);
    f_i(w, n->coords.x2);
    f_i(w, n->coords.y2);
    f_i(w, n->hidden ? 1 : 0);
    f_i(w, n->clickable ? 1 : 0);
    f_i(w, n->clip);
    f_i(w, n->scroll);
    f_i(w, n->scroll_x);
    f_i(w, n->scroll_y);
    f_hex(w, n->bg_rgb, 6);
    f_i(w, n->bg_opa);
    f_i(w, n->bg_opa_drawn);
    f_i(w, n->bg_opa_exact ? 1 : 0);
    f_i(w, n->bg_grad ? 1 : 0);
    f_i(w, n->bg_image ? 1 : 0);
    put_c(w, '\n');
}

/* label: 15 fields. */
static void line_label(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "label");
    f_i(w, i);
    if (n->font_id == LVPROBE_FONT_UNMAPPED) {
        f_text(w, "-");
    } else {
        f_i(w, n->font_id);
    }
    f_i(w, n->line_height);
    f_i(w, n->align);
    f_i(w, n->align_drawn);
    f_i(w, n->long_mode);
    f_i(w, n->dotted ? 1 : 0);
    f_i(w, n->lines);
    f_i(w, n->natural.x);
    f_i(w, n->natural.y);
    f_i(w, n->laid_out.x);
    f_i(w, n->laid_out.y);
    f_label_text(w, n->text);
    if (n->dotted) {
        f_label_text(w, n->full_text);
    } else {
        f_text(w, "-"); /* the full text is the text */
    }
    put_c(w, '\n');
}

/* fit: 8 fields. */
static void line_fit(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    put_s(w, "fit");
    f_i(w, i);
    f_i(w, n->drawn ? 1 : 0);
    f_i(w, n->unsupported ? 1 : 0);
    f_box(w, n->has_glyphs && !lvp_box_empty(&n->glyphs), &n->glyphs);
    f_box(w, n->drawn && !lvp_box_empty(&n->visible), &n->visible);
    f_i(w, n->missing);
    f_i(w, n->clipped ? 1 : 0);
    put_c(w, '\n');
}

/* ink: 8 fields; noink: 3 fields (the node was not measured, and why). */
static void line_ink(wr_t *w, const lvprobe_node_t *n, uint16_t i)
{
    if (n->unstable || n->ink_unsupported) {
        put_s(w, "noink");
        f_i(w, i);
        f_text(w, n->unstable ? "unstable" : "transformed");
        put_c(w, '\n');
        return;
    }
    put_s(w, "ink");
    f_i(w, i);
    f_i(w, n->ink);
    f_box(w, n->ink > 0u, &n->ink_box);
    f_hex(w, n->ink_lo, 6);
    f_hex(w, n->ink_hi, 6);
    f_hex(w, n->bg_lo, 6);
    f_hex(w, n->bg_hi, 6);
    put_c(w, '\n');
}

static void lines_node(wr_t *w, const lvprobe_t *p, uint16_t i)
{
    const lvprobe_node_t *n = &p->cfg.nodes[i];
    line_node(w, n, i);
    if (n->is_label) {
        line_label(w, n, i);
        line_fit(w, n, i);
    }
    if (n->has_ink || n->unstable || n->ink_unsupported) {
        line_ink(w, n, i);
    }
    if (n->has_region) { /* region: 3 fields */
        put_s(w, "region");
        f_i(w, i);
        f_hex(w, n->region_hash, 8);
        put_c(w, '\n');
    }
}

/* lvprobe: 3 fields; frame: 4 fields. */
static void lines_head(wr_t *w, const lvprobe_t *p)
{
    put_s(w, "lvprobe\t1");
    f_i(w, p->count);
    put_c(w, '\n');
    if (p->has_frame) {
        put_s(w, "frame");
        f_i(w, p->frame_w);
        f_i(w, p->frame_h);
        f_hex(w, p->frame_crc, 8);
        put_c(w, '\n');
    }
}

static lvprobe_status_t finish(const wr_t *w, size_t *len)
{
    bool ok = w->len < w->cap;
    *len = w->len;
    if (w->cap > 0u) {
        w->buf[ok ? w->len : 0u] = '\0';
    }
    return ok ? LVPROBE_OK : LVPROBE_ERR_TRUNC;
}

/* Only the facts of a walk that succeeded and is still current are written (a failed walk is no empty tree). */
static lvprobe_status_t start(const lvprobe_t *p, char *buf, size_t *len, wr_t *w)
{
    if (p == NULL || !p->open || buf == NULL || len == NULL) {
        return LVPROBE_ERR_ARG;
    }
    w->buf = buf;
    w->len = 0;
    *len = 0;
    return lvp_walk_valid(p) ? LVPROBE_OK : LVPROBE_ERR_STALE;
}

lvprobe_status_t lvprobe_encode_head(const lvprobe_t *p, char *buf, size_t cap, size_t *len)
{
    wr_t w;
    lvprobe_status_t st = start(p, buf, len, &w);
    if (st != LVPROBE_OK) {
        return st;
    }
    w.cap = cap;
    lines_head(&w, p);
    return finish(&w, len);
}

lvprobe_status_t lvprobe_encode_node(const lvprobe_t *p, uint16_t index, char *buf, size_t cap, size_t *len)
{
    wr_t w;
    lvprobe_status_t st = start(p, buf, len, &w);
    if (st != LVPROBE_OK || index >= p->count) {
        return st != LVPROBE_OK ? st : LVPROBE_ERR_ARG;
    }
    w.cap = cap;
    lines_node(&w, p, index);
    return finish(&w, len);
}

lvprobe_status_t lvprobe_encode(const lvprobe_t *p, char *buf, size_t cap, size_t *len)
{
    wr_t w;
    uint16_t i;
    lvprobe_status_t st = start(p, buf, len, &w);
    if (st != LVPROBE_OK) {
        return st;
    }
    w.cap = cap;
    lines_head(&w, p);
    for (i = 0; i < p->count; i++) {
        lines_node(&w, p, i);
    }
    return finish(&w, len);
}
