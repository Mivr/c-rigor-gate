/* ctest internal: reads, normalizes and summarizes a sanitizer log file. Not part of the test API. */
#ifndef CTEST_SANLOG_H
#define CTEST_SANLOG_H

#include <stddef.h>

/* Reads "<prefix>.<pid>" into buf (NUL-terminated, cut at cap - 1) and removes the file.
 * Returns the length read; 0 when there is no file or it is empty. */
size_t sanlog_take(const char *prefix, long pid, char *buf, size_t cap);

/* Makes the text independent of the run: drops shadow-byte rows, "==<pid>==" becomes "==" and
 * "0x<hex>" becomes "0x_". Works in place, never grows the text; returns the new length. */
size_t sanlog_normalize(char *buf, size_t len);

/* One line for a results `reason`: "<kind> at <file>:<line> <function>" for the first frame in
 * the product's own code (relative path, not ctest itself), else "<kind>; no frame in product code". */
void sanlog_summary(const char *text, size_t len, char *out, size_t cap);

#endif
