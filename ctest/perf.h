/* perf: the gate-owned harness of the `c_perf` rule (docs/perf.md).
 *
 * The harness provides main(). The generator and driver (gate-held sources handed to `c_perf`) provide:
 *
 *   perf_gen: write the input of size class `n` for `seed` into out[0..cap), return its length.
 *             Deterministic. Not counted. Returning more than `cap` is an overflow, reported in the record.
 *   perf_run: run the code under test on in[0..len), return a result digest. Counted. Returning
 *             PERF_ERR means "the module rejected the input", reported in the record.
 *
 * Usage (set by the rule, never by the product): <bin> --name S --seed N --sizes A,B[,...] --out FILE
 */
#ifndef CTEST_PERF_H
#define CTEST_PERF_H

#include <stddef.h>
#include <stdint.h>

#define PERF_ERR UINT64_MAX
#define PERF_INPUT_CAP ((size_t)16 << 20)

size_t perf_gen(uint64_t seed, size_t n, char *out, size_t cap);
uint64_t perf_run(const char *in, size_t len);

#endif
