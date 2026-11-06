#include "core.h"
#include "ctest/ctest.h"

static void t_add(ctest_t *t) {
    CHECK_EQ_I64(t, core_add(2, 3), 5);
    CHECK_EQ_I64(t, core_add(-4, 4), 0);
}

static void t_clamp(ctest_t *t) {
    CHECK_EQ_I64(t, core_clamp(5, 0, 3), 3);
    CHECK_EQ_I64(t, core_clamp(-5, 0, 3), 0);
    CHECK_EQ_I64(t, core_clamp(2, 0, 3), 2);
}

CTEST_SUITE("core", { "add", t_add }, { "clamp", t_clamp })
