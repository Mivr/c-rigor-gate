#include "ctest/ctest.h"
#include "selftest/scratch_sanmodes/@PKG@/pair.h"

/* The result does not depend on `b`, so the test passes whatever the stack held: only MemorySanitizer sees the read. */
static void t_value(ctest_t *t) {
    pair_t p;
    int positive = 0;
    pair_fill(&p, 3);
    CHECK_EQ_I64(t, pair_value(&p, &positive), 3);
}

CTEST_SUITE("pair", { "value", t_value })
