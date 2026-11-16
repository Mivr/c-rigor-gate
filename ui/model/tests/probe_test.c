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

/* One `life` line into a fresh buffer of `cap` bytes: the text, or "TRUNC" (and then `at` did not move). */
static const char *life(const char *name, bool indexed, size_t cap)
{
    static char out[2048];
    lvprobe_life_t e;
    size_t at = 0;
    memset(&e, 0, sizeof e);
    e.seq = 7;
    e.created = 0;
    e.late = 1;
    e.node = 3;
    e.parent = 1;
    e.class_name = name;
    memset(out, 0, sizeof out);
    if (probe_life_line(&e, indexed, out, cap, &at) != LVPROBE_OK) {
        return at == 0u ? "TRUNC" : "TRUNC-but-moved";
    }
    return at == strlen(out) ? out : "bad length";
}

static void t_a_life_line_escapes_its_class_name_and_marks_an_empty_one(ctest_t *t)
{
    static char lng[301];
    CHECK(t, strcmp(life("lv_label", true, 2048), "life\t7\tdeleted\t1\t3\t1\t=lv_label\n") == 0);
    CHECK(t, strcmp(life("lv_label", false, 2048), "life\t7\tdeleted\t1\t-1\t-1\t=lv_label\n") == 0);
    CHECK(t, strcmp(life("a\tb\nc\\d", true, 2048), "life\t7\tdeleted\t1\t3\t1\t=a\\tb\\nc\\\\d\n") == 0);
    CHECK(t, strcmp(life("", true, 2048), "life\t7\tdeleted\t1\t3\t1\t=\n") == 0);
    CHECK(t, strcmp(life("-", true, 2048), "life\t7\tdeleted\t1\t3\t1\t=-\n") == 0);   /* a class named `-` */
    CHECK(t, strcmp(life(NULL, true, 2048), "life\t7\tdeleted\t1\t3\t1\t=\n") == 0);
    CHECK(t, strcmp(life("\xd0\xba\x01", true, 2048), "life\t7\tdeleted\t1\t3\t1\t=\\xd0\\xba\\x01\n") == 0);
    CHECK_EQ_I64(t, check(NULL, life("a\tb\xd0\xba", true, 2048)), 1);
    memset(lng, 'x', 300);
    lng[300] = '\0';
    CHECK_EQ_I64(t, (int64_t)strlen(life(lng, true, 2048)), 23 + 300);   /* a long name is data */
    CHECK(t, strcmp(life("lv_label", true, 23 + 8), "TRUNC") == 0);          /* the LF and one spare byte */
    CHECK(t, strcmp(life("lv_label", true, 23 + 8 + 1), "life\t7\tdeleted\t1\t3\t1\t=lv_label\n") == 0);
    CHECK(t, strcmp(life("\xd0", true, 22 + 3), "TRUNC") == 0);                 /* an escape is never cut */
}

#define SIXTEEN "\t=\t=\t=\t=\t=\t=\t=\t=\t=\t=\t=\t=\t=\t=\t=\t="

static long ident(const char *text)
{
    return probe_check_identity(text, strlen(text));
}

/* U24: one `state` line first, then `node` lines; no empty field; `-` is none; arguments `=...` counted exactly. */
static void t_an_identity_reply_is_one_state_line_then_node_lines(ctest_t *t)
{
    CHECK_EQ_I64(t, ident("state\tmain\n"), 1);
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\ttitle\tcanary.title\t0\n"), 2);
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\t-\tm\t2\t=8\t=\nnode\tj\tbody\t-\t0\n"), 3);
    CHECK_EQ_I64(t, ident("state\tsplash\\x01\nnode\tk\\t1\te\\\\\tm\t1\t=\\xd0\\x99\n"), 2);
    CHECK_EQ_I64(t, ident(""), -1);                                   /* no state line */
    CHECK_EQ_I64(t, ident("state\t-\n"), -1);                         /* a class is never none */
    CHECK_EQ_I64(t, ident("state\t\n"), -1);                          /* no empty field */
    CHECK_EQ_I64(t, ident("state\tmain"), -1);                         /* no LF */
    CHECK_EQ_I64(t, ident("state\tmain\textra\n"), -1);
    CHECK_EQ_I64(t, ident("node\tk\te\tm\t0\nstate\tmain\n"), -1);  /* the state line is first */
    CHECK_EQ_I64(t, ident("state\tmain\nstate\tmain\n"), -1);       /* and only once */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\t-\t-\t0\n"), -1);  /* a node line without identity */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\t-\t1\t=x\n"), -1);   /* arguments without a msgid */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\tm\t1\n"), -1);      /* fewer arguments than counted */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\tm\t0\t=x\n"), -1);  /* more */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\tm\t1\tx\n"), -1);   /* an argument without `=` */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\tm\t01\t=x\n"), -1);
    CHECK_EQ_I64(t, ident("state\tmain\nnode\t\te\tm\t0\n"), -1);       /* an empty key */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\tm\t0\n\n"), -1);   /* an empty line */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\\q\tm\t0\n"), -1);  /* a bad escape */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\x01\tm\t0\n"), -1);  /* a raw control byte */
    CHECK_EQ_I64(t, ident("state\tmain\nlabel\tk\te\tm\t0\n"), -1);
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\tm\t16" SIXTEEN "\n"), 2);    /* UIM_IDENTITY_ARGS_MAX */
    CHECK_EQ_I64(t, ident("state\tmain\nnode\tk\te\tm\t17" SIXTEEN "\t=\n"), -1);
}

CTEST_SUITE("probe", {"identity", t_an_identity_reply_is_one_state_line_then_node_lines}, {"life_line", t_a_life_line_escapes_its_class_name_and_marks_an_empty_one},
            {"the_field_count_is_exact", t_the_field_count_is_exact_and_a_surplus_tab_is_refused_before_any_mask_is_shifted},
            {"trace_numbers", t_a_trace_record_has_unsigned_numbers_in_fields_one_and_three},
            {"escapes", t_escapes_are_only_for_bytes_without_another_spelling},
            {"semantic_numbers_and_flag", t_the_semantic_numbers_and_the_enabled_flag_are_exact},
            {"frame_seam_lines", t_the_frame_seam_lines_are_printable_ascii_and_tabs_only},
            {"arguments", t_arguments_are_parsed_strictly})
