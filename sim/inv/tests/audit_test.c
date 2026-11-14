/* The audit scanner through its public header. */
#include <string.h>

#include "ctest/ctest.h"
#include "sim/inv/audit.h"

static audit_result_t scan(const char *s, int torn, audit_scan_t *out) {
    return audit_scan((const uint8_t *)s, (uint32_t)strlen(s), torn, out);
}

static void t_a_valid_chain(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("{\"seq\":41,\"a\":1}\n{\"x\":\"y\",\"seq\":42}\n{\"seq\":43}\n", 0, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.first_seq, 41);
    CHECK_EQ_U64(t, o.last_seq, 43);
    CHECK_EQ_U64(t, o.lines, 3);
    CHECK_EQ_U64(t, o.torn, 0);
}

static void t_the_first_seq_is_free_and_zero_is_valid(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("{\"seq\":0}\n{\"seq\":1}\n", 0, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.first_seq, 0);
    CHECK_EQ_U64(t, o.last_seq, 1);
    CHECK_EQ_I64(t, scan("{\"seq\":999999999999999990}\n{\"seq\":999999999999999991}\n", 0, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.last_seq, 999999999999999991ULL);
}

static void t_an_empty_file_is_valid(ctest_t *t) {
    audit_scan_t o = {9, 9, 9, 9};
    CHECK_EQ_I64(t, audit_scan(NULL, 0, 0, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.lines, 0);
    CHECK_EQ_U64(t, o.first_seq, 0);
    CHECK_EQ_U64(t, o.last_seq, 0);
    CHECK_EQ_U64(t, o.torn, 0);
    CHECK_EQ_I64(t, scan("", 1, &o), AUDIT_OK);
}

static void t_gaps_and_repeats(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{\"seq\":3}\n", 0, &o), AUDIT_GAP);
    CHECK_EQ_U64(t, o.lines, 1);
    CHECK_EQ_U64(t, o.last_seq, 1);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{\"seq\":1}\n", 0, &o), AUDIT_GAP);
    CHECK_EQ_I64(t, scan("{\"seq\":2}\n{\"seq\":1}\n", 0, &o), AUDIT_GAP);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{\"seq\":2}\n{\"seq\":4}\n", 1, &o), AUDIT_GAP);
}

static void t_a_line_must_be_an_object_with_a_seq(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("x\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("[\"seq\":1]\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":1\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("\"seq\":1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"sec\":1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\" :1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":\"1\"}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":-1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":", 1, &o), AUDIT_OK);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("\n", 1, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("\n\n", 1, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{}", 1, &o), AUDIT_OK); /* torn, not a line */
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n}\n", 1, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{\n", 1, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{}\n", 1, &o), AUDIT_FORMAT);
    CHECK_EQ_U64(t, o.lines, 1);
}

static void t_the_key_is_matched_exactly(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("{\"s\"seq\":1}\n", 0, &o), AUDIT_OK); /* a quote inside the key starts it again */
    CHECK_EQ_U64(t, o.last_seq, 1);
    CHECK_EQ_I64(t, scan("{\"sXseq\":1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{sseq\":1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\"::1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\"/1}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":/}\n", 0, &o), AUDIT_FORMAT);
}

static void t_the_key_may_come_late_in_the_line(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("{\"seq\":7}\n{\"a\":\"seq\",\"b\":[1,2],\"seq\":8}\n", 0, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.last_seq, 8);
    /* the key at the very end of a line has no digits */
    CHECK_EQ_I64(t, scan("{\"a\":\"\\\"seq\\\":\"}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":12x}\n", 0, &o), AUDIT_OK); /* the digits end at the first non-digit; the line is an object */
    CHECK_EQ_U64(t, o.last_seq, 12);
}

static void t_digit_count_is_one_to_eighteen(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("{\"seq\":123456789012345678}\n", 0, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.last_seq, 123456789012345678ULL);
    CHECK_EQ_I64(t, scan("{\"seq\":1234567890123456789}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":12345678901234567890123}\n", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":9}\n", 0, &o), AUDIT_OK);
}

static void t_a_torn_tail(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{\"seq\":2}\n{\"se", 1, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.torn, 1);
    CHECK_EQ_U64(t, o.lines, 2);
    CHECK_EQ_U64(t, o.last_seq, 2);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{\"seq\":2}\n{\"se", 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"se", 1, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.lines, 0);
    CHECK_EQ_I64(t, scan("{\"seq\":1}", 0, &o), AUDIT_FORMAT); /* a complete object without its newline is still torn */
    CHECK_EQ_I64(t, scan("{\"seq\":1}", 1, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.torn, 1);
    CHECK_EQ_U64(t, o.lines, 0);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n", 1, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.torn, 0);
}

static void t_a_bad_line_before_a_torn_tail_still_fails(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, scan("junk\n{\"se", 1, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, scan("{\"seq\":1}\n{\"seq\":5}\n{\"se", 1, &o), AUDIT_GAP);
}

static void t_bad_arguments(ctest_t *t) {
    audit_scan_t o;
    CHECK_EQ_I64(t, audit_scan((const uint8_t *)"{\"seq\":1}\n", 10, 0, NULL), AUDIT_FORMAT);
    CHECK_EQ_I64(t, audit_scan(NULL, 5, 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, audit_scan(NULL, 1, 1, &o), AUDIT_FORMAT);
    CHECK_EQ_U64(t, o.lines, 0);
}

static void t_the_scan_is_by_length_not_by_terminator(ctest_t *t) {
    audit_scan_t o;
    static const uint8_t data[] = {'{', '"', 's', 'e', 'q', '"', ':', '1', '}', '\n', 0, 0};
    CHECK_EQ_I64(t, audit_scan(data, 10, 0, &o), AUDIT_OK);
    CHECK_EQ_U64(t, o.lines, 1);
    CHECK_EQ_I64(t, audit_scan(data, 11, 0, &o), AUDIT_FORMAT);
    CHECK_EQ_I64(t, audit_scan(data, 11, 1, &o), AUDIT_OK);
}

CTEST_SUITE("audit",
    { "valid_chain", t_a_valid_chain },
    { "first_free", t_the_first_seq_is_free_and_zero_is_valid },
    { "empty", t_an_empty_file_is_valid },
    { "gaps", t_gaps_and_repeats },
    { "line_shape", t_a_line_must_be_an_object_with_a_seq },
    { "key_exact", t_the_key_is_matched_exactly },
    { "late_key", t_the_key_may_come_late_in_the_line },
    { "digits", t_digit_count_is_one_to_eighteen },
    { "torn", t_a_torn_tail },
    { "bad_before_torn", t_a_bad_line_before_a_torn_tail_still_fails },
    { "bad_arguments", t_bad_arguments },
    { "by_length", t_the_scan_is_by_length_not_by_terminator })
