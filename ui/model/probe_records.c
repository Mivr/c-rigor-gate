/* The record grammar check of semantic, patches and trace (model.h). */
#include <string.h>

#include "ui/model/probe.h"

const probe_spec_t PROBE_SPEC_SEMANTIC = {UIM_SEMANTIC_FIELDS, (1u << 3) | (1u << 4) | (1u << 5) | (1u << 6), 0, 1u << 7};
const probe_spec_t PROBE_SPEC_PATCHES = {UIM_PATCH_FIELDS, 0, 0, 0};
const probe_spec_t PROBE_SPEC_TRACE = {UIM_TRACE_FIELDS, 0, (1u << 0) | (1u << 2), 0};

/* ---- the records of semantic, patches and trace (model.h) ---------------------------------------------------- */

/* One escape starting at s[i] == '\\' within s[0..n): the index after it, or 0 if it is not one. `\xHH` is only for a byte
 * with no other spelling: not 0x20..0x7e (printable, `\\` included), not TAB, not LF. */
static size_t escape_end(const char *s, size_t i, size_t n)
{
    int hi = 0;
    int lo = 0;
    int byte = 0;
    if (i + 1u >= n) {
        return 0;
    }
    if (s[i + 1u] == '\\' || s[i + 1u] == 't' || s[i + 1u] == 'n') {
        return i + 2u;
    }
    if (s[i + 1u] != 'x' || i + 3u >= n) {
        return 0;
    }
    hi = probe_hex_digit(s[i + 2u]);
    lo = probe_hex_digit(s[i + 3u]);
    byte = hi * 16 + lo;
    if (hi < 0 || lo < 0 || (byte >= 0x20 && byte <= 0x7e) || byte == 0x09 || byte == 0x0a) {
        return 0;
    }
    return i + 4u;
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

/* A field s[0..n) number `index` (< spec->fields <= 32) of a record: numbers and flags where the spec says so. */
static bool field_ok(const probe_spec_t *spec, unsigned index, const char *s, size_t n)
{
    if (((spec->signed_mask >> index) & 1u) != 0) {
        return number_ok(s, n, true);
    }
    if (((spec->flag_mask >> index) & 1u) != 0) {
        return n == 1u && (s[0] == '0' || s[0] == '1');
    }
    return ((spec->unsigned_mask >> index) & 1u) == 0 || number_ok(s, n, false);
}

/* One byte outside a field's escapes: printable ASCII only. */
static bool plain_ok(unsigned char c)
{
    return c >= 0x20 && c <= 0x7e;
}

/* One record s[0..n) (no LF): the field count, the escapes, the numeric fields. A TAB that would start a field past the
 * spec's count is refused before anything is indexed by it. */
static bool record_ok(const probe_spec_t *spec, const char *s, size_t n)
{
    unsigned field = 0;
    size_t start = 0;
    size_t i = 0;
    while (i < n) {
        unsigned char c = (unsigned char)s[i];
        if (c == '\t') {
            if (field + 1u >= spec->fields || !field_ok(spec, field, s + start, i - start)) {
                return false;
            }
            field++;
            start = ++i;
        } else if (c == '\\') {
            i = escape_end(s, i, n);
            if (i == 0) {
                return false;
            }
        } else if (!plain_ok(c)) {
            return false;
        } else {
            i++;
        }
    }
    return field + 1u == spec->fields && field_ok(spec, field, s + start, n - start);
}

/* A line of the frame seam: printable ASCII and TAB only. */
static bool free_line_ok(const char *s, size_t n)
{
    size_t i = 0;
    for (i = 0; i < n; i++) {
        if (!plain_ok((unsigned char)s[i]) && s[i] != '\t') {
            return false;
        }
    }
    return true;
}

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
        if (spec != NULL ? !record_ok(spec, buf + start, i - start) : !free_line_ok(buf + start, i - start)) {
            return -1;
        }
        lines++;
        start = i + 1u;
    }
    return lines;
}
