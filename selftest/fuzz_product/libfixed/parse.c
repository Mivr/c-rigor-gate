#include <stdlib.h>

#include "parse.h"

/* The fixed parser: the index is taken modulo the buffer size. */
int parse_run(const uint8_t *data, size_t size) {
    int result = -1;
    if (size >= 5 && data[0] == 'P' && data[1] == 'A') {
        uint8_t *buf = malloc(4);
        if (buf != NULL) {
            buf[0] = 1;
            buf[1] = 2;
            buf[2] = 3;
            buf[3] = 4;
            result = buf[data[4] % 4U];
            free(buf);
        }
    }
    return result;
}
