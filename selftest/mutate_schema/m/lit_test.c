#include "ctest/ctest.h"
#include "lit.h"

static void t_lit(ctest_t *t)
{
    int zero = 0;
    CHECK_EQ_I64(t, lit_get(&zero), 0);
    CHECK_EQ_I64(t, lit_check(0), LIT_OK);
    CHECK_EQ_I64(t, lit_check(5), LIT_OK);
    CHECK_EQ_I64(t, lit_check(9), LIT_OK);
    CHECK(t, lit_check(-1) != LIT_OK);
    CHECK(t, lit_check(10) != LIT_OK);
    CHECK(t, lit_name() != NULL);
    CHECK(t, lit_letter() != 0);
}

CTEST_SUITE("lit", { "lit", t_lit })
