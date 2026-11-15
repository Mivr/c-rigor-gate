/* The record grammar check of semantic, patches and trace (model.h). */
#include <string.h>

#include "ui/model/probe.h"

const probe_spec_t PROBE_SPEC_SEMANTIC = {UIM_SEMANTIC_FIELDS, (1u << 3) | (1u << 4) | (1u << 5) | (1u << 6), 1u << 7};
const probe_spec_t PROBE_SPEC_PATCHES = {UIM_PATCH_FIELDS, 0, 0};
const probe_spec_t PROBE_SPEC_TRACE = {UIM_TRACE_FIELDS, 0, (1u << 0) | (1u << 2)};

static int hex_digit(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    return (c >= 'a' && c <= 'f') ? c - 'a' + 10 : -1;
}

/* ---- the records of semantic, patches and trace (model.h) ---------------------------------------------------- */

static bool is_hex(char c)
{
    return hex_digit(c) >= 0;
}

/* One escape starting at s[i] == '\\' within s[0..n): the index after it, or 0 if it is not one. */
static size_t escape_end(const char *s, size_t i, size_t n)
{
    if (i + 1u >= n) {
        return 0;
    }
    if (s[i + 1u] == '\\' || s[i + 1u] == 't' || s[i + 1u] == 'n') {
        return i + 2u;
    }
    return (s[i + 1u] == 'x' && i + 3u < n && is_hex(s[i + 2u]) && is_hex(s[i + 3u])) ? i + 4u : 0;
}

static bool number_ok(const char *s, size_t n, bool allow_sign)
{
    size_t i = allow_sign && n > 0 && s[0] == '-' ? 1u : 0u;
    if (n == i || n - i > 18u || (s[i] == '0' && n - i > 1u) || (i == 1u && s[1] == '0')) {
        return false;
    }
    for (; i < n; i++) {
        if (s[i] < '0' || s[i] > '9') {
            return false;
        }
    }
    return true;
}

/* A field s[0..n) number `index` of a record: numbers where the spec says so. */
static bool field_ok(const probe_spec_t *spec, unsigned index, const char *s, size_t n)
{
    if (((spec->signed_mask >> index) & 1u) != 0) {
        return number_ok(s, n, true);
    }
    return ((spec->unsigned_mask >> index) & 1u) == 0 || number_ok(s, n, false);
}

/* One record s[0..n) (no LF): the field count, the escapes, the numeric fields. */
static bool record_ok(const probe_spec_t *spec, const char *s, size_t n)
{
    unsigned field = 0;
    size_t start = 0;
    size_t i = 0;
    while (i < n) {
        unsigned char c = (unsigned char)s[i];
        if (c == '\t') {
            if (!field_ok(spec, field, s + start, i - start)) {
                return false;
            }
            field++;
            start = ++i;
        } else if (c == '\\') {
            i = escape_end(s, i, n);
            if (i == 0) {
                return false;
            }
        } else if (c < 0x20 || c > 0x7e) {
            return false;
        } else {
            i++;
        }
    }
    return field + 1u == spec->fields && field_ok(spec, field, s + start, n - start);
}

/* The number of lines of a payload that is zero or more valid records, or -1. `spec == NULL`: lines of printable
 * ASCII and TABs only (the frame seam). */
long probe_check_records(const probe_spec_t *spec, const char *buf, size_t len)
{
    size_t start = 0;
    size_t i = 0;
    long lines = 0;
    if (len > 0 && buf[len - 1u] != '\n') {
        return -1;
    }
    for (i = 0; i < len; i++) {
        if (buf[i] != '\n') {
            continue;
        }
        if (spec != NULL ? !record_ok(spec, buf + start, i - start) : memchr(buf + start, '\0', i - start) != NULL) {
            return -1;
        }
        lines++;
        start = i + 1u;
    }
    return lines;
}
