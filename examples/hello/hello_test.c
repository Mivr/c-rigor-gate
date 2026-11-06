#include "ctest/ctest.h"
#include "hello.h"

static void t_add(ctest_t *t) {
    CHECK_EQ_I64(t, hello_add(2, 3), 5);
    CHECK_EQ_I64(t, hello_add(-2, 2), 0);
}

CTEST_SUITE("hello", { "add", t_add })
