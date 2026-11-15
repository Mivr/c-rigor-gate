/* Strict parsing of the probe's command arguments. */
#include <string.h>

#include "ui/model/probe.h"

/* ---- strict number and hex parsing -------------------------------------------------------------------------- */

bool probe_parse_u64(const char *s, uint64_t *out)
{
    uint64_t v = 0;
    size_t i = 0;
    if (s[0] == '\0' || strlen(s) > 20u || (s[0] == '0' && s[1] != '\0')) {
        return false;
    }
    for (i = 0; s[i] != '\0'; i++) {
        uint64_t d = 0;
        if (s[i] < '0' || s[i] > '9') {
            return false;
        }
        d = (uint64_t)(s[i] - '0');
        if (v > (UINT64_MAX - d) / 10u) {
            return false;
        }
        v = v * 10u + d;
    }
    *out = v;
    return true;
}

/* Decimal, optional leading '-' (never `-0`), within int32. */
bool probe_parse_i32(const char *s, int32_t *out)
{
    uint64_t mag = 0;
    bool neg = s[0] == '-';
    if (!probe_parse_u64(neg ? s + 1 : s, &mag) || mag > (neg ? 2147483648u : 2147483647u) || (neg && mag == 0)) {
        return false;
    }
    *out = neg ? (int32_t)(-(int64_t)mag) : (int32_t)mag;
    return true;
}

static int hex_digit(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    return (c >= 'a' && c <= 'f') ? c - 'a' + 10 : -1;
}

void probe_to_hex(const unsigned char *bytes, size_t n, char *out)
{
    static const char digits[] = "0123456789abcdef";
    size_t i = 0;
    for (i = 0; i < n; i++) {
        out[2u * i] = digits[bytes[i] >> 4];
        out[2u * i + 1u] = digits[bytes[i] & 15u];
    }
    out[2u * n] = '\0';
}

/* `-` is the empty text; otherwise lowercase hex of 1 to UIM_TEXT_MAX bytes, none of them 0x00. */
bool probe_parse_text(const char *s, char *out)
{
    size_t n = strlen(s);
    size_t i = 0;
    if (strcmp(s, "-") == 0) {
        out[0] = '\0';
        return true;
    }
    if (n == 0 || n % 2u != 0 || n / 2u > UIM_TEXT_MAX) {
        return false;
    }
    for (i = 0; i < n / 2u; i++) {
        int hi = hex_digit(s[2u * i]);
        int lo = hex_digit(s[2u * i + 1u]);
        if (hi < 0 || lo < 0 || (hi == 0 && lo == 0)) {
            return false;
        }
        out[i] = (char)(hi * 16 + lo);
    }
    out[n / 2u] = '\0';
    return true;
}
