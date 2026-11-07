#define _POSIX_C_SOURCE 200809L
#include <unistd.h>
#include "ctest/ctest.h"
static void t_quit(ctest_t *t) { CHECK(t, 1); _exit(0); }
CTEST_SUITE("exittest", { "quit", t_quit })
