/* gate//ui/lvprobe: the node index (nodes sorted by object address, binary search) and the liveness traversal. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ui/lvprobe/lvprobe.h"
#include "ui/lvprobe/lvprobe_int.h"

#include "src/display/lv_display_private.h"

/* Mark the nodes whose object is reached from the display's screens and layers (`reached`) and still carries the
 * probe's callback (`seen`). One traversal with an index stack, depth limited to the walk's (deeper objects are no
 * nodes); lookups by binary search. Only reached objects are dereferenced. */
static void scan_root(lvprobe_t *p, lv_obj_t *root)
{
    int32_t d = 0;
    uint32_t visits = 0;
    p->trav_obj[0] = root;
    p->trav_next[0] = 0;
    while (d >= 0 && visits < LVP_VISIT_CAP) {
        lv_obj_t *obj = p->trav_obj[d];
        if (p->trav_next[d] == 0u) {
            int32_t at = lvprobe_find(p, obj);
            visits++;
            if (at != LVPROBE_NONE) {
                p->cfg.nodes[at].reached = true;
                p->cfg.nodes[at].seen = lvp_has_cb(obj, p);
            }
        }
        if (d < LVPROBE_MAX_DEPTH && p->trav_next[d] < lv_obj_get_child_count(obj)) {
            p->trav_obj[d + 1] = lv_obj_get_child(obj, (int32_t)p->trav_next[d]);
            p->trav_next[d]++;
            d++;
            p->trav_next[d] = 0;
        } else {
            d--;
        }
    }
}

void lvp_live_scan(lvprobe_t *p)
{
    lv_obj_t *roots[3];
    uint32_t r;
    uint16_t i;
    for (i = 0; i < p->count; i++) {
        p->cfg.nodes[i].seen = false;
        p->cfg.nodes[i].reached = false;
    }
    if (p->disp_gone) {
        return;
    }
    roots[0] = p->disp->bottom_layer;
    roots[1] = p->disp->top_layer;
    roots[2] = p->disp->sys_layer;
    for (r = 0; r < p->disp->screen_cnt + 3u; r++) {
        lv_obj_t *root = r < p->disp->screen_cnt ? p->disp->screens[r] : roots[r - p->disp->screen_cnt];
        if (root != NULL) {
            scan_root(p, root);
        }
    }
}

static bool addr_less(const lvprobe_t *p, uint16_t a, uint16_t b)
{
    return (uintptr_t)p->cfg.nodes[a].addr < (uintptr_t)p->cfg.nodes[b].addr;
}

static void sift(lvprobe_t *p, uint16_t root, uint16_t n)
{
    lvprobe_node_t *v = p->cfg.nodes;
    uint32_t r = root;
    while (2u * r + 1u < n) {
        uint32_t c = 2u * r + 1u;
        uint16_t tmp;
        if (c + 1u < n && addr_less(p, v[c].by_addr, v[c + 1u].by_addr)) {
            c++;
        }
        if (!addr_less(p, v[r].by_addr, v[c].by_addr)) {
            return;
        }
        tmp = v[r].by_addr;
        v[r].by_addr = v[c].by_addr;
        v[c].by_addr = tmp;
        r = c;
    }
}

/* Heap sort of the node indexes by object address (no recursion, O(n log n)). */
void lvp_sort_nodes(lvprobe_t *p)
{
    lvprobe_node_t *v = p->cfg.nodes;
    uint16_t n = p->count;
    uint16_t i;
    for (i = 0; i < n; i++) {
        v[i].by_addr = i;
    }
    for (i = (uint16_t)(n / 2u); i > 0u; i--) {
        sift(p, (uint16_t)(i - 1u), n);
    }
    for (i = n; i > 1u; i--) {
        uint16_t tmp = v[0].by_addr;
        v[0].by_addr = v[i - 1u].by_addr;
        v[i - 1u].by_addr = tmp;
        sift(p, 0, (uint16_t)(i - 1u));
    }
    p->sorted = true;
}

/* By address: binary search over the sorted indexes after a walk, a scan during it. A deleted node never matches. */
int32_t lvp_find_addr(const lvprobe_t *p, const void *addr, bool live)
{
    uint32_t lo = 0;
    uint32_t hi = p->count;
    uint16_t i;
    if (addr == NULL) {
        return LVPROBE_NONE;
    }
    if (!p->sorted) {
        for (i = 0; i < p->count; i++) {
            if (p->cfg.nodes[i].addr == addr && (!live || p->cfg.nodes[i].obj != NULL)) {
                return (int32_t)i;
            }
        }
        return LVPROBE_NONE;
    }
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2u;
        const lvprobe_node_t *n = &p->cfg.nodes[p->cfg.nodes[mid].by_addr];
        if ((uintptr_t)n->addr < (uintptr_t)addr) {
            lo = mid + 1u;
        } else {
            hi = mid;
        }
    }
    if (lo < p->count) {
        uint16_t at = p->cfg.nodes[lo].by_addr;
        if (p->cfg.nodes[at].addr == addr && (!live || p->cfg.nodes[at].obj != NULL)) {
            return (int32_t)at;
        }
    }
    return LVPROBE_NONE;
}

int32_t lvprobe_find(const lvprobe_t *p, const lv_obj_t *obj)
{
    return p == NULL ? LVPROBE_NONE : lvp_find_addr(p, obj, true);
}

