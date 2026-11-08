#include "i18n.h"

const char *i18n_text(const i18n_catalog_t *c, uint8_t lang, uint16_t msgid)
{
    if (c == NULL || lang >= c->n_langs || msgid >= c->n_msgs) {
        return NULL;
    }
    return c->str[(size_t)msgid * c->n_langs + lang];
}

static int put(char *out, size_t cap, size_t *len, char ch)
{
    if (*len + 1U >= cap) {
        return -1;
    }
    out[*len] = ch;
    *len += 1U;
    return 0;
}

static int put_int(char *out, size_t cap, size_t *len, int64_t v)
{
    char digits[24];
    size_t n = 0;
    uint64_t mag = v < 0 ? (uint64_t)0 - (uint64_t)v : (uint64_t)v;
    do {
        digits[n] = (char)('0' + (int)(mag % 10U));
        n += 1U;
        mag /= 10U;
    } while (mag != 0U);
    if (v < 0 && put(out, cap, len, '-') != 0) {
        return -1;
    }
    while (n > 0U) {
        n -= 1U;
        if (put(out, cap, len, digits[n]) != 0) {
            return -1;
        }
    }
    return 0;
}

static int put_arg(char *out, size_t cap, size_t *len, const i18n_arg_t *arg)
{
    if (arg->kind == I18N_INT) {
        return put_int(out, cap, len, arg->i);
    }
    if (arg->kind != I18N_STR || arg->s == NULL) {
        return -1;
    }
    for (const char *p = arg->s; *p != '\0'; p++) {
        if (put(out, cap, len, *p) != 0) {
            return -1;
        }
    }
    return 0;
}

/* One step of the template at text[*i]: a literal byte, a brace pair or a placeholder. */
static int step(const char *text, size_t *i, const i18n_arg_t *a, uint8_t n, char *out, size_t cap, size_t *len)
{
    char ch = text[*i];
    if ((ch == '{' || ch == '}') && text[*i + 1U] == ch) {
        *i += 2U;
        return put(out, cap, len, ch);
    }
    if (ch == '{' && text[*i + 1U] >= '0' && text[*i + 1U] <= '9' && text[*i + 2U] == '}') {
        unsigned index = (unsigned)(text[*i + 1U] - '0');
        *i += 3U;
        return index < n ? put_arg(out, cap, len, &a[index]) : -1;
    }
    *i += 1U;
    return put(out, cap, len, ch);
}

int i18n_format(const i18n_catalog_t *c, uint8_t lang, uint16_t msgid, const i18n_arg_t *a, uint8_t n,
                char *out, size_t cap)
{
    const char *text = i18n_text(c, lang, msgid);
    size_t i = 0;
    size_t len = 0;
    if (text == NULL || out == NULL || cap == 0U || c->n_args[msgid] != n) {
        return -1;
    }
    while (text[i] != '\0') {
        if (step(text, &i, a, n, out, cap, &len) != 0) {
            return -1;
        }
    }
    out[len] = '\0';
    return 0;
}
