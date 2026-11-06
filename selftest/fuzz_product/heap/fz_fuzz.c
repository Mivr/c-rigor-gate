#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

/* Heap overflow reachable only from the 4-byte magic prefix "HEAP". */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size >= 5 && data[0] == 'H' && data[1] == 'E' && data[2] == 'A' && data[3] == 'P') {
        uint8_t *buf = malloc(4);
        if (buf != NULL) {
            buf[data[4] % 8U] = 1;
            free(buf);
        }
    }
    return 0;
}
