/* `frame` (U05a; docs/ui-model.md, "Frame facts"): the rendered tree, the frame checksum and the lifecycle events since
 * the previous frame, read through gate//ui/lvprobe (docs/ui-lvprobe.md). This file owns lvprobe's storage, opens it on
 * the session's display, sequences the snapshot and writes the `life` lines (lvprobe has no encoder for them). A reply
 * is assembled whole before anything is written: an error is one `err` line, never a partial reply. Static memory
 * only; no recursion. */
#include <stdio.h>
#include <string.h>

#include "ui/model/probe.h"

static lvprobe_node_t g_nodes[PROBE_LV_NODES];
static char g_text[PROBE_LV_TEXT];
static lvprobe_life_t g_ring[PROBE_LV_LIFE];
static lv_obj_t *g_screens[PROBE_LV_SCREENS];
static uint32_t g_ink_px[PROBE_LV_SCRATCH_PX];
static lvprobe_life_t g_life[PROBE_LV_LIFE];   /* the events drained for the frame being taken */

typedef struct {
    uint16_t lives;       /* events in g_life */
    uint16_t indexed;     /* events g_life[0..indexed) were drained before any walk of this command */
    bool walked;
    probe_work_t work;    /* the last uim_settle */
} snap_t;

/* ---- the display and the indev ------------------------------------------------------------------------------- */

/* `disp` is one of LVGL's displays, compared by address only (nothing is dereferenced). */
static bool listed(const lv_display_t *disp)
{
    lv_display_t *d = lv_display_get_next(NULL);
    uint32_t guard = 0;
    while (d != NULL && guard < 256u) {
        if (d == disp) {
            return true;
        }
        d = lv_display_get_next(d);
        guard++;
    }
    return false;
}

/* The display's one pointer indev (`*out`, NULL when it has none: lvprobe creates its own); false if it has several. */
static bool pointer_of(lv_display_t *disp, lv_indev_t **out)
{
    lv_indev_t *i = lv_indev_get_next(NULL);
    uint32_t guard = 0;
    unsigned found = 0;
    *out = NULL;
    while (i != NULL && guard < 256u) {
        if (lv_indev_get_display(i) == disp && lv_indev_get_type(i) == LV_INDEV_TYPE_POINTER) {
            *out = i;
            found++;
        }
        i = lv_indev_get_next(i);
        guard++;
    }
    return found <= 1u && i == NULL;
}

/* Opens lvprobe on a listed display. FORMAT: an ambiguous pointer (several pointer indevs) or a display with more
 * pixels than the ink scratch (so that ink can never run out of it later). */
static lvprobe_status_t attach(probe_t *p, lv_display_t *disp)
{
    lvprobe_config_t cfg;
    lvprobe_status_t st;
    uint64_t px = (uint64_t)lv_display_get_horizontal_resolution(disp) *
                  (uint64_t)lv_display_get_vertical_resolution(disp);
    if (!pointer_of(disp, &cfg.indev) || px > PROBE_LV_SCRATCH_PX) {
        return LVPROBE_ERR_FORMAT;
    }
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
    st = lvprobe_open(p->lv, disp, &cfg);
    p->disp = st == LVPROBE_OK ? disp : NULL;
    return st;
}

/* ---- the snapshot -------------------------------------------------------------------------------------------- */

/* Moves the queued lifecycle events to g_life; FULL when more are queued than g_life still holds. Events drained after
 * a walk of this command may carry indexes of that walk, which is never reported: they lose their indexes. */
static lvprobe_status_t drain(probe_t *p, snap_t *s)
{
    uint16_t got = 0;
    uint32_t lost = 0;
    lvprobe_status_t st;
    if (s->walked && s->indexed > s->lives) {
        s->indexed = s->lives;
    }
    st = lvprobe_life(p->lv, &g_life[s->lives], (uint16_t)(PROBE_LV_LIFE - s->lives), &got, &lost);
    if (got > PROBE_LV_LIFE - s->lives) {
        return LVPROBE_ERR_ARG;
    }
    s->lives = (uint16_t)(s->lives + got);
    if (st == LVPROBE_OK && lvprobe_life_pending(p->lv) != 0u) {
        st = LVPROBE_ERR_FULL;
    }
    return st;
}

/* One try: life, LVGL settle, the product's due work (if any ran, the state moved: STALE), walk, frame facts. */
static lvprobe_status_t try_once(probe_t *p, snap_t *s)
{
    bool flushed = false;
    bool worked = false;
    lvprobe_status_t st = drain(p, s);
    st = st == LVPROBE_OK ? probe_lv_settle(p, &flushed) : st;
    if (st != LVPROBE_OK) {
        return st;
    }
    s->work = probe_model_settle(p, &worked);
    if (s->work != PROBE_WORK_OK || worked) {
        return LVPROBE_ERR_STALE;
    }
    s->walked = true;
    st = lvprobe_walk(p->lv);
    st = st == LVPROBE_OK ? lvprobe_frame(p->lv) : st;
    if (st == LVPROBE_OK && lvprobe_life_pending(p->lv) != 0u) {
        st = LVPROBE_ERR_STALE;   /* an event arrived during the snapshot: take it with a fresh walk */
    }
    return st;
}

/* Retried while the state moved under the calls; still moving after PROBE_FRAME_TRIES is model-contract. */
static lvprobe_status_t snapshot(probe_t *p, snap_t *s)
{
    unsigned t;
    lvprobe_status_t st = LVPROBE_ERR_STALE;
    for (t = 0; t < PROBE_FRAME_TRIES && st == LVPROBE_ERR_STALE && s->work == PROBE_WORK_OK; t++) {
        st = try_once(p, s);
        st = st == LVPROBE_ERR_UNSETTLED ? LVPROBE_ERR_STALE : st;
    }
    return st;
}

/* ---- the reply ----------------------------------------------------------------------------------------------- */

/* The head, every node (streamed: one encoder call per node, at its offset) and the life lines into out[0..*at). */
static lvprobe_status_t encode(const probe_t *p, const snap_t *s, char *out, size_t cap, size_t *at)
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
    for (i = 0; i < s->lives && st == LVPROBE_OK; i++) {
        st = probe_life_line(&g_life[i], i < s->indexed, out, cap, at);
    }
    return st;
}

/* Takes the snapshot of the attached display and writes it; LVGL's tick must not move meanwhile (the gate owns it). */
static bool take(probe_t *p, snap_t *s)
{
    size_t cap = 0;
    char *out = probe_payload(&cap);
    size_t at = 0;
    long lines = 0;
    uint32_t tick = lv_tick_get();
    lvprobe_status_t st = snapshot(p, s);
    if (s->work == PROBE_WORK_FAILED) {
        p->opened = false;
        return probe_reply_plain("frame", false);
    }
    st = (s->work == PROBE_WORK_CONTRACT || lv_tick_get() != tick) ? LVPROBE_ERR_FORMAT : st;
    st = st == LVPROBE_OK ? encode(p, s, out, cap, &at) : st;
    if (st != LVPROBE_OK) {
        return probe_fatal(p, probe_why(st));
    }
    lines = probe_check_records(NULL, out, at);
    if (lines < 0) {
        return probe_fatal(p, "internal");
    }
    p->framed = true;
    return probe_reply_lines("frame", (size_t)lines, at);
}

bool probe_cmd_frame(probe_t *p, char **arg)
{
    lv_display_t *disp = NULL;
    snap_t s;
    lvprobe_status_t st = LVPROBE_OK;
    (void)arg;
    p->framed = false;
    if (!uim_frame(p->model, &disp)) {
        p->opened = false;
        return probe_reply_plain("frame", false);
    }
    if (disp == NULL || !listed(disp) || (p->disp != NULL && disp != p->disp)) {
        return probe_fatal(p, "model-contract");   /* no display, one LVGL does not know, or another one */
    }
    st = p->disp == NULL ? attach(p, disp) : LVPROBE_OK;
    if (st != LVPROBE_OK) {
        return probe_fatal(p, probe_why(st));
    }
    s.lives = 0;
    s.indexed = PROBE_LV_LIFE;
    s.walked = false;
    s.work = PROBE_WORK_OK;
    return take(p, &s);
}
