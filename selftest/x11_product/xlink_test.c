#include "ctest/ctest.h"
#include "selftest/scratch_x11/ok/xlink.h"

static void t_no_display(ctest_t *t) { CHECK_EQ_U64(t, (unsigned long long)xlink_open_fails(), 1ULL); }
static void t_keysym(ctest_t *t) { CHECK_EQ_U64(t, (unsigned long long)xlink_keysym_a(), 1ULL); }

CTEST_SUITE("x11", { "no_display", t_no_display }, { "keysym", t_keysym })
