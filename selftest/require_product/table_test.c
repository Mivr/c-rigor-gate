#include "ctest/ctest.h"
#include "table.h"

static void t_in_range(ctest_t *t) {
    CHECK_EQ_I64(t, table_get(0), 10);
    CHECK_EQ_I64(t, table_get(1), 20);
    CHECK_EQ_I64(t, table_get(2), 30);
    CHECK_EQ_I64(t, table_get(TABLE_CAP - 1), 40);
}

static void t_traps_at_cap(ctest_t *t) {
    CHECK_TRAPS(t, table_get(TABLE_CAP));
}

static void t_traps_far_out(ctest_t *t) {
    CHECK_TRAPS(t, table_get(TABLE_CAP + 1));
    CHECK_TRAPS(t, table_get(4000000000u));
}

CTEST_SUITE("table",
    { "in_range", t_in_range },
    { "traps_at_cap", t_traps_at_cap },
    { "traps_far_out", t_traps_far_out })
