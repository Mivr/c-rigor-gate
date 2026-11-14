/* The directives of the fields of an object: `field`, `switch`, `on`, `endswitch`. */
#include <string.h>

#include "sim/inv/ui_schema_int.h"


/* The slot of the enum field `k` of `o`, given on its first use: 0 when the object reads more than UI_MAX_SLOTS fields. */
static uint8_t take_slot(ui_object_t *o, int k) {
    ui_field_t *f = &o->fields[k];
    if (f->slot == 0U && o->n_slots < UI_MAX_SLOTS) {
        o->n_slots++;
        f->slot = o->n_slots;
    }
    return f->slot;
}

/* `by KEY` and `null` after the object name of an `obj` field. */
static ui_schema_err_t obj_tail(ui_schema_t *s, const us_line_t *l, ui_field_t *f, ui_object_t *o) {
    uint32_t i = 4;
    if (us_tok_is(l, i, "by")) {
        int k = us_find_field(o, l->p[i + 1U], l->n[i + 1U]);
        if (k < 0 || o->fields[k].type != (uint8_t)UI_T_ENUM) {
            return UI_SE_REF;
        }
        f->by = take_slot(o, k);
        if (f->by == 0U) {
            return UI_SE_LIMIT;
        }
        f->by_enum = o->fields[k].ref;
        i += 2U;
    }
    if (us_tok_is(l, i, "null")) {
        f->nullable = 1;
        i++;
    }
    if (i != l->count) {
        return UI_SE_SYNTAX;
    }
    const ui_object_t *t = &s->objects[f->ref];
    if ((f->by != 0U) != (t->has_ext != 0U) || (f->by != 0U && t->ext_enum != f->by_enum)) {
        return UI_SE_REF;
    }
    return UI_SE_OK;
}

static ui_schema_err_t type_uint(const us_line_t *l, ui_field_t *f) {
    f->type = (uint8_t)UI_T_UINT;
    if (l->count < 4U || l->count > 5U || !us_number(l, 3, &f->max)) {
        return UI_SE_SYNTAX;
    }
    f->nullable = (uint8_t)(l->count == 5U);
    return l->count == 5U && !us_tok_is(l, 4, "null") ? UI_SE_SYNTAX : UI_SE_OK;
}

static ui_schema_err_t type_enum(const ui_schema_t *s, const us_line_t *l, ui_field_t *f) {
    if (l->count != 4U) {
        return UI_SE_SYNTAX;
    }
    int e = us_find_enum(s, l->p[3], l->n[3]);
    f->type = (uint8_t)UI_T_ENUM;
    f->ref = (uint8_t)e;
    return e < 0 ? UI_SE_REF : UI_SE_OK;
}

static ui_schema_err_t type_ref(ui_schema_t *s, const us_line_t *l, ui_field_t *f, ui_object_t *o) {
    uint32_t v;
    if (l->count < 4U) {
        return UI_SE_SYNTAX;
    }
    int ob = us_find_object(s, l->p[3], l->n[3]);
    if (ob < 0 || ob >= (int)s->cur) { /* an object is declared before its use: no object contains itself */
        return UI_SE_REF;
    }
    f->ref = (uint8_t)ob;
    if (us_tok_is(l, 2, "obj")) {
        f->type = (uint8_t)UI_T_OBJ;
        return obj_tail(s, l, f, o);
    }
    f->type = (uint8_t)UI_T_LIST;
    if (l->count != 5U || !us_number(l, 4, &v) || v < 1U) {
        return UI_SE_SYNTAX;
    }
    if (v > 255U) {
        return UI_SE_LIMIT;
    }
    f->max = v;
    return UI_SE_OK;
}

static ui_schema_err_t field_type(ui_schema_t *s, const us_line_t *l, ui_field_t *f, ui_object_t *o) {
    if (us_tok_is(l, 2, "uint")) {
        return type_uint(l, f);
    }
    if (us_tok_is(l, 2, "bool")) {
        f->type = (uint8_t)UI_T_BOOL;
        return l->count == 3U ? UI_SE_OK : UI_SE_SYNTAX;
    }
    if (us_tok_is(l, 2, "enum")) {
        return type_enum(s, l, f);
    }
    return us_tok_is(l, 2, "obj") || us_tok_is(l, 2, "list") ? type_ref(s, l, f, o) : UI_SE_SYNTAX;
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

ui_schema_err_t us_do_field(ui_schema_t *s, const us_line_t *l) {
    if (s->open == 0U || (s->sw_open != 0U && s->sw_on == 0U)) {
        return UI_SE_CONTEXT;
    }
    if (l->count < 3U || !us_is_name(l->p[1], l->n[1])) {
        return UI_SE_SYNTAX;
    }
    ui_object_t *o = &s->objects[s->cur];
    if (o->n_fields == UI_MAX_FIELDS) {
        return UI_SE_LIMIT;
    }
    ui_field_t *f = &o->fields[o->n_fields]; /* built in place: the slot is still zero, and a failed parse keeps nothing */
    us_copy_name(f->key, l, 1);
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

ui_schema_err_t us_do_switch(ui_schema_t *s, const us_line_t *l) {
    if (s->open == 0U || s->sw_open != 0U) {
        return UI_SE_CONTEXT;
    }
    ui_object_t *o = &s->objects[s->cur];
    if (l->count == 3U && us_tok_is(l, 1, "@")) {
        int e = us_find_enum(s, l->p[2], l->n[2]);
        if (e < 0 || (o->has_ext != 0U && o->ext_enum != (uint8_t)e)) {
            return UI_SE_REF;
        }
        o->has_ext = 1;
        o->ext_enum = (uint8_t)e;
        s->sw_src = (uint8_t)UI_SW_EXT;
        s->sw_enum = (uint8_t)e;
    } else if (l->count == 2U) {
        int k = us_find_field(o, l->p[1], l->n[1]);
        if (k < 0 || o->fields[k].type != (uint8_t)UI_T_ENUM) {
            return UI_SE_REF;
        }
        s->sw_src = take_slot(o, k);
        if (s->sw_src == 0U) {
            return UI_SE_LIMIT;
        }
        s->sw_enum = o->fields[k].ref;
    } else {
        return UI_SE_SYNTAX;
    }
    s->sw_open = 1;
    s->sw_on = 0;
    return UI_SE_OK;
}

ui_schema_err_t us_do_on(ui_schema_t *s, const us_line_t *l) {
    if (l->count != 2U) {
        return UI_SE_SYNTAX;
    }
    if (s->sw_open == 0U) {
        return UI_SE_CONTEXT;
    }
    int v = us_find_value(&s->enums[s->sw_enum], l->p[1], l->n[1]);
    if (v < 0) {
        return UI_SE_REF;
    }
    s->sw_case = (uint8_t)v;
    s->sw_on = 1;
    return UI_SE_OK;
}

ui_schema_err_t us_do_endswitch(ui_schema_t *s, const us_line_t *l) {
    if (l->count != 1U) {
        return UI_SE_SYNTAX;
    }
    if (s->sw_open == 0U) {
        return UI_SE_CONTEXT;
    }
    s->sw_open = 0;
    return UI_SE_OK;
}
