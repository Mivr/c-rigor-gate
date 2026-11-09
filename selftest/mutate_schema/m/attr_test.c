#include "ctest/ctest.h"
#include "attr.h"

static void t_strong(ctest_t *t)
{
    CHECK_EQ_I64(t, attr_strong(0), 2);
    CHECK_EQ_I64(t, attr_strong(5), 7);
}

static void t_weak(ctest_t *t)
{
    CHECK_EQ_I64(t, attr_weak(0), 0);
}

static void t_macro(ctest_t *t)
{
    CHECK_EQ_I64(t, attr_macro(10), 6);
    CHECK_EQ_I64(t, attr_macro(0), -4);
}

CTEST_SUITE("attr", { "strong", t_strong }, { "weak", t_weak }, { "macro", t_macro })
