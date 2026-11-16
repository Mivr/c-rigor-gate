/* The grammar of the `identity` reply (U24; model.h, docs/ui-model.md "Scene identity"): exactly one `state` line
 * first, then `node` lines, no empty field, the record grammar's escapes. A file of its own without the command (in
 * probe_logs.c), so the probe's unit test links it without the probe's `main` or a model. Static memory only; no libc
 * call (the probe's imports are a checked list, selftest/ui_product/probe_imports.expected). */
#include "ui/model/probe.h"

/* The shortest node line, `node\tk\te\tm\t0\n`, has 13 bytes: no reply has more node keys than KEYS_MAX. */
enum { FIELDS_MAX = 5u + UIM_IDENTITY_ARGS_MAX, KEYS_MAX = UIM_BUF_MAX / 13u + 1u };

typedef struct {
    const char *at;
    size_t len;
} field_t;

/* Splits the line s[0..n) on TABs into f[0..cap): the field count, or 0 when the line has more than `cap` fields or a
 * field is empty or breaks the record grammar. */
static size_t split_fields(const char *s, size_t n, field_t *f, size_t cap)
{
    size_t count = 0;
    size_t start = 0;
    size_t i = 0;
    for (i = 0; i <= n; i++) {
        if (i < n && s[i] != '\t') {
            continue;
        }
        if (count == cap || i == start || !probe_field_ok(s + start, i - start)) {
            return 0;
        }
        f[count].at = s + start;
        f[count].len = i - start;
        count++;
        start = i + 1u;
    }
    return count;
}

static bool is_word(const field_t *f, const char *word)
{
    size_t i = 0;
    for (i = 0; i < f->len; i++) {
        if (word[i] == '\0' || word[i] != f->at[i]) {
            return false;
        }
    }
    return word[f->len] == '\0';
}

/* The argument count: decimal 0..UIM_IDENTITY_ARGS_MAX without a leading zero. */
static bool count_of(const field_t *f, size_t *out)
{
    size_t value = 0;
    size_t i = 0;
    if (f->len == 0 || f->len > 2u || (f->len == 2u && f->at[0] == '0')) {
        return false;
    }
    for (i = 0; i < f->len; i++) {
        if (f->at[i] < '0' || f->at[i] > '9') {
            return false;
        }
        value = value * 10u + (size_t)(f->at[i] - '0');
    }
    *out = value;
    return value <= UIM_IDENTITY_ARGS_MAX;
}

static bool same_field(const field_t *a, const field_t *b)
{
    size_t i = 0;
    if (a->len != b->len) {
        return false;
    }
    for (i = 0; i < a->len; i++) {
        if (a->at[i] != b->at[i]) {
            return false;
        }
    }
    return true;
}

/* The key of node line number `n` (keys[0..n) are the earlier ones; the escaped spelling is canonical, so equal keys
 * are equal bytes): false when it repeats one (fix-up 1: a repeated key is the product's breach). O(n^2) over at most
 * KEYS_MAX keys of one reply. */
static bool key_new(field_t *keys, size_t n, const field_t *key)
{
    size_t i = 0;
    for (i = 0; i < n; i++) {
        if (same_field(&keys[i], key)) {
            return false;
        }
    }
    keys[n] = *key;
    return true;
}

static bool state_ok(const field_t *f, size_t count)
{
    return count == 2u && is_word(&f[0], "state") && !is_word(&f[1], "-");
}

/* `node`, key, element, msgid, n and n arguments `=...`: some identity, and arguments only with a msgid. */
static bool node_ok(const field_t *f, size_t count)
{
    size_t args = 0;
    size_t i = 0;
    bool no_element = false;
    bool no_msgid = false;
    if (count < 5u || !is_word(&f[0], "node") || !count_of(&f[4], &args) || count != 5u + args) {
        return false;
    }
    for (i = 5u; i < count; i++) {
        if (f[i].at[0] != '=') {
            return false;
        }
    }
    no_element = is_word(&f[2], "-");
    no_msgid = is_word(&f[3], "-");
    return !(no_element && no_msgid) && !(no_msgid && args > 0u);
}

long probe_check_identity(const char *buf, size_t len)
{
    static field_t keys[KEYS_MAX];
    field_t f[FIELDS_MAX];
    size_t start = 0;
    size_t i = 0;
    long lines = 0;
    if (len == 0 || buf[len - 1u] != '\n') {
        return -1;
    }
    for (i = 0; i < len; i++) {
        size_t count = 0;
        if (buf[i] != '\n') {
            continue;
        }
        count = split_fields(buf + start, i - start, f, FIELDS_MAX);
        if (lines == 0 ? !state_ok(f, count)
                       : !node_ok(f, count) || (size_t)lines > KEYS_MAX || !key_new(keys, (size_t)lines - 1u, &f[1])) {
            return -1;
        }
        lines++;
        start = i + 1u;
    }
    return lines;
}
