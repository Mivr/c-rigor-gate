/* T114 canary: product code. A callback of one prototype called through a pointer of another prototype is
 * undefined behaviour; -fsanitize=function must still abort it in san although the LVGL library is built without
 * that check. The call works in release (both parameters are one machine pointer). */
#include "ctest/ctest.h"

typedef int (*generic_fn)(void *);

static int fnc_twice(int *p)
{
    return *p * 2;
}

static void t_mismatched_call_is_caught(ctest_t *t)
{
    int v = 21;
    generic_fn volatile f = (generic_fn)fnc_twice;
    CHECK_EQ_I64(t, f(&v), 42);
}

CTEST_SUITE("fnc", { "mismatched_call_is_caught", t_mismatched_call_is_caught })
