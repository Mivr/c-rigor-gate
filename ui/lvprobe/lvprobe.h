/* gate//ui/lvprobe: the rendered-stage observer of the UI gate (P004 §2.1 O3 and O4; U02).
 *
 * Reads what LVGL laid out and drew, through LVGL's own paths only (H6): the object tree after layout, the label
 * layout LVGL computed, the glyph boxes LVGL's own label draw code places (`lv_obj_redraw` of the label into a
 * probe-owned layer that is never rendered, then `lv_draw_label_iterate_characters` on the task LVGL created), the
 * production pointer indev hit-test, and the pixels of the real flush in the display's buffer.
 *
 * Memory: everything lives in the caller's `lvprobe_t` (static storage) plus the scratch pixels handed to
 * `lvprobe_open`. LVGL allocates from its own pool: one event descriptor per observed object (and on the display),
 * the probe's indev when it creates one, and the draw tasks of one label at a time during a walk (freed at once).
 * All loops are bounded by the capacities below. No product types. Reference: docs/ui-lvprobe.md (with the text
 * format of `lvprobe_encode`).
 *
 * Reuse: the probe main of gate//ui/model (U03) and every `ui-*` gate that reads O3/O4 facts. */
#ifndef UI_LVPROBE_LVPROBE_H
#define UI_LVPROBE_LVPROBE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "lvgl.h"

#define LVPROBE_FONT_UNMAPPED 0xFFFFu
#define LVPROBE_NONE (-1)

/* Capacities are open-time configuration (lvprobe_config_t); these are the documented defaults. */
enum {
    LVPROBE_DEFAULT_NODES = 512,   /* objects in one walk (at most 32767) */
    LVPROBE_DEFAULT_TEXT = 16384,  /* bytes of all label texts of one walk (drawn and original), NULs included */
    LVPROBE_DEFAULT_SCREENS = 16,  /* screens of the display the probe observes */
    LVPROBE_DEFAULT_LIFE = 1024,   /* lifecycle ring: a screen switch of 512 objects deleted and 512 created */
    LVPROBE_MAX_DEPTH = 32,        /* nesting depth of the walked tree (a root has depth 0), fixed */
    LVPROBE_MAX_FONTS = 16,        /* font identities the caller can map, fixed */
    LVPROBE_LINE_FIXED = 1024      /* bytes of a node's encoded lines besides its escaped strings (see encode) */
};

typedef enum {
    LVPROBE_OK = 0,
    LVPROBE_ERR_ARG,      /* NULL pointer, closed or already open probe, index or point out of range */
    LVPROBE_ERR_FULL,     /* a capacity above was exceeded (nodes, depth, text bytes, fonts, screens, scratch) */
    LVPROBE_ERR_TRUNC,    /* the caller's output buffer is too small; its content is not a valid result */
    LVPROBE_ERR_FORMAT,   /* the display does not render into one full-size XRGB8888 buffer in DIRECT mode */
    LVPROBE_ERR_LVGL,     /* LVGL refused something (indev, event registration, a draw task) */
    LVPROBE_ERR_GONE,     /* the node's object was deleted after the walk */
    LVPROBE_ERR_UNSTABLE, /* ink attribution changed the frame, a walked node's coords or the focus */
    LVPROBE_ERR_OVERFLOW, /* lifecycle events were lost since the previous `lvprobe_life` */
    LVPROBE_ERR_UNSETTLED,/* the display has dirty areas or pending layout: call lvprobe_settle first */
    LVPROBE_ERR_STALE,    /* objects were created or deleted, or the screen changed, since the last walk */
    LVPROBE_ERR_BLOCKED,  /* LVGL did not process the tap (before it: indev disabled, a screen-load animation
                           * running, waiting for a release; or the release itself was not processed) */
    LVPROBE_ERR_UNSUPPORTED /* a label LVGL draws through a sub-layer (drop shadow, layered child): not measured */
} lvprobe_status_t;

/* One object of the last walk. Read-only for the caller. Boxes are LVGL areas (inclusive corners, absolute display
 * coordinates, untransformed: style transforms are not applied); a box with x2 < x1 or y2 < y1 is empty. The index
 * of a node is its position in walk order: it is not stable across walks of different trees, so judges key nodes
 * through the scene, never through the index. */
typedef struct {
    lv_obj_t *obj;             /* NULL once LVGL deleted it; never dereference it yourself */
    bool seen;                 /* private: reached in the last liveness traversal */
    const void *addr;          /* private: the object's address, kept after deletion for parent lookups */
    const char *class_name;    /* LVGL's class name ("lv_obj", "lv_label", "lv_button", "lv_image") */
    int16_t parent;            /* index of the parent node, LVPROBE_NONE for a root (layer or screen) */
    int16_t clip;              /* nearest ancestor whose child clip box does not contain `coords`, or NONE */
    int16_t scroll;            /* nearest ancestor that can scroll (scrollable flag and content beyond it), or NONE */
    uint8_t depth;
    bool hidden;               /* the object's own LV_OBJ_FLAG_HIDDEN */
    bool clickable;            /* the object's own LV_OBJ_FLAG_CLICKABLE */
    lv_area_t coords;          /* absolute coordinates after layout */
    int32_t scroll_x, scroll_y;/* scroll offsets of `scroll` (lv_obj_get_scroll_x/y), 0 without one */
    uint32_t bg_rgb;           /* main-part bg colour as drawn (lv_obj_get_style_bg_color_filtered), 0xRRGGBB */
    uint8_t bg_opa;            /* main-part bg_opa style */
    uint8_t bg_opa_drawn;      /* bg_opa x own and inherited opa x own and ancestors' opa_layered (0..255) */
    bool bg_grad;              /* a bg gradient is set */
    bool bg_image;             /* a bg image is set */
    /* labels only (is_label: lv_label or a subclass) */
    bool is_label;
    const char *text;          /* the text LVGL draws (with dots in DOTS mode), NUL-terminated copy */
    const char *full_text;     /* the label's own text (dots reverted); equals `text` unless `dotted` */
    bool dotted;               /* DOTS mode replaced the end of the text by dots */
    const lv_font_t *font;     /* resolved main-part font */
    uint16_t font_id;          /* the caller's id for `font` (lvprobe_map_font) or LVPROBE_FONT_UNMAPPED */
    int32_t line_height;       /* lv_font_get_line_height(font) */
    uint8_t align;             /* main-part text align style (lv_text_align_t) */
    uint8_t align_drawn;       /* the alignment of the label draw task (after auto/bidi and the scroll rule) */
    uint8_t long_mode;         /* lv_label_long_mode_t */
    int32_t lines;             /* laid-out line count of `text` */
    lv_point_t natural;        /* lv_text_get_size(full_text) with no width limit */
    lv_point_t laid_out;       /* size of `text` laid out to the label's content width */
    /* verdict facts of the walk (labels only) */
    bool drawn;                /* LVGL's label draw code created a label draw task for it */
    bool has_glyphs;           /* at least one glyph box */
    lv_area_t glyphs;          /* union of the per-glyph boxes, unclipped */
    lv_area_t visible;         /* the clip area of that draw task (union over its tasks) */
    uint16_t missing;          /* glyphs drawn as placeholders (no font has them) */
    bool clipped;              /* glyphs not inside visible; or text whose content box no clip leaves visible */
    /* lvprobe_ink */
    bool has_ink;
    bool unstable;             /* the last lvprobe_ink of this node returned LVPROBE_ERR_UNSTABLE */
    uint32_t ink;              /* pixels that change when the node (and its subtree) is not drawn */
    lv_area_t ink_box;         /* bounding box of those pixels (empty when ink == 0) */
    uint32_t ink_lo, ink_hi;   /* darkest and lightest drawn pixel among them, 0xRRGGBB (luma order) */
    uint32_t bg_lo, bg_hi;     /* darkest and lightest pixel behind them (the frame without the node) */
    /* lvprobe_frame */
    bool has_region;
    uint32_t region_hash;      /* FNV-1a of the pixels of coords inside the display */
} lvprobe_node_t;

typedef struct {
    uint32_t seq;              /* running number of the event since lvprobe_open */
    uint8_t created;           /* 1: created, 0: deleted */
    uint8_t late;              /* 1: found later on a screen the probe had not observed (see docs) */
    int16_t node;              /* index of the object in the last walk, or NONE (always NONE for a creation) */
    int16_t parent;            /* index of its parent in the last walk, or NONE */
    const char *class_name;
} lvprobe_life_t;

typedef struct {
    bool pressed;              /* LVGL's indev found an object under the point on press */
    lv_obj_t *pressed_obj;     /* that object (compare only) */
    int32_t pressed_node;      /* its index in the last walk, or NONE */
    bool clicked;              /* some object received LV_EVENT_CLICKED from the tap */
    lv_obj_t *obj;             /* that object (compare only, it may be gone) */
    int32_t node;              /* its index in the last walk, or NONE */
} lvprobe_hit_t;

/* Open-time configuration: the caller's storage and its capacities. Every pointer is required. */
typedef struct {
    lvprobe_node_t *nodes;     /* max_nodes nodes */
    uint16_t max_nodes;
    char *text;                /* text_bytes bytes */
    size_t text_bytes;
    lvprobe_life_t *life;      /* life_cap entries */
    uint16_t life_cap;
    lv_obj_t **screens;        /* max_screens entries */
    uint16_t max_screens;
    uint32_t *scratch;         /* scratch_px pixels for lvprobe_ink (a node's box + ext draw size) */
    size_t scratch_px;
    lv_indev_t *indev;         /* the product's pointer indev for taps, or NULL for a probe-owned one */
} lvprobe_config_t;

/* The probe. Caller-owned (static storage, zero-initialised before the first open); all fields are private. */
typedef struct {
    bool open;
    lvprobe_status_t fault;    /* sticky error raised inside an LVGL callback, reported by the next walk/life */
    lv_display_t *disp;
    lvprobe_config_t cfg;
    bool own_indev;
    lv_indev_read_cb_t product_read;
    lv_point_t press_at;
    bool pressed;
    bool tapping;
    lvprobe_hit_t hit;
    uint32_t flushes;
    uint32_t gen;              /* structural changes seen */
    uint32_t walk_gen;
    bool walked;
    lv_obj_t *walk_screen;
    int32_t glyph_node;
    uint16_t count;
    size_t text_used;
    const lv_font_t *fonts[LVPROBE_MAX_FONTS];
    uint16_t font_ids[LVPROBE_MAX_FONTS];
    uint16_t font_count;
    uint16_t screen_count;
    uint16_t life_count;
    uint32_t life_lost;
    uint32_t life_seq;
    bool has_frame;
    uint32_t frame_crc;
    int32_t frame_w, frame_h;
    lv_layer_t layer;          /* the never-rendered layer label draw tasks are created on (user_data: the probe) */
} lvprobe_t;

/* Open a probe on `disp` with `cfg` (copied). The display needs its refresh timer and a full-size XRGB8888 buffer
 * in DIRECT mode for frame facts (LVPROBE_ERR_FORMAT otherwise). With `cfg->indev` taps go through the product's
 * indev (its read callback is replaced for the two reads of a tap, nothing else); with NULL the probe creates one.
 * Starts observing object creation and deletion on every screen and layer. An open probe is LVPROBE_ERR_ARG. */
lvprobe_status_t lvprobe_open(lvprobe_t *p, lv_display_t *disp, const lvprobe_config_t *cfg);

/* Stop observing; delete the probe's own indev. Safe after the display (or the indev) was deleted: the probe then
 * finds neither in LVGL's lists and touches neither. */
void lvprobe_close(lvprobe_t *p);

/* Give `font` the identity `id` in walk facts (at most LVPROBE_MAX_FONTS fonts). */
lvprobe_status_t lvprobe_map_font(lvprobe_t *p, const lv_font_t *font, uint16_t id);

/* Let LVGL refresh the display once (`lv_refr_now`: animations advanced by the ticks elapsed, layout, dirty areas;
 * no other timer). `*flushed` says whether anything was flushed: a settled, quiet frame is one where it is false. */
lvprobe_status_t lvprobe_settle(lvprobe_t *p, bool *flushed);

/* 1 (O3 tree) and `clipped` (2). Needs a settled display (LVPROBE_ERR_UNSETTLED otherwise); renders nothing and
 * flushes nothing. Walks bottom layer, active screen, top layer and sys layer depth-first. Replaces the last walk. */
lvprobe_status_t lvprobe_walk(lvprobe_t *p);

uint16_t lvprobe_count(const lvprobe_t *p);
const lvprobe_node_t *lvprobe_node(const lvprobe_t *p, uint16_t index);   /* NULL when out of range */
int32_t lvprobe_find(const lvprobe_t *p, const lv_obj_t *obj);              /* index or LVPROBE_NONE */

/* 2 (ink) and the luminance samples of 4: stop the node from being drawn (its own `hidden` bit, set and cleared
 * directly: no layout mark, no focus move, no style change, no allocation), refresh, diff its box (coords + ext draw size),
 * restore, refresh, and check that both refreshes flushed and settled and that the frame, every walked node's coords,
 * the focus and the tree are unchanged. A node LVGL does not draw (hidden, transparent, off-screen) has ink 0 without
 * a refresh. Needs a settled display and a current walk. */
lvprobe_status_t lvprobe_ink(lvprobe_t *p, uint16_t index);

/* 3, input injection: press and release at (x, y) (inside the display) through the pointer indev, reset first so
 * that every tap is a first single click. Needs a current walk. Product handlers run; settle afterwards. */
lvprobe_status_t lvprobe_hit(lvprobe_t *p, int32_t x, int32_t y, lvprobe_hit_t *out);

/* 3, query: the object LVGL's pointer search (lv_indev_search_obj over sys layer, top layer, active screen, bottom
 * layer, the order of the pointer indev) finds at (x, y). Sends no input event and changes nothing. */
lvprobe_status_t lvprobe_hit_test(lvprobe_t *p, int32_t x, int32_t y, int32_t *node, lv_obj_t **obj);

/* 4: frame CRC (FNV-1a over the B, G, R bytes of every pixel, row-major) and every node's region hash. No redraw;
 * needs a settled display and a current walk. */
lvprobe_status_t lvprobe_frame(lvprobe_t *p);
uint32_t lvprobe_frame_crc(const lvprobe_t *p);

/* 4: copy `box` (inside the display) as RGBA8888 rows into `rgba`; `*len` = bytes written. */
lvprobe_status_t lvprobe_crop(const lvprobe_t *p, const lv_area_t *box, uint8_t *rgba, size_t cap, size_t *len);

/* 5: the oldest lifecycle events since the last call, at most `cap` (the rest stays queued: call again while
 * lvprobe_life_pending is not 0). `*lost` counts events the ring could not hold; then the status is
 * LVPROBE_ERR_OVERFLOW. Call it every frame. */
lvprobe_status_t lvprobe_life(lvprobe_t *p, lvprobe_life_t *out, uint16_t cap, uint16_t *n, uint32_t *lost);
uint16_t lvprobe_life_pending(const lvprobe_t *p);

/* 6: the facts of 1, 2 and 4 as ui-probe/1 record lines (docs/ui-lvprobe.md): printable ASCII, TAB-separated fields,
 * a fixed field count per line type, LF-terminated. `lvprobe_encode_head` writes the header (and frame) lines,
 * `lvprobe_encode_node` the lines of one node (at most LVPROBE_LINE_FIXED + 4 x the bytes of its class name, text and
 * full text), `lvprobe_encode` all of them. Each needs cap > the text length (a NUL follows); otherwise it returns
 * LVPROBE_ERR_TRUNC, the buffer holds an empty string and `*len` is the exact length needed. */
lvprobe_status_t lvprobe_encode_head(const lvprobe_t *p, char *buf, size_t cap, size_t *len);
lvprobe_status_t lvprobe_encode_node(const lvprobe_t *p, uint16_t index, char *buf, size_t cap, size_t *len);
lvprobe_status_t lvprobe_encode(const lvprobe_t *p, char *buf, size_t cap, size_t *len);

#endif /* UI_LVPROBE_LVPROBE_H */
