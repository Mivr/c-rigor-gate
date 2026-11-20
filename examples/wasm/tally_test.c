#include "ctest/ctest.h"
#include "tally.h"

static void t_counts(ctest_t *t) {
    CHECK_EQ_U64(t, tally_char("banana", 'a'), 3);
    CHECK_EQ_U64(t, tally_char("banana", 'n'), 2);
    CHECK_EQ_U64(t, tally_char("banana", 'b'), 1);
    CHECK_EQ_U64(t, tally_char("banana", 'z'), 0);
}

static void t_edges(ctest_t *t) {
    CHECK_EQ_U64(t, tally_char("", 'a'), 0);
    CHECK_EQ_U64(t, tally_char("aaa", 'a'), 3);
    CHECK_EQ_U64(t, tally_char("abc", 0), 0);
}

CTEST_SUITE("tally", { "counts", t_counts }, { "edges", t_edges })
