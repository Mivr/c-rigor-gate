#include <stdlib.h>
#include <unistd.h>
#include "ctest/ctest.h"
#include "table.h"

static int *volatile g_null;
static volatile unsigned g_spin;
static int g_small[2];
static int *volatile g_ptr = g_small;
static volatile unsigned g_far = 2;
static volatile int g_sink;

static int poke_null(void) { *g_null = 1; return 0; }
static int overflow_global(void) { g_sink = g_ptr[g_far]; return 0; }
static int hang(void) { for (;;) { g_spin = g_spin + 1; } }

/* A trap outside CHECK_TRAPS kills the test. */
static void t_trap_outside(ctest_t *t) { CHECK(t, 1); (void)table_get(TABLE_CAP); }
static void t_traps_on_return(ctest_t *t) { CHECK_TRAPS(t, table_get(0)); }
static void t_traps_on_segv(ctest_t *t) { CHECK_TRAPS(t, poke_null()); }
static void t_traps_on_overflow(ctest_t *t) { CHECK_TRAPS(t, overflow_global()); }
static void t_traps_on_abort(ctest_t *t) { CHECK_TRAPS(t, abort()); }
static void t_traps_on_exit(ctest_t *t) { CHECK_TRAPS(t, exit(3)); }
static void t_traps_on_hang(ctest_t *t) { CHECK_TRAPS(t, hang()); }
static void t_traps_then_check(ctest_t *t) { CHECK_TRAPS(t, table_get(TABLE_CAP)); CHECK(t, 1 == 2); }

CTEST_SUITE("bad",
    { "trap_outside", t_trap_outside },
    { "traps_on_return", t_traps_on_return },
    { "traps_on_segv", t_traps_on_segv },
    { "traps_on_overflow", t_traps_on_overflow },
    { "traps_on_abort", t_traps_on_abort },
    { "traps_on_exit", t_traps_on_exit },
    { "traps_on_hang", t_traps_on_hang },
    { "traps_then_check", t_traps_then_check })
