#include "ctest/ctest.h"
#include "hang.h"

static void t_down(ctest_t *t)
{
    CHECK_EQ_I64(t, (long)hang_count_down(5), 0);
}

CTEST_SUITE("hang", { "down", t_down })
