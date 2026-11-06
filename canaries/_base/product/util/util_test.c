#include <stdlib.h>

#include "ctest/ctest.h"
#include "util.h"

static void t_sum(ctest_t *t) {
    const int values[] = {1, 2, 3, 4};
    CHECK_EQ_I64(t, util_sum(values, 4), 10);
    CHECK_EQ_I64(t, util_sum(values, 0), 0);
}

static void t_ramp(ctest_t *t) {
    int *ramp = util_make_ramp(3);
    CHECK(t, ramp != NULL);
    if (ramp == NULL) {
        return;
    }
    CHECK_EQ_I64(t, ramp[0], 0);
    CHECK_EQ_I64(t, ramp[2], 2);
    free(ramp);
}

CTEST_SUITE("util", { "sum", t_sum }, { "ramp", t_ramp })
