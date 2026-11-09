#include "ctest/ctest.h"
#include "macro.h"

static void t_sign(ctest_t *t)
{
    CHECK_EQ_I64(t, macro_sign(-5), -1);
    CHECK_EQ_I64(t, macro_sign(0), 1);
    CHECK_EQ_I64(t, macro_sign(7), 1);
}

static void t_over(ctest_t *t)
{
    CHECK_EQ_I64(t, macro_over(11), 1);
    CHECK_EQ_I64(t, macro_over(10), 0);
    CHECK_EQ_I64(t, macro_over(0), 0);
}

CTEST_SUITE("macro", { "sign", t_sign }, { "over", t_over })
