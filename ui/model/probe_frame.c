/* The lvprobe seam of the probe (U05a; docs/ui-model.md, "Frame facts"): `frame` (the rendered tree, the frame checksum
 * and the lifecycle events since the previous frame), `ink`, `hit-test`, `tap` and `crop`. Every fact comes from
 * gate//ui/lvprobe (docs/ui-lvprobe.md); this file only sequences its calls, maps its statuses to replies and writes the
 * `life` lines (lvprobe has no encoder for them). A reply is assembled whole before anything is written: an error is one
 * `err` line, never a partial reply. Static memory only; no recursion. */
#include <stdio.h>
#include <string.h>

#include "ui/model/probe.h"

static lvprobe_node_t g_nodes[PROBE_LV_NODES];
static char g_text[PROBE_LV_TEXT];
static lvprobe_life_t g_ring[PROBE_LV_LIFE];
static lv_obj_t *g_screens[PROBE_LV_SCREENS];
static uint32_t g_ink_px[PROBE_LV_SCRATCH_PX];
static lvprobe_life_t g_life[PROBE_LV_LIFE];   /* the events drained for the frame being taken */
static char g_scratch[UIM_BUF_MAX];            /* one node's encoding (ink), or the RGBA bytes of a crop */

/* ---- statuses and replies ------------------------------------------------------------------------------------ */

static bool retry(lvprobe_status_t st)
{
    return st == LVPROBE_ERR_STALE || st == LVPROBE_ERR_UNSETTLED;
}

/* The `err` reason of an lvprobe status that ends a command: a capacity or the payload is `too-large`; a display the
 * probe cannot read, gone, or never quiet, current or stable is `model-contract`; anything else is `internal`. */
static const char *why(lvprobe_status_t st)
{
    if (st == LVPROBE_ERR_FULL || st == LVPROBE_ERR_OVERFLOW || st == LVPROBE_ERR_TRUNC) {
        return "too-large";
    }
    if (st == LVPROBE_ERR_FORMAT || st == LVPROBE_ERR_GONE || retry(st) || st == LVPROBE_ERR_UNSTABLE) {
        return "model-contract";
    }
    return "internal";
}

/* A failure of a call that may have changed the model: the session is poisoned. */
static bool fatal(probe_t *p, const char *reason)
{
    p->opened = false;
    p->framed = false;
    return probe_reply_err(p->cmd, reason);
}

/* A failure of a read-only call: the session goes on, but the frame is no longer trusted. */
static bool refuse(probe_t *p, const char *reason)
{
    p->framed = false;
    return probe_reply_err(p->cmd, reason);
}

/* `ok <name> <a>[ <b>]`: probe_reply_plain writes `ok ` and its name argument. */
static bool reply_words(const char *name, const char *a, const char *b)
{
    char line[64];
    int n = b != NULL ? snprintf(line, sizeof line, "%s %s %s", name, a, b) : snprintf(line, sizeof line, "%s %s", name, a);
    return (n > 0 && (size_t)n < sizeof line) ? probe_reply_plain(line, true) : probe_reply_err(name, "internal");
}

/* ---- opening and settling ------------------------------------------------------------------------------------ */

/* The product's pointer indev on `disp`: the first in LVGL's list, or NULL (lvprobe then creates its own). */
static lv_indev_t *pointer_of(lv_display_t *disp)
{
    lv_indev_t *i = lv_indev_get_next(NULL);
    uint32_t guard = 0;
    while (i != NULL && guard < 256u) {
        if (lv_indev_get_display(i) == disp && lv_indev_get_type(i) == LV_INDEV_TYPE_POINTER) {
            return i;
        }
        i = lv_indev_get_next(i);
        guard++;
    }
    return NULL;
}

static lvprobe_status_t attach(probe_t *p, lv_display_t *disp)
{
    lvprobe_config_t cfg;
    lvprobe_status_t st;
    cfg.nodes = g_nodes;
    cfg.max_nodes = PROBE_LV_NODES;
    cfg.text = g_text;
    cfg.text_bytes = sizeof g_text;
    cfg.life = g_ring;
    cfg.life_cap = PROBE_LV_LIFE;
    cfg.screens = g_screens;
    cfg.max_screens = PROBE_LV_SCREENS;
    cfg.scratch = g_ink_px;
    cfg.scratch_px = PROBE_LV_SCRATCH_PX;
    cfg.indev = pointer_of(disp);
    st = lvprobe_open(p->lv, disp, &cfg);
    p->disp = st == LVPROBE_OK ? disp : NULL;
    return st;
}

/* Refresh until a refresh flushes nothing (a quiet frame), at most PROBE_SETTLE_MAX times. */
static lvprobe_status_t settle(probe_t *p)
{
    unsigned i;
    for (i = 0; i < PROBE_SETTLE_MAX; i++) {
        bool flushed = true;
        lvprobe_status_t st = lvprobe_settle(p->lv, &flushed);
        if (st != LVPROBE_OK || !flushed) {
            return st;
        }
    }
    return LVPROBE_ERR_UNSETTLED;
}

/* Moves the queued lifecycle events to g_life[*n..]; FULL when more are queued than g_life still holds. */
static lvprobe_status_t drain(probe_t *p, uint16_t *n)
{
    uint16_t got = 0;
    uint32_t lost = 0;
    lvprobe_status_t st = lvprobe_life(p->lv, &g_life[*n], (uint16_t)(PROBE_LV_LIFE - *n), &got, &lost);
    if (got > PROBE_LV_LIFE - *n) {
        return LVPROBE_ERR_ARG;
    }
    *n = (uint16_t)(*n + got);
    if (st == LVPROBE_OK && lvprobe_life_pending(p->lv) != 0u) {
        st = LVPROBE_ERR_FULL;
    }
    return st;
}

/* Life, settle, walk and frame facts, retried while the state moved under the calls (stale or unsettled). */
static lvprobe_status_t snapshot(probe_t *p, uint16_t *lives)
{
    unsigned t;
    lvprobe_status_t st = LVPROBE_ERR_STALE;
    for (t = 0; t < PROBE_FRAME_TRIES && retry(st); t++) {
        st = drain(p, lives);
        if (st == LVPROBE_OK) {
            st = settle(p);
        }
        if (st == LVPROBE_OK) {
            st = lvprobe_walk(p->lv);
        }
        if (st == LVPROBE_OK) {
            st = lvprobe_frame(p->lv);
        }
        if (st == LVPROBE_OK && lvprobe_life_pending(p->lv) != 0u) {
            st = LVPROBE_ERR_STALE;   /* an event arrived during the snapshot: take it with a fresh walk */
        }
    }
    return st;
}

/* ---- frame --------------------------------------------------------------------------------------------------- */

/* `life`, 7 fields: seq, created|deleted, late, node, parent, class (node and parent: walk indexes or -1). */
static lvprobe_status_t life_line(const lvprobe_life_t *e, char *out, size_t cap, size_t *at)
{
    int n = snprintf(out + *at, cap - *at, "life\t%lu\t%s\t%u\t%d\t%d\t%s\n", (unsigned long)e->seq,
                     e->created != 0u ? "created" : "deleted", (unsigned)e->late, (int)e->node, (int)e->parent,
                     e->class_name != NULL ? e->class_name : "?");
    if (n <= 0 || (size_t)n >= cap - *at || (size_t)n > PROBE_LIFE_LINE_MAX) {
        return LVPROBE_ERR_TRUNC;
    }
    *at += (size_t)n;
    return LVPROBE_OK;
}

/* The head, every node (streamed: one encoder call per node, at its offset) and the life lines into out[0..*at). */
static lvprobe_status_t encode(const probe_t *p, uint16_t lives, char *out, size_t cap, size_t *at)
{
    size_t len = 0;
    uint16_t i;
    uint16_t count = lvprobe_count(p->lv);
    lvprobe_status_t st = lvprobe_encode_head(p->lv, out, cap, &len);
    *at = st == LVPROBE_OK ? len : 0u;
    for (i = 0; i < count && st == LVPROBE_OK; i++) {
        st = lvprobe_encode_node(p->lv, i, out + *at, cap - *at, &len);
        *at += st == LVPROBE_OK ? len : 0u;
    }
    for (i = 0; i < lives && st == LVPROBE_OK; i++) {
        st = life_line(&g_life[i], out, cap, at);
    }
    return st;
}

static bool cmd_frame(probe_t *p, char **arg)
{
    lv_display_t *disp = NULL;
    size_t cap = 0;
    char *out = probe_payload(&cap);
    size_t at = 0;
    uint16_t lives = 0;
    long lines = 0;
    lvprobe_status_t st = LVPROBE_OK;
    (void)arg;
    p->framed = false;
    if (!uim_frame(p->model, &disp)) {
        p->opened = false;
        return probe_reply_plain("frame", false);
    }
    if (disp == NULL || (p->disp != NULL && disp != p->disp)) {
        return fatal(p, "model-contract");   /* no display, or another one than lvprobe observes */
    }
    if (p->disp == NULL) {
        st = attach(p, disp);
    }
    st = st == LVPROBE_OK ? snapshot(p, &lives) : st;
    st = st == LVPROBE_OK ? encode(p, lives, out, cap, &at) : st;
    if (st != LVPROBE_OK) {
        return fatal(p, why(st));
    }
    lines = probe_check_records(NULL, out, at);
    if (lines < 0) {
        return fatal(p, "internal");
    }
    p->framed = true;
    return probe_reply_lines("frame", (size_t)lines, at);
}

/* ---- ink ----------------------------------------------------------------------------------------------------- */

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

/* One node: unstable or unsettled is settled and retried once; still unstable or transformed is data (`noink`). */
static lvprobe_status_t ink_one(probe_t *p, uint16_t i)
{
    unsigned t;
    lvprobe_status_t st = lvprobe_ink(p->lv, i);
    for (t = 0; t < PROBE_INK_RETRIES && (st == LVPROBE_ERR_UNSTABLE || st == LVPROBE_ERR_UNSETTLED); t++) {
        st = settle(p);
        st = st == LVPROBE_OK ? lvprobe_ink(p->lv, i) : st;
    }
    return (st == LVPROBE_ERR_UNSTABLE || st == LVPROBE_ERR_UNSUPPORTED) ? LVPROBE_OK : st;
}

static bool is_root(const probe_t *p, uint16_t i)
{
    const lvprobe_node_t *n = lvprobe_node(p->lv, i);
    return n == NULL || n->parent == LVPROBE_NONE;
}

/* `ink`: every node of the walk but the roots, in walk order; `ink <i>`: node i. */
static bool cmd_ink(probe_t *p, char **arg)
{
    uint64_t want = 0;
    uint16_t count = lvprobe_count(p->lv);
    uint16_t i;
    size_t cap = 0;
    char *out = probe_payload(&cap);
    size_t at = 0;
    long lines = 0;
    if (arg[0] != NULL && !probe_parse_u64(arg[0], &want)) {
        return probe_reply_err("ink", "bad-arguments");
    }
    if (!p->framed) {
        return probe_reply_err("ink", "no-frame");
    }
    if (arg[0] != NULL && (want >= count || is_root(p, (uint16_t)want))) {
        return probe_reply_err("ink", "bad-arguments");   /* no such node, or a screen or layer root */
    }
    for (i = arg[0] != NULL ? (uint16_t)want : 0u; i < count; i++) {
        lvprobe_status_t st = is_root(p, i) ? LVPROBE_OK : ink_one(p, i);
        st = (st == LVPROBE_OK && !is_root(p, i)) ? ink_line(p, i, out, cap, &at) : st;
        if (st != LVPROBE_OK) {
            return fatal(p, why(st));
        }
        if (arg[0] != NULL) {
            break;
        }
    }
    lines = probe_check_records(NULL, out, at);
    return lines >= 0 ? probe_reply_lines("ink", (size_t)lines, at) : fatal(p, "internal");
}

/* ---- hit-test and tap ---------------------------------------------------------------------------------------- */

/* Parses `x y` (decimal, `syntax`); then, on a frame, checks that the point lies inside the display. */
static bool point(const probe_t *p, char **arg, int32_t *x, int32_t *y, bool *syntax)
{
    uint64_t vx = 0;
    uint64_t vy = 0;
    *syntax = probe_parse_u64(arg[0], &vx) && probe_parse_u64(arg[1], &vy);
    if (!*syntax || !p->framed || vx >= (uint64_t)lv_display_get_horizontal_resolution(p->disp) ||
        vy >= (uint64_t)lv_display_get_vertical_resolution(p->disp)) {
        return false;
    }
    *x = (int32_t)vx;
    *y = (int32_t)vy;
    return true;
}

static bool point_err(const probe_t *p, bool syntax)
{
    return probe_reply_err(p->cmd, syntax && !p->framed ? "no-frame" : "bad-arguments");
}

/* `<index>` or `none` for a node of the walk; NULL if it does not fit. */
static const char *node_word(int32_t node, char *buf, size_t cap)
{
    int n = 0;
    if (node == LVPROBE_NONE) {
        return "none";
    }
    n = snprintf(buf, cap, "%ld", (long)node);
    return (n > 0 && (size_t)n < cap) ? buf : NULL;
}

/* What LVGL's own search finds at the point; nothing is pressed. Read-only: an error does not poison. */
static bool cmd_hit_test(probe_t *p, char **arg)
{
    int32_t x = 0;
    int32_t y = 0;
    int32_t node = LVPROBE_NONE;
    lv_obj_t *obj = NULL;
    bool syntax = false;
    char num[16];
    const char *word = NULL;
    lvprobe_status_t st;
    if (!point(p, arg, &x, &y, &syntax)) {
        return point_err(p, syntax);
    }
    st = lvprobe_hit_test(p->lv, x, y, &node, &obj);
    if (st == LVPROBE_ERR_BLOCKED) {
        return reply_words("hit-test", "blocked", NULL);
    }
    if (st != LVPROBE_OK || (obj != NULL && node == LVPROBE_NONE)) {
        return refuse(p, st != LVPROBE_OK ? why(st) : "internal");   /* an object outside the walk: never a guess */
    }
    word = node_word(obj != NULL ? node : LVPROBE_NONE, num, sizeof num);
    return word != NULL ? reply_words("hit-test", word, NULL) : refuse(p, "internal");
}

/* A press and release through the production pointer path, then a settle to a quiet frame. An input like `apply`: a
 * failure poisons; `blocked` (LVGL did not process it) does not. Reply: the pressed and the clicked node. */
static bool cmd_tap(probe_t *p, char **arg)
{
    int32_t x = 0;
    int32_t y = 0;
    bool syntax = false;
    lvprobe_hit_t hit;
    char a[16];
    char b[16];
    const char *pressed = NULL;
    const char *clicked = NULL;
    lvprobe_status_t st;
    lvprobe_status_t quiet;
    if (!point(p, arg, &x, &y, &syntax)) {
        return point_err(p, syntax);
    }
    p->framed = false;
    memset(&hit, 0, sizeof hit);
    st = lvprobe_hit(p->lv, x, y, &hit);
    quiet = (st == LVPROBE_OK || st == LVPROBE_ERR_BLOCKED) ? settle(p) : st;
    if (quiet != LVPROBE_OK) {
        return fatal(p, why(quiet));
    }
    if (st == LVPROBE_ERR_BLOCKED) {
        return reply_words("tap", "blocked", NULL);
    }
    pressed = hit.pressed ? node_word(hit.pressed_node, a, sizeof a) : "none";
    clicked = hit.clicked ? node_word(hit.node, b, sizeof b) : "none";
    if (pressed == NULL || clicked == NULL || (hit.pressed && hit.pressed_node == LVPROBE_NONE) ||
        (hit.clicked && hit.node == LVPROBE_NONE)) {
        return fatal(p, "internal");   /* an object outside the walk took the tap: never a guess */
    }
    return reply_words("tap", pressed, clicked);
}

/* ---- crop ---------------------------------------------------------------------------------------------------- */

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

/* RGBA8888 of a region of the current frame, one line of lowercase hex per row. Read-only. */
static bool cmd_crop(probe_t *p, char **arg)
{
    uint64_t v[4];
    size_t cap = 0;
    char *out = probe_payload(&cap);
    size_t len = 0;
    size_t at = 0;
    size_t row = 0;
    lv_area_t box;
    unsigned k;
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
    st = lvprobe_crop(p->lv, &box, (uint8_t *)(void *)g_scratch, sizeof g_scratch, &len);
    if (st != LVPROBE_OK || len != row * (size_t)v[3]) {
        return refuse(p, "internal");
    }
    for (k = 0; k < v[3]; k++) {
        probe_to_hex((const unsigned char *)&g_scratch[(size_t)k * row], row, out + at);
        at += 2u * row;
        out[at++] = '\n';
    }
    return probe_reply_lines("crop", (size_t)v[3], at);
}

/* ---- the entry point ----------------------------------------------------------------------------------------- */

typedef bool (*seam_fn_t)(probe_t *p, char **arg);

static const struct {
    const char *name;
    seam_fn_t run;
} SEAM[] = {
    {"frame", cmd_frame}, {"ink", cmd_ink}, {"hit-test", cmd_hit_test}, {"tap", cmd_tap}, {"crop", cmd_crop},
};

bool probe_cmd_frame(probe_t *p, char **arg)
{
    size_t i;
    for (i = 0; i < sizeof SEAM / sizeof SEAM[0]; i++) {
        if (strcmp(p->cmd, SEAM[i].name) == 0) {
            return SEAM[i].run(p, arg);
        }
    }
    return probe_reply_err(p->cmd, "internal");
}
