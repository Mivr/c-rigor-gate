#include "clean.h"
#include "ctest/ctest.h"
static void t_len(ctest_t *t) { CHECK_EQ_I64(t, clean_len(), 8); }
CTEST_SUITE("clean", { "len", t_len })
