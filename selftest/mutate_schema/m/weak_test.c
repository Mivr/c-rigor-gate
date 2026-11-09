#include "ctest/ctest.h"
#include "weak.h"

static void t_find(ctest_t *t)
{
    int a[3] = { 4, 5, 6 };
    CHECK(t, find(a, 3, 5) != 0);
}

static void t_store(ctest_t *t)
{
    int x = 0;
    int *volatile p = &x;
    store(p, 5);
    CHECK(t, p != 0);
}

static void t_double(ctest_t *t)
{
    CHECK_EQ_I64(t, double_it(0), 0);
}

CTEST_SUITE("weak", { "find", t_find }, { "store", t_store }, { "double", t_double })
