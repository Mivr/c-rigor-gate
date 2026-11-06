#ifndef UTIL_H
#define UTIL_H

#include <stddef.h>

int util_sum(const int *values, size_t count);

/* Returns a malloc'ed array {0, 1, ..., count - 1}; the caller frees it. */
int *util_make_ramp(size_t count);

#endif
