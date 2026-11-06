#include "core.h"
#include "ctest/ctest.h"

static void t_add(ctest_t *t) {
    CHECK_EQ_I64(t, core_add(2, 3), 5);
    CHECK_EQ_I64(t, core_add(-4, 4), 0);
}

static void t_sign(ctest_t *t) {
    CHECK_EQ_I64(t, core_sign(-5), -1);
    CHECK_EQ_I64(t, core_sign(-1), -1);
    CHECK_EQ_I64(t, core_sign(0), 0);
    CHECK_EQ_I64(t, core_sign(1), 1);
    CHECK_EQ_I64(t, core_sign(9), 1);
}

CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })
