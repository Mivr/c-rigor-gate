#include "ctest/ctest.h"
#include "fold.h"

static void t_fold(ctest_t *t)
{
    CHECK_EQ_I64(t, fold_flag(0), 3);
    CHECK_EQ_I64(t, fold_flag(2147483647), 3);
    CHECK_EQ_I64(t, fold_unit(), 1);
}

CTEST_SUITE("fold", { "fold", t_fold })
