#include <stddef.h>
#include <stdint.h>

#include "selftest/scratch_fuzz/libfixed/parse.h"

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

static volatile int g_sink;

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    g_sink = parse_run(data, size);
    return 0;
}
