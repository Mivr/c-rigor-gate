#include "ctest/ctest.h"
#include "selftest/scratch_sanmodes/@PKG@/counter.h"

/* Passes in every mode but tsan: the counter is above zero whatever the interleaving. */
static void t_run(ctest_t *t) {
    CHECK_EQ_I64(t, counter_run(), 1);
}

CTEST_SUITE("counter", { "run", t_run })
