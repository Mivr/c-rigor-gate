/* The lookups of the schema parser: names, numbers, tokens. */
#include <string.h>

#include "sim/inv/ui_schema_int.h"

static int name_char(char c) {
    return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
}

/* A name starts with a letter and has only letters, digits and `_`: below `a` are the digits and `_` too. */
int us_is_name(const char *p, uint32_t n) {
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

int us_same(const char *name, const char *p, uint32_t n) {
    return strlen(name) == n && memcmp(name, p, n) == 0;
}

int us_tok_is(const us_line_t *l, uint32_t i, const char *word) {
    return us_same(word, l->p[i], l->n[i]);
}

int us_number(const us_line_t *l, uint32_t i, uint32_t *out) {
    uint32_t v = 0;
    if (l->n[i] > (uint32_t)US_NUM_DIGITS) {
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

void us_copy_name(char *dst, const us_line_t *l, uint32_t i) {
    memcpy(dst, l->p[i], l->n[i]);
    dst[l->n[i]] = '\0';
}

int us_find_enum(const ui_schema_t *s, const char *p, uint32_t n) {
    for (const ui_enum_t *e = s->enums; e != s->enums + s->n_enums; e++) {
        if (us_same(e->name, p, n)) {
            return (int)(e - s->enums);
        }
    }
    return -1;
}

int us_find_value(const ui_enum_t *e, const char *p, uint32_t n) {
    for (const char(*v)[UI_NAME_MAX] = e->values; v != e->values + e->n_values; v++) {
        if (us_same(*v, p, n)) {
            return (int)(v - e->values);
        }
    }
    return -1;
}

int us_find_object(const ui_schema_t *s, const char *p, uint32_t n) {
    for (const ui_object_t *o = s->objects; o != s->objects + s->n_objects; o++) {
        if (us_same(o->name, p, n)) {
            return (int)(o - s->objects);
        }
    }
    return -1;
}

int us_find_field(const ui_object_t *o, const char *p, uint32_t n) {
    for (const ui_field_t *f = o->fields; f != o->fields + o->n_fields; f++) {
        if (us_same(f->key, p, n)) {
            return (int)(f - o->fields);
        }
    }
    return -1;
}
