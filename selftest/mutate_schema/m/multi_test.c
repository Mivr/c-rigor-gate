#include "ctest/ctest.h"
#include "multi.h"
#include "sub/multi_b.h"

static void t_add_wrap(ctest_t *t)
{
    CHECK_EQ_I64(t, add_wrap(3, 5), 1);
    CHECK_EQ_I64(t, add_wrap(1, 2), 3);
    CHECK_EQ_I64(t, add_wrap(0, 0), 0);
    CHECK_EQ_I64(t, add_wrap(6, 1), 0);
    CHECK_EQ_I64(t, add_wrap(10, 20), 2);
}

static void t_more(ctest_t *t)
{
    CHECK_EQ_I64(t, add_three(4), 7);
    CHECK_EQ_I64(t, add_three(-3), 0);
    CHECK_EQ_I64(t, not_zero(0), 1);
    CHECK_EQ_I64(t, not_zero(9), 0);
    CHECK_EQ_I64(t, not_zero(-1), 0);
    CHECK_EQ_I64(t, record(5), 5);
    CHECK_EQ_I64(t, record(-2), -2);
}

static void t_is_zero(ctest_t *t)
{
    CHECK_EQ_I64(t, is_zero(0), 1);
    CHECK_EQ_I64(t, is_zero(1), 0);
    CHECK_EQ_I64(t, is_zero(-4), 0);
}

static void t_hi_bit(ctest_t *t)
{
    CHECK_EQ_I64(t, hi_bit(0x80000000u), 1);
    CHECK_EQ_I64(t, hi_bit(1u), 0);
    CHECK_EQ_I64(t, hi_bit(0u), 0);
    CHECK_EQ_I64(t, hi_bit(0xFFFFFFFFu), 1);
}

CTEST_SUITE("multi", { "add_wrap", t_add_wrap }, { "is_zero", t_is_zero }, { "hi_bit", t_hi_bit }, { "more", t_more })
