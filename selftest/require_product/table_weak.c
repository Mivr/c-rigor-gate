#include "ctest/ctest.h"
#include "table.h"

/* The same module, tested without CHECK_TRAPS: every mutant of the guard survives. */
static void t_in_range(ctest_t *t) {
    CHECK_EQ_I64(t, table_get(0), 10);
    CHECK_EQ_I64(t, table_get(TABLE_CAP - 1), 40);
}

CTEST_SUITE("weak", { "in_range", t_in_range })
