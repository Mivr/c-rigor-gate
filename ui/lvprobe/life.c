/* gate//ui/lvprobe: the lifecycle log (5) and the observed screens. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/display/lv_display_private.h"

/* The node of `addr` in the last walk: a live one, else a deleted one whose address was not reused since (a
 * child is deleted after its parent's LV_EVENT_DELETE, while the parent's memory still exists). */
/* The node of `addr` in the last walk: a live one, else a deleted one whose address was not reused since (a
 * child is deleted after its parent's LV_EVENT_DELETE, while the parent's memory still exists). */
static int16_t find_addr(const lvprobe_t *p, const void *addr)
{
    int32_t at = lvp_find_addr(p, addr, false);
    if (at == LVPROBE_NONE || p->cfg.nodes[at].reused) {
        return (int16_t)LVPROBE_NONE;
    }
    return (int16_t)at;
}

static void forget_addr(lvprobe_t *p, const void *addr)
{
    int32_t at = lvp_find_addr(p, addr, false);
    if (at != LVPROBE_NONE && p->cfg.nodes[at].obj == NULL) {
        p->cfg.nodes[at].reused = true;
    }
}

static void life_push(lvprobe_t *p, bool created, bool late, const lv_obj_t *obj)
{
    lvprobe_life_t *e;
    p->life_seq++;
    if (p->life_count >= p->cfg.life_cap) {
        p->life_lost++;
        return;
    }
    e = &p->cfg.life[p->life_count];
    p->life_count++;
    e->seq = p->life_seq;
    e->created = created ? 1u : 0u;
    e->late = late ? 1u : 0u;
    e->node = created ? (int16_t)LVPROBE_NONE : find_addr(p, obj);
    e->parent = find_addr(p, lv_obj_get_parent(obj));
    e->class_name = lvp_class_name(obj);
}

static void log_subtree(lvprobe_t *p, lv_obj_t *root, bool late)
{
    lv_obj_t *obj = root;
    int32_t depth = 0;
    uint32_t visits = 0;

    while (obj != NULL && visits < LVP_VISIT_CAP) {
        forget_addr(p, obj); /* a new object at the address of a deleted node is not that node */
        life_push(p, true, late, obj);
        visits++;
        obj = lvp_next(obj, root, &depth);
    }
}

void lvp_on_created(lvprobe_t *p, lv_obj_t *child)
{
    log_subtree(p, child, false);
    if (lvp_attach_tree(p, child) != LVPROBE_OK) {
        p->fault = LVPROBE_ERR_LVGL;
    }
}

static void forget_screen(lvprobe_t *p, uint16_t i)
{
    p->screen_count--;
    p->cfg.screens[i] = p->cfg.screens[p->screen_count];
    p->cfg.screens[p->screen_count] = NULL;
}

void lvp_on_deleted(lvprobe_t *p, lv_obj_t *obj)
{
    int32_t at = lvprobe_find(p, obj);
    uint16_t i;
    life_push(p, false, false, obj);
    if (at != LVPROBE_NONE) {
        p->cfg.nodes[at].obj = NULL;
    }
    for (i = 0; i < p->screen_count; i++) {
        if (p->cfg.screens[i] == obj) {
            forget_screen(p, i);
            break;
        }
    }
}

static bool observed(const lvprobe_t *p, const lv_obj_t *screen)
{
    uint16_t i;
    for (i = 0; i < p->screen_count; i++) {
        if (p->cfg.screens[i] == screen) {
            return true;
        }
    }
    return false;
}

static bool on_display(const lv_display_t *d, const lv_obj_t *screen)
{
    uint32_t i;
    for (i = 0; i < d->screen_cnt; i++) {
        if (d->screens[i] == screen) {
            return true;
        }
    }
    return false;
}

lvprobe_status_t lvp_scan_screens(lvprobe_t *p, bool log)
{
    const lv_display_t *d = p->disp;
    uint32_t i;
    uint16_t k = 0;
    while (k < p->screen_count) { /* a screen deleted without our callback (removed by the app) */
        if (on_display(d, p->cfg.screens[k])) {
            k++;
        } else {
            forget_screen(p, k);
        }
    }
    for (i = 0; i < d->screen_cnt; i++) {
        lv_obj_t *screen = d->screens[i];
        lvprobe_status_t st;
        if (screen == NULL || observed(p, screen)) {
            continue;
        }
        if (p->screen_count >= p->cfg.max_screens) {
            return LVPROBE_ERR_FULL;
        }
        p->cfg.screens[p->screen_count] = screen;
        p->screen_count++;
        if (log) {
            p->gen++;
            log_subtree(p, screen, true);
        }
        st = lvp_attach_tree(p, screen);
        if (st != LVPROBE_OK) {
            return st;
        }
    }
    return LVPROBE_OK;
}

lvprobe_status_t lvprobe_life(lvprobe_t *p, lvprobe_life_t *out, uint16_t cap, uint16_t *n, uint32_t *lost)
{
    uint16_t i;
    uint16_t take;
    lvprobe_status_t st;
    if (p == NULL || !p->open || n == NULL || lost == NULL || (out == NULL && cap > 0u)) {
        return LVPROBE_ERR_ARG;
    }
    st = p->disp_gone ? LVPROBE_ERR_GONE : lvp_scan_screens(p, true); /* the queued events stay readable */
    take = p->life_count < cap ? p->life_count : cap;
    for (i = 0; i < take; i++) {
        out[i] = p->cfg.life[i];
    }
    for (i = take; i < p->life_count; i++) { /* the rest stays queued, oldest first */
        p->cfg.life[i - take] = p->cfg.life[i];
    }
    p->life_count = (uint16_t)(p->life_count - take);
    *n = take;
    *lost = p->life_lost;
    p->life_lost = 0;
    if (st == LVPROBE_OK && p->fault != LVPROBE_OK) {
        st = p->fault;
        p->fault = LVPROBE_OK;
    }
    if (st != LVPROBE_OK) {
        return st;
    }
    return *lost > 0u ? LVPROBE_ERR_OVERFLOW : LVPROBE_OK;
}

uint16_t lvprobe_life_pending(const lvprobe_t *p)
{
    return (p == NULL || !p->open) ? 0u : p->life_count;
}
