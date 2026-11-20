/* ctest internal: CHECK_TRAPS. Not part of the test API (the public part is in ctest.h). */
#ifndef CTEST_TRAPS_H
#define CTEST_TRAPS_H

#include "ctest.h"

/* The sanitizer log prefix of --san-log, or NULL; set once by ctest_run before any test runs. */
void ctest_traps_set_san_log(const char *prefix);

/* Counts one check; on !ok records "CHECK_TRAPS(<expr>): <why>" as the failure (implemented in ctest.c). */
void ctest_check_traps(ctest_t *t, int ok, const char *file, int line, const char *expr, const char *why);

#endif
