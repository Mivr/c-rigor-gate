/* gate//ui/lvprobe: the lifecycle log (5) and the observed screens. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/display/lv_display_private.h"

/* The node of `addr` in the last walk: a live one, else a deleted one whose address was not reused since (a
 * child is deleted after its parent's LV_EVENT_DELETE, while the parent's memory still exists). */
static int16_t find_addr(const lvprobe_t *p, const void *addr)
{
    int32_t live = lvprobe_find(p, addr);
    uint16_t i;
    if (live != LVPROBE_NONE || addr == NULL) {
        return (int16_t)live;
    }
    for (i = 0; i < p->count; i++) {
        if (p->nodes[i].obj == NULL && p->nodes[i].addr == addr) {
            return (int16_t)i;
        }
    }
    return (int16_t)LVPROBE_NONE;
}

static void forget_addr(lvprobe_t *p, const void *addr)
{
    uint16_t i;
    for (i = 0; i < p->count; i++) {
        if (p->nodes[i].obj == NULL && p->nodes[i].addr == addr) {
            p->nodes[i].addr = NULL;
        }
    }
}

static void life_push(lvprobe_t *p, bool created, bool late, const lv_obj_t *obj)
{
    lvprobe_life_t *e;
    p->life_seq++;
    if (p->life_count >= LVPROBE_LIFE_CAP) {
        p->life_lost++;
        return;
    }
    e = &p->life[p->life_count];
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
    p->screens[i] = p->screens[p->screen_count];
    p->screens[p->screen_count] = NULL;
}

void lvp_on_deleted(lvprobe_t *p, lv_obj_t *obj)
{
    int32_t at = lvprobe_find(p, obj);
    uint16_t i;
    life_push(p, false, false, obj);
    if (at != LVPROBE_NONE) {
        p->nodes[at].obj = NULL;
    }
    for (i = 0; i < p->screen_count; i++) {
        if (p->screens[i] == obj) {
            forget_screen(p, i);
            break;
        }
    }
}

static bool observed(const lvprobe_t *p, const lv_obj_t *screen)
{
    uint16_t i;
    for (i = 0; i < p->screen_count; i++) {
        if (p->screens[i] == screen) {
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
        if (on_display(d, p->screens[k])) {
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
        if (p->screen_count >= LVPROBE_MAX_SCREENS) {
            return LVPROBE_ERR_FULL;
        }
        p->screens[p->screen_count] = screen;
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
    st = lvp_scan_screens(p, true);
    take = p->life_count < cap ? p->life_count : cap;
    for (i = 0; i < take; i++) {
        out[i] = p->life[i];
    }
    *n = take;
    *lost = p->life_lost + (uint32_t)(p->life_count - take);
    p->life_count = 0;
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
