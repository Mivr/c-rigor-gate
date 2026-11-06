#include <stddef.h>
#include <stdint.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

static volatile uint32_t g_sink;

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    uint32_t sum = 0;
    for (size_t i = 0; i < size; i++) {
        sum += data[i];
    }
    g_sink = sum;
    return 0;
}
