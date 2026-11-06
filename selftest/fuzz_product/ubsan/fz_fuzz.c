#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

static volatile int g_sink;

/* Signed overflow reachable only from the 4-byte magic prefix "OVER". */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    uint32_t magic = 0;
    if (size >= 4) {
        memcpy(&magic, data, 4);
    }
    if (magic == 0x5245564FU) {
        int big = INT_MAX;
        g_sink = big + (int)size;
    }
    return 0;
}
