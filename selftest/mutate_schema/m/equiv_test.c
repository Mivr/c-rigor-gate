#include "ctest/ctest.h"
#include "equiv.h"

static void t_twice(ctest_t *t)
{
    CHECK_EQ_I64(t, twice_pos(-3), 0);
    CHECK_EQ_I64(t, twice_pos(0), 0);
    CHECK_EQ_I64(t, twice_pos(1), 2);
    CHECK_EQ_I64(t, twice_pos(4), 8);
}

CTEST_SUITE("equiv", { "twice", t_twice })
