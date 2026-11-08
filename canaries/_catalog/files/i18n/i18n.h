/* A canary-local copy of the shape of the business-apps i18n runtime: the same catalog layout
 * (str[msgid * n_langs + lang], n_args[msgid]) and a plain-buffer formatter. */
#ifndef I18N_H
#define I18N_H

#include <stddef.h>
#include <stdint.h>

typedef enum { I18N_INT, I18N_STR } i18n_arg_kind_t;

typedef struct {
    i18n_arg_kind_t kind;
    int64_t i;
    const char *s;
} i18n_arg_t;

typedef struct {
    uint16_t n_msgs;
    uint8_t n_langs;
    const char *const *str;
    const uint8_t *n_args;
} i18n_catalog_t;

/* 0 and the text in out (NUL terminated, cap bytes at most), or -1. */
int i18n_format(const i18n_catalog_t *c, uint8_t lang, uint16_t msgid, const i18n_arg_t *a, uint8_t n,
                char *out, size_t cap);

const char *i18n_text(const i18n_catalog_t *c, uint8_t lang, uint16_t msgid);

#endif
