/* The strict parser of one view: the canonical compact JSON of the product's ViewState, checked against a ui_schema_t as it is read.
 * No recursion: an explicit stack of frames (an object, or a list of objects); the schema declares an object before its use, so
 * a path through it has an object at most once and the stack is bounded by UI_MAX_DEPTH. Every step returns the rule it broke, or
 * UI_R_NONE; the parser stops at the first one, with `pos` where it stopped. */
#include <string.h>

#include "sim/inv/ui.h"

typedef struct {
    uint8_t is_list, obj, field, first, role, count, max;
    int8_t ext;
    int8_t sel[UI_MAX_FIELDS];
    uint32_t begin;
} frame_t;

typedef struct {
    const ui_schema_t *s;
    const uint8_t *b;
    uint32_t len, pos, depth;
    ui_view_t *v;
    frame_t st[UI_MAX_DEPTH];
} ps_t;

static int text_char(uint8_t c) {
    return (c >= (uint8_t)'a' && c <= (uint8_t)'z') || (c >= (uint8_t)'0' && c <= (uint8_t)'9') || c == (uint8_t)'_';
}

static ui_rule_t want(ps_t *p, char c, ui_rule_t otherwise) {
    if (p->pos < p->len && p->b[p->pos] == (uint8_t)c) {
        p->pos++;
        return UI_R_NONE;
    }
    return otherwise;
}

static int take_word(ps_t *p, const char *w) {
    size_t n = strlen(w);
    if (p->len - p->pos >= n && memcmp(p->b + p->pos, w, n) == 0) {
        p->pos += (uint32_t)n;
        return 1;
    }
    return 0;
}

/* The text of a key or an enum value after its opening quote, up to and including the closing one. */
static ui_rule_t read_text(ps_t *p, char *out) {
    uint32_t n = 0;
    while (p->pos < p->len && text_char(p->b[p->pos])) {
        if (n == (uint32_t)UI_NAME_MAX - 1U) {
            return UI_R_SYNTAX;
        }
        out[n++] = (char)p->b[p->pos++];
    }
    out[n] = '\0';
    return want(p, '"', UI_R_SYNTAX);
}

/* The next field of the object that exists for this view's selectors: its index, or -1 at the end. */
static int next_active(const ui_object_t *o, frame_t *f) {
    while (f->field < o->n_fields) {
        uint32_t i = f->field++;
        const ui_field_t *fd = &o->fields[i];
        if (fd->sw_src == 0U || (fd->sw_src == (uint8_t)UI_SW_EXT ? f->ext : f->sel[fd->sw_src - 1U]) == (int)fd->sw_case) {
            return (int)i;
        }
    }
    return -1;
}

static int forbidden(const ui_schema_t *s, const char *key) {
    for (const char(*w)[UI_NAME_MAX] = s->forbid; w != s->forbid + s->n_forbid; w++) {
        if (strcmp(*w, key) == 0) {
            return 1;
        }
    }
    return 0;
}

/* `,` `"key"` `:` for the field `fd`. */
static ui_rule_t key_stage(ps_t *p, frame_t *f, const ui_field_t *fd) {
    char key[UI_NAME_MAX];
    ui_rule_t lack = fd->role == (uint8_t)UI_ROLE_N_DISMISS ? UI_R_NO_DISMISS : UI_R_SYNTAX;
    ui_rule_t r = f->first == 0U ? want(p, ',', lack) : UI_R_NONE;
    if (r == UI_R_NONE) {
        r = want(p, '"', lack);
    }
    if (r == UI_R_NONE) {
        r = read_text(p, key);
    }
    if (r == UI_R_NONE) {
        r = want(p, ':', lack);
    }
    f->first = 0;
    if (r != UI_R_NONE) {
        return r;
    }
    if (strcmp(key, fd->key) == 0) {
        return UI_R_NONE;
    }
    return forbidden(p->s, key) ? UI_R_FULL_SCREEN : lack == UI_R_NO_DISMISS ? UI_R_NO_DISMISS : UI_R_KEY;
}

static ui_rule_t leaf_uint(ps_t *p, const ui_field_t *fd, uint32_t *out) {
    uint64_t v = 0;
    int over = 0;
    uint32_t start;
    if (fd->nullable != 0U && take_word(p, "null")) {
        *out = 0;
        return UI_R_NONE;
    }
    start = p->pos;
    while (p->pos < p->len && p->b[p->pos] >= (uint8_t)'0' && p->b[p->pos] <= (uint8_t)'9') {
        if (over == 0) {
            v = v * 10U + (uint64_t)(p->b[p->pos] - (uint8_t)'0');
            over = v > fd->max;
        }
        p->pos++;
    }
    if (p->pos == start || (p->b[start] == (uint8_t)'0' && p->pos - start > 1U)) {
        return UI_R_SYNTAX;
    }
    if (p->pos < p->len && (p->b[p->pos] == (uint8_t)'.' || p->b[p->pos] == (uint8_t)'e' || p->b[p->pos] == (uint8_t)'E')) {
        return UI_R_FLOAT;
    }
    if (over != 0 || (fd->nullable != 0U && v == 0U)) {
        return UI_R_RANGE;
    }
    *out = (uint32_t)v;
    return UI_R_NONE;
}

static ui_rule_t leaf_enum(ps_t *p, const ui_field_t *fd, uint32_t *out) {
    char text[UI_NAME_MAX];
    const ui_enum_t *e = &p->s->enums[fd->ref];
    ui_rule_t r = want(p, '"', fd->role == (uint8_t)UI_ROLE_N_DISMISS ? UI_R_NO_DISMISS : UI_R_SYNTAX);
    if (r == UI_R_NONE) {
        r = read_text(p, text);
    }
    if (r != UI_R_NONE) {
        return r;
    }
    for (const char(*w)[UI_NAME_MAX] = e->values; w != e->values + e->n_values; w++) {
        if (strcmp(*w, text) == 0) {
            *out = (uint32_t)(w - e->values);
            return UI_R_NONE;
        }
    }
    return fd->role == (uint8_t)UI_ROLE_SCREEN ? UI_R_FULL_SCREEN : UI_R_ENUM;
}

static void store(ps_t *p, const ui_field_t *fd, uint32_t val) {
    ui_view_t *v = p->v;
    switch ((ui_role_t)fd->role) {
    case UI_ROLE_SCREEN:
        v->screen = (uint8_t)val;
        break;
    case UI_ROLE_LANG:
        v->lang = (uint8_t)val;
        break;
    case UI_ROLE_N_KIND:
        v->n_kind = (uint8_t)val;
        break;
    case UI_ROLE_N_DISMISS:
        v->n_dismiss = (uint8_t)val;
        break;
    case UI_ROLE_N_PHRASE:
        v->n_phrase = (uint8_t)val;
        break;
    case UI_ROLE_N_COUNTDOWN:
        v->n_countdown_ms = val;
        break;
    case UI_ROLE_B_ID:
        v->banner_id[v->n_banners] = (uint8_t)val;
        break;
    case UI_ROLE_B_PHRASE:
        v->banner_phrase[v->n_banners] = (uint8_t)val;
        break;
    default:
        break;
    }
}

static ui_rule_t leaf(ps_t *p, frame_t *f, const ui_field_t *fd, uint32_t idx) {
    uint32_t val;
    uint32_t start = p->pos;
    ui_rule_t r;
    if (fd->type == (uint8_t)UI_T_BOOL) {
        return take_word(p, "true") || take_word(p, "false") ? UI_R_NONE : UI_R_SYNTAX;
    }
    r = fd->type == (uint8_t)UI_T_UINT ? leaf_uint(p, fd, &val) : leaf_enum(p, fd, &val);
    if (r != UI_R_NONE) {
        return r;
    }
    if (fd->type == (uint8_t)UI_T_ENUM) {
        f->sel[idx] = (int8_t)val;
    }
    if (fd->role == (uint8_t)UI_ROLE_N_COUNTDOWN) {
        p->v->n_cd_off = start;
        p->v->n_cd_len = p->pos - start;
    }
    store(p, fd, val);
    return UI_R_NONE;
}

static frame_t *push(ps_t *p, uint8_t obj, uint8_t is_list) {
    frame_t *f = &p->st[p->depth++];
    memset(f, 0, sizeof *f);
    f->is_list = is_list;
    f->obj = obj;
    f->first = 1;
    f->begin = p->pos - 1U;
    return f;
}

/* The value of an `obj` or `list` field, after its key. */
static ui_rule_t container(ps_t *p, const frame_t *f, const ui_field_t *fd) {
    frame_t *n;
    ui_rule_t r;
    if (fd->type == (uint8_t)UI_T_LIST) {
        r = want(p, '[', UI_R_SYNTAX);
        if (r != UI_R_NONE) {
            return r;
        }
        n = push(p, fd->ref, 1);
        n->role = fd->role;
        n->max = (uint8_t)fd->max;
        return UI_R_NONE;
    }
    if (fd->nullable != 0U && take_word(p, "null")) {
        return UI_R_NONE;
    }
    r = want(p, '{', UI_R_SYNTAX);
    if (r != UI_R_NONE) {
        return r;
    }
    if (fd->role == (uint8_t)UI_ROLE_NOTICE) {
        p->v->has_notice = 1;
    }
    n = push(p, fd->ref, 0);
    n->role = fd->role;
    if (fd->by != 0U) {
        n->ext = f->sel[fd->by - 1U];
    }
    return UI_R_NONE;
}

static ui_rule_t banner_done(ps_t *p) {
    ui_view_t *v = p->v;
    uint32_t n = v->n_banners;
    v->n_banners = (uint8_t)(n + 1U);
    return n > 0U && v->banner_id[n] <= v->banner_id[n - 1U] ? UI_R_BANNER_ORDER : UI_R_NONE;
}

static ui_rule_t close_obj(ps_t *p, const frame_t *f) {
    ui_rule_t r = want(p, '}', UI_R_SYNTAX);
    if (r != UI_R_NONE) {
        return r;
    }
    p->depth--;
    if (f->role == (uint8_t)UI_ROLE_NOTICE) {
        p->v->notice_off = f->begin;
        p->v->notice_len = p->pos - f->begin;
    }
    return f->role == (uint8_t)UI_ROLE_BANNERS ? banner_done(p) : UI_R_NONE;
}

static ui_rule_t step_obj(ps_t *p, frame_t *f) {
    const ui_object_t *o = &p->s->objects[f->obj];
    int i = next_active(o, f);
    ui_rule_t r;
    if (i < 0) {
        return close_obj(p, f);
    }
    r = key_stage(p, f, &o->fields[i]);
    if (r != UI_R_NONE) {
        return r;
    }
    if (o->fields[i].type == (uint8_t)UI_T_OBJ || o->fields[i].type == (uint8_t)UI_T_LIST) {
        return container(p, f, &o->fields[i]);
    }
    return leaf(p, f, &o->fields[i], (uint32_t)i);
}

static ui_rule_t step_list(ps_t *p, frame_t *f) {
    ui_rule_t r;
    if (p->pos < p->len && p->b[p->pos] == (uint8_t)']') {
        p->pos++;
        p->depth--;
        return UI_R_NONE;
    }
    r = f->count > 0U ? want(p, ',', UI_R_SYNTAX) : UI_R_NONE;
    if (r != UI_R_NONE) {
        return r;
    }
    if (f->count == f->max) {
        return UI_R_RANGE;
    }
    f->count++;
    r = want(p, '{', UI_R_SYNTAX);
    if (r == UI_R_NONE) {
        push(p, f->obj, 0)->role = f->role;
    }
    return r;
}

static ui_rule_t read_view(ps_t *p) {
    ui_rule_t r = want(p, '{', UI_R_SYNTAX);
    if (r != UI_R_NONE) {
        return r;
    }
    push(p, p->s->top, 0);
    while (p->depth > 0U) {
        frame_t *f = &p->st[p->depth - 1U];
        r = f->is_list != 0U ? step_list(p, f) : step_obj(p, f);
        if (r != UI_R_NONE) {
            return r;
        }
    }
    return p->pos == p->len ? UI_R_NONE : UI_R_SYNTAX;
}

ui_rule_t ui_parse(const ui_schema_t *s, const uint8_t *bytes, uint32_t len, ui_view_t *out, uint32_t *at) {
    if (out == NULL) {
        return UI_R_SYNTAX;
    }
    memset(out, 0, sizeof *out);
    if (at != NULL) {
        *at = 0;
    }
    if (s == NULL || bytes == NULL || s->ready == 0U || len > (uint32_t)UI_VIEW_MAX) {
        return UI_R_SYNTAX;
    }
    ps_t p = {.s = s, .b = bytes, .len = len, .v = out};
    ui_rule_t r = read_view(&p);
    if (at != NULL) {
        *at = p.pos;
    }
    return r;
}
