/* gate//ui/lvprobe: the rendered-stage observer of the UI gate (P004 §2.1 O3 and O4; U02).
 *
 * Reads what LVGL laid out and drew, through LVGL's own paths only (H6): the object tree after layout, the label
 * layout LVGL computed (`lv_text_get_size`, the label's laid-out size), the glyph boxes of the real label draw task
 * (`lv_draw_label_iterate_characters` on the task LVGL created, unclipped), the production pointer indev hit-test,
 * and the pixels of the real flush into the display's buffer. No re-implemented layout or hit-test.
 *
 * Memory: everything lives in the caller's `lvprobe_t` (static storage) plus the scratch pixels the caller hands to
 * `lvprobe_open`. LVGL itself allocates from its own pool: one event descriptor per observed object and one pointer
 * indev. All loops are bounded by the capacities below. No product types; `docs/ui-lvprobe.md` is the reference,
 * including the text format of `lvprobe_encode`.
 *
 * Reuse: the probe main of gate//ui/model (U03) and every `ui-*` gate that reads O3/O4 facts. */
#ifndef UI_LVPROBE_LVPROBE_H
#define UI_LVPROBE_LVPROBE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "lvgl.h"

enum {
    LVPROBE_MAX_NODES = 512,   /* objects in one walk */
    LVPROBE_MAX_DEPTH = 32,    /* nesting depth of the walked tree */
    LVPROBE_TEXT_BYTES = 16384, /* all label texts of one walk, NUL included */
    LVPROBE_MAX_FONTS = 16,    /* font identities the caller can map */
    LVPROBE_LIFE_CAP = 64      /* lifecycle events kept between two `lvprobe_life` calls */
};

#define LVPROBE_FONT_UNMAPPED 0xFFFFu
#define LVPROBE_NONE (-1)

typedef enum {
    LVPROBE_OK = 0,
    LVPROBE_ERR_ARG,      /* NULL pointer, closed probe or an index out of range */
    LVPROBE_ERR_FULL,     /* a capacity above was exceeded (nodes, depth, text bytes, fonts, scratch pixels) */
    LVPROBE_ERR_TRUNC,    /* the caller's output buffer is too small; its content is not a valid result */
    LVPROBE_ERR_FORMAT,   /* the display's active buffer is not XRGB8888 */
    LVPROBE_ERR_LVGL,     /* LVGL refused something (indev or event registration) */
    LVPROBE_ERR_GONE,     /* the node's object was deleted after the walk */
    LVPROBE_ERR_UNSTABLE, /* unhiding a node did not restore its pixels */
    LVPROBE_ERR_OVERFLOW  /* lifecycle events were lost since the previous `lvprobe_life` */
} lvprobe_status_t;

/* One object of the last walk. Read-only for the caller. Boxes are LVGL areas (inclusive corners, absolute
 * display coordinates); a box with x2 < x1 is empty. */
typedef struct {
    lv_obj_t *obj;             /* NULL once LVGL deleted it; never dereference it yourself */
    const char *class_name;    /* LVGL's class name ("lv_obj", "lv_label", "lv_button", "lv_image") */
    int16_t parent;            /* index of the parent node, LVPROBE_NONE for a root (layer or screen) */
    int16_t clip;              /* nearest ancestor whose child clip box does not contain `coords`, or NONE */
    uint8_t depth;             /* 0 for a root */
    bool hidden;               /* the object's own LV_OBJ_FLAG_HIDDEN */
    bool clickable;            /* the object's own LV_OBJ_FLAG_CLICKABLE */
    lv_area_t coords;          /* absolute coordinates after layout */
    uint32_t bg_rgb;           /* main-part bg colour as 0xRRGGBB */
    uint8_t bg_opa;            /* main-part bg opacity 0..255 */
    /* labels only (is_label) */
    bool is_label;
    const char *text;          /* copy of the label text in the probe, NUL-terminated */
    const lv_font_t *font;     /* resolved main-part font */
    uint16_t font_id;          /* the caller's id for `font` (lvprobe_map_font) or LVPROBE_FONT_UNMAPPED */
    int32_t line_height;       /* lv_font_get_line_height(font) */
    uint8_t align;             /* main-part text align style (lv_text_align_t) */
    uint8_t long_mode;         /* lv_label_long_mode_t */
    int32_t lines;             /* laid-out line count, from the size LVGL laid the text out to */
    lv_point_t natural;        /* lv_text_get_size with no width limit */
    lv_point_t laid_out;       /* the text size LVGL computed for the label's content width */
    /* verdict facts of the walk (labels only) */
    bool drawn;                /* LVGL created a label draw task for it in the walk's render */
    bool has_glyphs;           /* at least one glyph box */
    lv_area_t glyphs;          /* union of the per-glyph ink boxes, unclipped */
    lv_area_t visible;         /* the clip area LVGL drew the label with (union over its draw tasks) */
    bool clipped;              /* glyphs not inside visible; or text that LVGL did not draw at all */
    /* lvprobe_ink */
    bool has_ink;
    uint32_t ink;              /* pixels that change when the node (and its subtree) is hidden */
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
    int16_t node;              /* index of the object in the last walk, or NONE (always NONE for a creation) */
    int16_t parent;            /* index of its parent in the last walk, or NONE */
    const char *class_name;
} lvprobe_life_t;

typedef struct {
    bool clicked;              /* some object received LV_EVENT_CLICKED from the probe's indev */
    lv_obj_t *obj;             /* that object (compare only, it may be gone) */
    int32_t node;              /* its index in the last walk, or NONE */
} lvprobe_hit_t;

/* The probe. Caller-owned (static storage); all fields are private to the probe. */
typedef struct {
    bool open;
    lvprobe_status_t fault;    /* sticky error raised inside an LVGL callback, reported by the next walk/life */
    lv_display_t *disp;
    lv_indev_t *indev;
    lv_point_t press_at;
    bool pressed;
    lvprobe_hit_t hit;
    uint32_t *scratch;
    size_t scratch_px;
    uint16_t count;
    bool capturing;
    lvprobe_node_t nodes[LVPROBE_MAX_NODES];
    uint8_t draw_events_before[LVPROBE_MAX_NODES];
    char text[LVPROBE_TEXT_BYTES];
    size_t text_used;
    const lv_font_t *fonts[LVPROBE_MAX_FONTS];
    uint16_t font_ids[LVPROBE_MAX_FONTS];
    uint16_t font_count;
    lvprobe_life_t life[LVPROBE_LIFE_CAP];
    uint16_t life_count;
    uint32_t life_lost;
    uint32_t life_seq;
    bool has_frame;
    uint32_t frame_crc;
    int32_t frame_w, frame_h;
} lvprobe_t;

/* Open a probe on `disp` (whose active buffer must be XRGB8888). `scratch` holds `scratch_px` pixels for
 * `lvprobe_ink` (a node's box + its ext draw size must fit; width x height of the display always does). Creates
 * the probe's pointer indev and starts observing object creation and deletion on every screen and layer. */
lvprobe_status_t lvprobe_open(lvprobe_t *p, lv_display_t *disp, uint32_t *scratch, size_t scratch_px);

/* Stop observing and delete the probe's indev. Call before deleting the display. */
void lvprobe_close(lvprobe_t *p);

/* Give `font` the identity `id` in walk facts (at most LVPROBE_MAX_FONTS fonts). */
lvprobe_status_t lvprobe_map_font(lvprobe_t *p, const lv_font_t *font, uint16_t id);

/* 1 (O3 tree) and the `clipped` verdict of 2: invalidate the screen and let LVGL redraw it once (the frame is
 * redrawn identically) while capturing each label's draw task, then walk bottom layer, active screen, top layer
 * and sys layer depth-first. Replaces the previous walk. */
lvprobe_status_t lvprobe_walk(lvprobe_t *p);

uint16_t lvprobe_count(const lvprobe_t *p);
const lvprobe_node_t *lvprobe_node(const lvprobe_t *p, uint16_t index);   /* NULL when out of range */
int32_t lvprobe_find(const lvprobe_t *p, const lv_obj_t *obj);              /* index or LVPROBE_NONE */

/* 2 (ink) and the luminance samples of 4: hide the node, redraw, diff its box (coords + ext draw size), unhide,
 * redraw, and check the box is restored. The expensive call (two renders): the caller decides which nodes need it
 * (for example once per scene-structure class). */
lvprobe_status_t lvprobe_ink(lvprobe_t *p, uint16_t index);

/* 3: press and release at (x, y) through the probe's LVGL pointer indev. */
lvprobe_status_t lvprobe_hit(lvprobe_t *p, int32_t x, int32_t y, lvprobe_hit_t *out);

/* 4: frame CRC (FNV-1a over the B, G, R bytes of every pixel, row-major) and every node's region hash. No redraw. */
lvprobe_status_t lvprobe_frame(lvprobe_t *p);
uint32_t lvprobe_frame_crc(const lvprobe_t *p);

/* 4: copy `box` (inside the display) as RGBA8888 rows into `rgba`; `*len` = bytes written. */
lvprobe_status_t lvprobe_crop(const lvprobe_t *p, const lv_area_t *box, uint8_t *rgba, size_t cap, size_t *len);

/* 5: object creations and deletions since the previous call, oldest first. At most `cap` are copied; `*lost`
 * counts the events that did not fit (in the ring or in `out`), and then the status is LVPROBE_ERR_OVERFLOW. */
lvprobe_status_t lvprobe_life(lvprobe_t *p, lvprobe_life_t *out, uint16_t cap, uint16_t *n, uint32_t *lost);

/* 6: the facts of 1, 2 and 4 as text, one fact per line (docs/ui-lvprobe.md). Needs cap > the text length (a
 * NUL follows it). Truncation returns LVPROBE_ERR_TRUNC and `*len` = 0; it is never silent. */
lvprobe_status_t lvprobe_encode(const lvprobe_t *p, char *buf, size_t cap, size_t *len);

#endif /* UI_LVPROBE_LVPROBE_H */
