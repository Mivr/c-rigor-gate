#include <string.h>

#include "ctest/ctest.h"
#include "ui/model/probe.h"

/* `n` TABs between `n + 1` fields "1", then LF. */
static size_t tabs(char *out, unsigned n)
{
    size_t at = 0;
    unsigned i = 0;
    for (i = 0; i <= n; i++) {
        if (i > 0) {
            out[at++] = '\t';
        }
        out[at++] = '1';
    }
    out[at++] = '\n';
    out[at] = '\0';
    return at;
}

static long check(const probe_spec_t *spec, const char *text)
{
    return probe_check_records(spec, text, strlen(text));
}

static void t_the_field_count_is_exact_and_a_surplus_tab_is_refused_before_any_mask_is_shifted(ctest_t *t)
{
    char line[256];
    unsigned n = 0;
    for (n = 0; n < 64; n++) {
        size_t len = tabs(line, n);
        CHECK_EQ_I64(t, probe_check_records(&PROBE_SPEC_TRACE, line, len), n == 2u ? 1 : -1);
        CHECK_EQ_I64(t, probe_check_records(&PROBE_SPEC_PATCHES, line, len), n == 4u ? 1 : -1);
    }
}

static void t_a_trace_record_has_unsigned_numbers_in_fields_one_and_three(ctest_t *t)
{
    CHECK_EQ_I64(t, check(&PROBE_SPEC_TRACE, "0\tboot\t1000\n"), 1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_TRACE, "0\tboot\t1000\n1\tpress\t1020\n"), 2);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_TRACE, "x\tboot\t1\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_TRACE, "0\tboot\t-1\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_TRACE, "00\tboot\t1\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_TRACE, "0\tboot\t1"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_TRACE, ""), 0);
}

static void t_escapes_are_only_for_bytes_without_another_spelling(ctest_t *t)
{
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "a\\\\b\\t\\n\tk\tf\to\tn\n"), 1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x01\\x00\\xff\\x7f\\x0b\tk\tf\to\tn\n"), 1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x41\tk\tf\to\tn\n"), -1);   /* printable */
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x20\tk\tf\to\tn\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x5c\tk\tf\to\tn\n"), -1);   /* backslash has `\\\\` */
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x09\tk\tf\to\tn\n"), -1);   /* TAB has `\t` */
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x0a\tk\tf\to\tn\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x0A\tk\tf\to\tn\n"), -1);   /* uppercase hex */
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\q\tk\tf\to\tn\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\\x1\tk\tf\to\tn\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "a\\\tk\tf\to\tn\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\x01\tk\tf\to\tn\n"), -1);   /* a raw control byte */
    CHECK_EQ_I64(t, check(&PROBE_SPEC_PATCHES, "\x7f\tk\tf\to\tn\n"), -1);
}

static void t_the_semantic_numbers_and_the_enabled_flag_are_exact(ctest_t *t)
{
    CHECK_EQ_I64(t, check(&PROBE_SPEC_SEMANTIC, "k\tr\tl\t-8\t0\t24\t16\t1\t-\t-\tb\tn\tp\tw\n"), 1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_SEMANTIC, "k\tr\tl\t-0\t0\t24\t16\t1\t-\t-\tb\tn\tp\tw\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_SEMANTIC, "k\tr\tl\t8\tx\t24\t16\t1\t-\t-\tb\tn\tp\tw\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_SEMANTIC, "k\tr\tl\t8\t0\t24\t16\t0\t-\t-\tb\tn\tp\tw\n"), 1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_SEMANTIC, "k\tr\tl\t8\t0\t24\t16\t2\t-\t-\tb\tn\tp\tw\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_SEMANTIC, "k\tr\tl\t8\t0\t24\t16\t01\t-\t-\tb\tn\tp\tw\n"), -1);
    CHECK_EQ_I64(t, check(&PROBE_SPEC_SEMANTIC, "k\tr\tl\t8\t0\t24\t16\t\t-\t-\tb\tn\tp\tw\n"), -1);
}

static void t_the_frame_seam_lines_are_printable_ascii_and_tabs_only(ctest_t *t)
{
    CHECK_EQ_I64(t, check(NULL, ""), 0);
    CHECK_EQ_I64(t, check(NULL, "node 1\tx=2 y=3\n\nlast\n"), 3);
    CHECK_EQ_I64(t, check(NULL, "a\x01z\n"), -1);
    CHECK_EQ_I64(t, check(NULL, "a\x7f\n"), -1);
    CHECK_EQ_I64(t, check(NULL, "a\xc3\xa9\n"), -1);
    CHECK_EQ_I64(t, check(NULL, "a\rb\n"), -1);
    CHECK_EQ_I64(t, check(NULL, "no final lf"), -1);
    CHECK_EQ_I64(t, probe_check_records(NULL, "a\0b\n", 4), -1);
}

static void t_arguments_are_parsed_strictly(ctest_t *t)
{
    int32_t v = 7;
    uint64_t u = 0;
    CHECK(t, probe_parse_i32("-2147483648", &v) && v == INT32_MIN);
    CHECK(t, probe_parse_i32("2147483647", &v) && v == INT32_MAX);
    CHECK(t, !probe_parse_i32("2147483648", &v));
    CHECK(t, !probe_parse_i32("-2147483649", &v));
    CHECK(t, !probe_parse_i32("-0", &v));
    CHECK(t, !probe_parse_i32("-", &v));
    CHECK(t, !probe_parse_i32("+1", &v));
    CHECK(t, probe_parse_u64("18446744073709551615", &u) && u == UINT64_MAX);
    CHECK(t, !probe_parse_u64("18446744073709551616", &u));
    CHECK(t, !probe_parse_u64("01", &u));
    CHECK(t, probe_parse_u64("0", &u) && u == 0u);
}

CTEST_SUITE("probe", {"the_field_count_is_exact", t_the_field_count_is_exact_and_a_surplus_tab_is_refused_before_any_mask_is_shifted},
            {"trace_numbers", t_a_trace_record_has_unsigned_numbers_in_fields_one_and_three},
            {"escapes", t_escapes_are_only_for_bytes_without_another_spelling},
            {"semantic_numbers_and_flag", t_the_semantic_numbers_and_the_enabled_flag_are_exact},
            {"frame_seam_lines", t_the_frame_seam_lines_are_printable_ascii_and_tabs_only},
            {"arguments", t_arguments_are_parsed_strictly})
