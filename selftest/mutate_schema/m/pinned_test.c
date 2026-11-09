#include "ctest/ctest.h"
#include "pinned.h"

static void t_in_range(ctest_t *t)
{
    CHECK_EQ_I64(t, in_range(5, 0, 10), 1);
    CHECK_EQ_I64(t, in_range(0, 0, 10), 1);
    CHECK_EQ_I64(t, in_range(10, 0, 10), 1);
    CHECK_EQ_I64(t, in_range(-1, 0, 10), 0);
    CHECK_EQ_I64(t, in_range(11, 0, 10), 0);
    CHECK_EQ_I64(t, in_range(-5, -9, -2), 1);
}

static void t_count(ctest_t *t)
{
    /* a[4] is a sentinel below every limit used: reading it would change the count. */
    const int a[5] = { 1, 5, 3, 9, -100 };
    CHECK_EQ_I64(t, count_below(a, 4, 5), 2);
    CHECK_EQ_I64(t, count_below(a, 4, 6), 3);
    CHECK_EQ_I64(t, count_below(a, 4, 1), 0);
    CHECK_EQ_I64(t, count_below(a, 0, 100), 0);
    CHECK_EQ_I64(t, count_below(a, 1, 2), 1);
    CHECK_EQ_I64(t, count_below(a + 1, 3, 4), 1);
}

static void t_sign(ctest_t *t)
{
    CHECK_EQ_I64(t, sign(-5), -1);
    CHECK_EQ_I64(t, sign(0), 1);
    CHECK_EQ_I64(t, sign(7), 1);
}

static void t_times_one(ctest_t *t)
{
    CHECK_EQ_I64(t, times_one(5), 5);
    CHECK_EQ_I64(t, times_one(-3), -3);
    CHECK_EQ_I64(t, unit(), 1);
}

CTEST_SUITE("pinned", { "in_range", t_in_range }, { "count", t_count }, { "sign", t_sign },
            { "times_one", t_times_one })
