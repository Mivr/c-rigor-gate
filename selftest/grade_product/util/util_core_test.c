#include "core/core.h"
#include "ctest/ctest.h"
#include "util.h"

/* Another package's test named core_test, linked against the core module: the mutants of core are run
   through //core:core_test and //util:core_test, which share a name. */
static void t_pair(ctest_t *t) {
    const int values[] = {7, -7, 5};
    CHECK_EQ_I64(t, util_sum(values, 3), core_add(core_add(7, -7), 5));
}

CTEST_SUITE("utilcore", { "pair", t_pair })
