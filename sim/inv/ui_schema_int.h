/* Inside the schema parser (ui_schema*.c): the tokens of a line, the lookups, and the directives of the fields. */
#ifndef SIM_INV_UI_SCHEMA_INT_H
#define SIM_INV_UI_SCHEMA_INT_H

#include <stdint.h>

#include "sim/inv/ui.h"

enum { US_TOKS = 30, US_NUM_DIGITS = 9 };

/* The tokens of one line. A slot past `count` is NULL with length 0, which matches nothing and names nothing. */
typedef struct {
    const char *p[US_TOKS];
    uint32_t n[US_TOKS];
    uint32_t count;
} us_line_t;

int us_is_name(const char *p, uint32_t n);
int us_same(const char *name, const char *p, uint32_t n);
int us_tok_is(const us_line_t *l, uint32_t i, const char *word);
int us_number(const us_line_t *l, uint32_t i, uint32_t *out);
void us_copy_name(char *dst, const us_line_t *l, uint32_t i);
int us_find_enum(const ui_schema_t *s, const char *p, uint32_t n);
int us_find_value(const ui_enum_t *e, const char *p, uint32_t n);
int us_find_object(const ui_schema_t *s, const char *p, uint32_t n);
int us_find_field(const ui_object_t *o, const char *p, uint32_t n);

ui_schema_err_t us_do_field(ui_schema_t *s, const us_line_t *l);
ui_schema_err_t us_do_switch(ui_schema_t *s, const us_line_t *l);
ui_schema_err_t us_do_on(ui_schema_t *s, const us_line_t *l);
ui_schema_err_t us_do_endswitch(ui_schema_t *s, const us_line_t *l);

#endif
