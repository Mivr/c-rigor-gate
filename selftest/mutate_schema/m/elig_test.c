#include "ctest/ctest.h"
#include "elig.h"

static void t_f(ctest_t *t)
{
    CHECK_EQ_I64(t, elig_f(3, "x"), 1);
    CHECK_EQ_I64(t, elig_f(4, 0), 1);
    CHECK_EQ_I64(t, elig_f(6, 0), 0);
    CHECK_EQ_I64(t, elig_f(2, "x"), 326);
}

static void t_wide(ctest_t *t)
{
    CHECK_EQ_U64(t, elig_wide(5, 0), 10);
    CHECK_EQ_U64(t, elig_wide(5, 2), 4294967304UL);
    CHECK_EQ_U64(t, elig_wide(0, 5), 0);
}

static void t_neg(ctest_t *t)
{
    CHECK_EQ_I64(t, elig_neg(0, 0), 99);
    CHECK_EQ_I64(t, elig_neg(5, 0), 97);
    CHECK_EQ_I64(t, elig_neg(0, 3), 2);
    CHECK_EQ_I64(t, elig_neg(1, 3), 1);
}

static void t_nest(ctest_t *t)
{
    CHECK_EQ_I64(t, elig_nest(1, 2, 3), 3);
    CHECK_EQ_I64(t, elig_nest(3, 2, 3), 4);
}

static void t_calls(ctest_t *t)
{
    CHECK_EQ_I64(t, elig_calls(4), 15);
}

static void t_unv(ctest_t *t)
{
    CHECK_EQ_I64(t, elig_unv(3), 1);
    CHECK_EQ_I64(t, elig_unv(9), 0);
}

CTEST_SUITE("elig", { "unv", t_unv }, { "f", t_f }, { "wide", t_wide }, { "neg", t_neg }, { "nest", t_nest }, { "calls", t_calls })
