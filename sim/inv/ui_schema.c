/* The parser of the schema text of ui.h: names, enums, objects with switches, roles and the few rules a product states as data. */
#include <string.h>

#include "sim/inv/ui.h"

enum { TOKS = 30, LINE_BYTES = 600, NUM_DIGITS = 9 };

/* The tokens of one line. A slot past `count` is NULL with length 0, which matches nothing and names nothing. */
typedef struct {
    const char *p[TOKS];
    uint32_t n[TOKS];
    uint32_t count;
} line_t;

typedef ui_schema_err_t (*directive_fn)(ui_schema_t *s, const line_t *l);

static int name_char(char c) {
    return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
}

/* A name starts with a letter and has only letters, digits and `_`: below `a` are the digits and `_` too. */
static int is_name(const char *p, uint32_t n) {
    if (n >= (uint32_t)UI_NAME_MAX || p[0] < 'a') {
        return 0;
    }
    for (const char *c = p; c != p + n; c++) {
        if (!name_char(*c)) {
            return 0;
        }
    }
    return 1;
}

static int same(const char *name, const char *p, uint32_t n) {
    return strlen(name) == n && memcmp(name, p, n) == 0;
}

static int tok_is(const line_t *l, uint32_t i, const char *word) {
    return same(word, l->p[i], l->n[i]);
}

static int number(const line_t *l, uint32_t i, uint32_t *out) {
    uint32_t v = 0;
    if (l->n[i] > (uint32_t)NUM_DIGITS) {
        return 0;
    }
    for (const char *c = l->p[i]; c != l->p[i] + l->n[i]; c++) {
        if (*c < '0' || *c > '9') {
            return 0;
        }
        v = v * 10U + (uint32_t)(*c - '0');
    }
    *out = v;
    return 1;
}

static void copy_name(char *dst, const line_t *l, uint32_t i) {
    memcpy(dst, l->p[i], l->n[i]);
    dst[l->n[i]] = '\0';
}

static int find_enum(const ui_schema_t *s, const char *p, uint32_t n) {
    for (const ui_enum_t *e = s->enums; e != s->enums + s->n_enums; e++) {
        if (same(e->name, p, n)) {
            return (int)(e - s->enums);
        }
    }
    return -1;
}

static int find_value(const ui_enum_t *e, const char *p, uint32_t n) {
    for (const char(*v)[UI_NAME_MAX] = e->values; v != e->values + e->n_values; v++) {
        if (same(*v, p, n)) {
            return (int)(v - e->values);
        }
    }
    return -1;
}

static int find_object(const ui_schema_t *s, const char *p, uint32_t n) {
    for (const ui_object_t *o = s->objects; o != s->objects + s->n_objects; o++) {
        if (same(o->name, p, n)) {
            return (int)(o - s->objects);
        }
    }
    return -1;
}

static int find_field(const ui_object_t *o, const char *p, uint32_t n) {
    for (const ui_field_t *f = o->fields; f != o->fields + o->n_fields; f++) {
        if (same(f->key, p, n)) {
            return (int)(f - o->fields);
        }
    }
    return -1;
}

/* The enum of the field that plays `role`, or NULL while the role is not declared. */
static const ui_enum_t *role_enum(const ui_schema_t *s, ui_role_t role) {
    return s->role_seen[role] != 0U ? &s->enums[s->role_ref[role]] : NULL;
}

static ui_schema_err_t do_enum(ui_schema_t *s, const line_t *l) {
    if (s->open != 0U) {
        return UI_SE_CONTEXT;
    }
    if (l->count < 3U || !is_name(l->p[1], l->n[1])) {
        return UI_SE_SYNTAX;
    }
    if (s->n_enums == UI_MAX_ENUMS || l->count - 2U > (uint32_t)UI_MAX_VALUES) {
        return UI_SE_LIMIT;
    }
    if (find_enum(s, l->p[1], l->n[1]) >= 0) {
        return UI_SE_DUPLICATE;
    }
    ui_enum_t *e = &s->enums[s->n_enums];
    copy_name(e->name, l, 1);
    for (uint32_t i = 2; i < l->count; i++) {
        if (!is_name(l->p[i], l->n[i])) {
            return UI_SE_SYNTAX;
        }
        if (find_value(e, l->p[i], l->n[i]) >= 0) {
            return UI_SE_DUPLICATE;
        }
        copy_name(e->values[e->n_values], l, i);
        e->n_values++;
    }
    s->n_enums++;
    return UI_SE_OK;
}

static ui_schema_err_t do_object(ui_schema_t *s, const line_t *l) {
    if (s->open != 0U) {
        return UI_SE_CONTEXT;
    }
    if (l->count != 2U || !is_name(l->p[1], l->n[1])) {
        return UI_SE_SYNTAX;
    }
    if (s->n_objects == UI_MAX_OBJECTS) {
        return UI_SE_LIMIT;
    }
    if (find_object(s, l->p[1], l->n[1]) >= 0) {
        return UI_SE_DUPLICATE;
    }
    copy_name(s->objects[s->n_objects].name, l, 1);
    s->cur = s->n_objects;
    s->open = 1;
    s->n_objects++;
    return UI_SE_OK;
}

static ui_schema_err_t do_end(ui_schema_t *s, const line_t *l) {
    if (l->count != 1U) {
        return UI_SE_SYNTAX;
    }
    if (s->open == 0U || s->sw_open != 0U) {
        return UI_SE_CONTEXT;
    }
    s->open = 0;
    return UI_SE_OK;
}

/* `by KEY` and `null` after the object name of an `obj` field. */
static ui_schema_err_t obj_tail(ui_schema_t *s, const line_t *l, ui_field_t *f, const ui_object_t *o) {
    uint32_t i = 4;
    if (tok_is(l, i, "by")) {
        int k = find_field(o, l->p[i + 1U], l->n[i + 1U]);
        if (k < 0 || o->fields[k].type != (uint8_t)UI_T_ENUM) {
            return UI_SE_REF;
        }
        f->by = (uint8_t)(k + 1);
        i += 2U;
    }
    if (tok_is(l, i, "null")) {
        f->nullable = 1;
        i++;
    }
    if (i != l->count) {
        return UI_SE_SYNTAX;
    }
    const ui_object_t *t = &s->objects[f->ref];
    if ((f->by != 0U) != (t->has_ext != 0U) || (f->by != 0U && t->ext_enum != o->fields[f->by - 1U].ref)) {
        return UI_SE_REF;
    }
    return UI_SE_OK;
}

static ui_schema_err_t type_uint(const line_t *l, ui_field_t *f) {
    f->type = (uint8_t)UI_T_UINT;
    if (l->count < 4U || l->count > 5U || !number(l, 3, &f->max)) {
        return UI_SE_SYNTAX;
    }
    f->nullable = (uint8_t)(l->count == 5U);
    return l->count == 5U && !tok_is(l, 4, "null") ? UI_SE_SYNTAX : UI_SE_OK;
}

static ui_schema_err_t type_enum(const ui_schema_t *s, const line_t *l, ui_field_t *f) {
    if (l->count != 4U) {
        return UI_SE_SYNTAX;
    }
    int e = find_enum(s, l->p[3], l->n[3]);
    f->type = (uint8_t)UI_T_ENUM;
    f->ref = (uint8_t)e;
    return e < 0 ? UI_SE_REF : UI_SE_OK;
}

static ui_schema_err_t type_ref(ui_schema_t *s, const line_t *l, ui_field_t *f, const ui_object_t *o) {
    uint32_t v;
    if (l->count < 4U) {
        return UI_SE_SYNTAX;
    }
    int ob = find_object(s, l->p[3], l->n[3]);
    if (ob < 0 || ob >= (int)s->cur) { /* an object is declared before its use: no object contains itself */
        return UI_SE_REF;
    }
    f->ref = (uint8_t)ob;
    if (tok_is(l, 2, "obj")) {
        f->type = (uint8_t)UI_T_OBJ;
        return obj_tail(s, l, f, o);
    }
    f->type = (uint8_t)UI_T_LIST;
    if (l->count != 5U || !number(l, 4, &v) || v < 1U) {
        return UI_SE_SYNTAX;
    }
    if (v > 255U) {
        return UI_SE_LIMIT;
    }
    f->max = v;
    return UI_SE_OK;
}

static ui_schema_err_t field_type(ui_schema_t *s, const line_t *l, ui_field_t *f, const ui_object_t *o) {
    if (tok_is(l, 2, "uint")) {
        return type_uint(l, f);
    }
    if (tok_is(l, 2, "bool")) {
        f->type = (uint8_t)UI_T_BOOL;
        return l->count == 3U ? UI_SE_OK : UI_SE_SYNTAX;
    }
    if (tok_is(l, 2, "enum")) {
        return type_enum(s, l, f);
    }
    return tok_is(l, 2, "obj") || tok_is(l, 2, "list") ? type_ref(s, l, f, o) : UI_SE_SYNTAX;
}

/* A key may repeat only in different cases of one switch. */
static int key_taken(const ui_object_t *o, const ui_field_t *f) {
    for (const ui_field_t *g = o->fields; g != o->fields + o->n_fields; g++) {
        if (strcmp(g->key, f->key) == 0 && (g->sw_src == 0U || f->sw_src == 0U || (g->sw_src == f->sw_src && g->sw_case == f->sw_case))) {
            return 1;
        }
    }
    return 0;
}

static ui_schema_err_t do_field(ui_schema_t *s, const line_t *l) {
    if (s->open == 0U || (s->sw_open != 0U && s->sw_on == 0U)) {
        return UI_SE_CONTEXT;
    }
    if (l->count < 3U || !is_name(l->p[1], l->n[1])) {
        return UI_SE_SYNTAX;
    }
    ui_object_t *o = &s->objects[s->cur];
    if (o->n_fields == UI_MAX_FIELDS) {
        return UI_SE_LIMIT;
    }
    ui_field_t *f = &o->fields[o->n_fields]; /* built in place: the slot is still zero, and a failed parse keeps nothing */
    copy_name(f->key, l, 1);
    ui_schema_err_t err = field_type(s, l, f, o);
    if (err != UI_SE_OK) {
        return err;
    }
    f->sw_src = s->sw_open != 0U ? s->sw_src : 0U;
    f->sw_case = s->sw_case;
    if (key_taken(o, f)) {
        return UI_SE_DUPLICATE;
    }
    o->n_fields++;
    return UI_SE_OK;
}

static ui_schema_err_t do_switch(ui_schema_t *s, const line_t *l) {
    if (s->open == 0U || s->sw_open != 0U) {
        return UI_SE_CONTEXT;
    }
    ui_object_t *o = &s->objects[s->cur];
    if (l->count == 3U && tok_is(l, 1, "@")) {
        int e = find_enum(s, l->p[2], l->n[2]);
        if (e < 0 || (o->has_ext != 0U && o->ext_enum != (uint8_t)e)) {
            return UI_SE_REF;
        }
        o->has_ext = 1;
        o->ext_enum = (uint8_t)e;
        s->sw_src = (uint8_t)UI_SW_EXT;
        s->sw_enum = (uint8_t)e;
    } else if (l->count == 2U) {
        int k = find_field(o, l->p[1], l->n[1]);
        if (k < 0 || o->fields[k].type != (uint8_t)UI_T_ENUM) {
            return UI_SE_REF;
        }
        s->sw_src = (uint8_t)(k + 1);
        s->sw_enum = o->fields[k].ref;
    } else {
        return UI_SE_SYNTAX;
    }
    s->sw_open = 1;
    s->sw_on = 0;
    return UI_SE_OK;
}

static ui_schema_err_t do_on(ui_schema_t *s, const line_t *l) {
    if (l->count != 2U) {
        return UI_SE_SYNTAX;
    }
    if (s->sw_open == 0U) {
        return UI_SE_CONTEXT;
    }
    int v = find_value(&s->enums[s->sw_enum], l->p[1], l->n[1]);
    if (v < 0) {
        return UI_SE_REF;
    }
    s->sw_case = (uint8_t)v;
    s->sw_on = 1;
    return UI_SE_OK;
}

static ui_schema_err_t do_endswitch(ui_schema_t *s, const line_t *l) {
    if (l->count != 1U) {
        return UI_SE_SYNTAX;
    }
    if (s->sw_open == 0U) {
        return UI_SE_CONTEXT;
    }
    s->sw_open = 0;
    return UI_SE_OK;
}

static ui_schema_err_t do_top(ui_schema_t *s, const line_t *l) {
    if (l->count != 2U) {
        return UI_SE_SYNTAX;
    }
    if (s->open != 0U) {
        return UI_SE_CONTEXT;
    }
    int o = find_object(s, l->p[1], l->n[1]);
    if (s->has_top != 0U) {
        return UI_SE_DUPLICATE;
    }
    if (o < 0) {
        return UI_SE_REF;
    }
    s->top = (uint8_t)o;
    s->has_top = 1;
    return UI_SE_OK;
}

typedef struct {
    const char *name;
    ui_type_t type;
    uint8_t nullable;
} role_row_t;

/* The role of the row `i` is UI_ROLE_SCREEN + i. */
static const role_row_t ROLES[UI_ROLE_COUNT - 1] = {
    {"screen", UI_T_ENUM, 0},
    {"lang", UI_T_ENUM, 0},
    {"notice", UI_T_OBJ, 1},
    {"banners", UI_T_LIST, 0},
    {"n_kind", UI_T_ENUM, 0},
    {"n_dismiss", UI_T_ENUM, 0},
    {"n_phrase", UI_T_ENUM, 0},
    {"n_countdown", UI_T_UINT, 1},
    {"b_id", UI_T_ENUM, 0},
    {"b_phrase", UI_T_ENUM, 0}};

static ui_schema_err_t do_role(ui_schema_t *s, const line_t *l) {
    if (l->count != 4U) {
        return UI_SE_SYNTAX;
    }
    if (s->open != 0U) {
        return UI_SE_CONTEXT;
    }
    uint32_t i = 0;
    while (i < (uint32_t)UI_ROLE_COUNT - 1U && !tok_is(l, 1, ROLES[i].name)) {
        i++;
    }
    if (i == (uint32_t)UI_ROLE_COUNT - 1U) {
        return UI_SE_SYNTAX;
    }
    uint32_t r = i + 1U; /* the role: UI_ROLE_SCREEN + i */
    int o = find_object(s, l->p[2], l->n[2]);
    int k = o >= 0 ? find_field(&s->objects[o], l->p[3], l->n[3]) : -1;
    if (k < 0) {
        return UI_SE_REF;
    }
    ui_field_t *f = &s->objects[o].fields[k];
    if (s->role_seen[r] != 0U || f->role != 0U || f->sw_src != 0U || f->type != (uint8_t)ROLES[i].type || f->nullable != ROLES[i].nullable) {
        return UI_SE_ROLE;
    }
    f->role = (uint8_t)r;
    s->role_seen[r] = 1;
    s->role_obj[r] = (uint8_t)o;
    s->role_ref[r] = f->ref;
    s->role_max[r] = f->max;
    return UI_SE_OK;
}

static ui_schema_err_t do_bannerdismiss(ui_schema_t *s, const line_t *l) {
    if (l->count != 3U) {
        return UI_SE_SYNTAX;
    }
    const ui_enum_t *ids = role_enum(s, UI_ROLE_B_ID);
    const ui_enum_t *dismisses = role_enum(s, UI_ROLE_N_DISMISS);
    if (ids == NULL || dismisses == NULL) {
        return UI_SE_REF;
    }
    int id = find_value(ids, l->p[1], l->n[1]);
    int ds = find_value(dismisses, l->p[2], l->n[2]);
    if (id < 0 || ds < 0) {
        return UI_SE_REF;
    }
    if (s->banner_dismiss[id] != 0U) {
        return UI_SE_DUPLICATE;
    }
    s->banner_dismiss[id] = (uint8_t)(ds + 1);
    return UI_SE_OK;
}

static ui_schema_err_t do_forbid(ui_schema_t *s, const line_t *l) {
    if (l->count < 2U) {
        return UI_SE_SYNTAX;
    }
    if (s->n_forbid + (l->count - 1U) > (uint32_t)UI_MAX_FORBID) {
        return UI_SE_LIMIT;
    }
    for (uint32_t i = 1; i < l->count; i++) {
        if (!is_name(l->p[i], l->n[i])) {
            return UI_SE_SYNTAX;
        }
        copy_name(s->forbid[s->n_forbid], l, i);
        s->n_forbid++;
    }
    return UI_SE_OK;
}

static ui_schema_err_t do_value_of(ui_schema_t *s, const line_t *l, ui_role_t role, uint8_t *dst, uint8_t *seen) {
    if (l->count != 2U) {
        return UI_SE_SYNTAX;
    }
    const ui_enum_t *values = role_enum(s, role);
    if (values == NULL) {
        return UI_SE_REF;
    }
    int v = find_value(values, l->p[1], l->n[1]);
    if (*seen != 0U) {
        return UI_SE_DUPLICATE;
    }
    if (v < 0) {
        return UI_SE_REF;
    }
    *dst = (uint8_t)v;
    *seen = 1;
    return UI_SE_OK;
}

static ui_schema_err_t do_idle(ui_schema_t *s, const line_t *l) {
    return do_value_of(s, l, UI_ROLE_SCREEN, &s->idle_screen, &s->has_idle);
}

static ui_schema_err_t do_lang_default(ui_schema_t *s, const line_t *l) {
    return do_value_of(s, l, UI_ROLE_LANG, &s->default_lang, &s->has_lang);
}

static ui_schema_err_t do_expiring(ui_schema_t *s, const line_t *l) {
    if (l->count < 2U) {
        return UI_SE_SYNTAX;
    }
    const ui_enum_t *kinds = role_enum(s, UI_ROLE_N_KIND);
    if (kinds == NULL) {
        return UI_SE_REF;
    }
    for (uint32_t i = 1; i < l->count; i++) {
        int v = find_value(kinds, l->p[i], l->n[i]);
        if (v < 0) {
            return UI_SE_REF;
        }
        s->expiring_mask |= 1U << (unsigned)v;
    }
    return UI_SE_OK;
}

typedef struct {
    const char *word;
    directive_fn fn;
} directive_t;

static const directive_t DIRECTIVES[] = {
    {"enum", do_enum},         {"object", do_object},   {"end", do_end},           {"field", do_field},
    {"switch", do_switch},     {"on", do_on},           {"endswitch", do_endswitch}, {"top", do_top},
    {"role", do_role},         {"bannerdismiss", do_bannerdismiss}, {"forbid", do_forbid}, {"idle", do_idle},
    {"lang_default", do_lang_default}, {"expiring", do_expiring}};

static ui_schema_err_t do_line(ui_schema_t *s, const line_t *l) {
    for (const directive_t *d = DIRECTIVES; d != DIRECTIVES + sizeof DIRECTIVES / sizeof DIRECTIVES[0]; d++) {
        if (tok_is(l, 0, d->word)) {
            return d->fn(s, l);
        }
    }
    return UI_SE_SYNTAX;
}

/* Split the `n` bytes at `p` into tokens. UI_SE_LIMIT when there are too many. */
static ui_schema_err_t tokenize(const char *p, uint32_t n, line_t *l) {
    uint32_t i = 0;
    while (i < n) {
        if (p[i] == ' ') {
            i++;
            continue;
        }
        if (l->count == TOKS) {
            return UI_SE_LIMIT;
        }
        l->p[l->count] = p + i;
        while (i < n && p[i] != ' ') {
            i++;
        }
        l->n[l->count] = (uint32_t)(p + i - l->p[l->count]);
        l->count++;
    }
    return UI_SE_OK;
}

/* The directives of the lines of `len` bytes at `text`. */
static ui_schema_err_t lines(ui_schema_t *s, const char *text, uint32_t len) {
    while (len > 0U) {
        uint32_t end = 0;
        line_t l = {{NULL}, {0}, 0};
        while (end < len && text[end] != '\n') {
            end++;
        }
        s->err_line++;
        ui_schema_err_t err = end > (uint32_t)LINE_BYTES ? UI_SE_LIMIT : tokenize(text, end, &l);
        if (err == UI_SE_OK && l.count > 0U && l.p[0][0] != '#') {
            err = do_line(s, &l);
        }
        if (err != UI_SE_OK) {
            return err;
        }
        uint32_t used = end < len ? end + 1U : end; /* the line and its newline */
        text += used;
        len -= used;
    }
    return UI_SE_OK;
}

/* The roles live in the objects they are for. */
static ui_schema_err_t owners(const ui_schema_t *s) {
    for (uint32_t r = UI_ROLE_SCREEN; r < (uint32_t)UI_ROLE_COUNT; r++) {
        uint32_t want = r <= (uint32_t)UI_ROLE_BANNERS ? s->top : (r <= (uint32_t)UI_ROLE_N_COUNTDOWN ? s->role_ref[UI_ROLE_NOTICE] : s->role_ref[UI_ROLE_BANNERS]);
        if (s->role_obj[r] != want) {
            return UI_SE_ROLE;
        }
    }
    return s->role_max[UI_ROLE_BANNERS] > (uint32_t)UI_MAX_BANNERS ? UI_SE_ROLE : UI_SE_OK;
}

/* Every role is declared. (`screen` and `lang` are: `idle` and `lang_default` need them, and are required here.) */
static ui_schema_err_t finish(const ui_schema_t *s) {
    if (s->open != 0U || s->has_top == 0U || s->has_idle == 0U || s->has_lang == 0U || s->expiring_mask == 0U) {
        return UI_SE_INCOMPLETE;
    }
    for (uint32_t r = UI_ROLE_NOTICE; r < (uint32_t)UI_ROLE_COUNT; r++) {
        if (s->role_seen[r] == 0U) {
            return UI_SE_INCOMPLETE;
        }
    }
    const ui_enum_t *ids = role_enum(s, UI_ROLE_B_ID);
    for (const uint8_t *d = s->banner_dismiss; d != s->banner_dismiss + ids->n_values; d++) {
        if (*d == 0U) {
            return UI_SE_INCOMPLETE;
        }
    }
    return owners(s);
}

ui_schema_err_t ui_schema_parse(ui_schema_t *s, const char *text, uint32_t len) {
    memset(s, 0, sizeof *s);
    ui_schema_err_t err = text == NULL && len > 0U ? UI_SE_SYNTAX : lines(s, text, len);
    if (err == UI_SE_OK) {
        err = finish(s);
        s->err_line = 0;
    }
    s->ready = (uint8_t)(err == UI_SE_OK);
    return err;
}

uint32_t ui_schema_error_line(const ui_schema_t *s) {
    return s->err_line;
}

const char *ui_schema_error_name(ui_schema_err_t err) {
    static const char *const names[] = {"ok", "syntax", "limit", "duplicate", "reference", "context", "role", "incomplete"};
    return (unsigned)err <= (unsigned)UI_SE_INCOMPLETE ? names[err] : NULL;
}

int ui_schema_banner_dismiss(const ui_schema_t *s, uint8_t id) {
    return (int)s->banner_dismiss[id] - 1;
}
