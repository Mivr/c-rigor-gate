#include <stdlib.h>

#include "parse.h"

/* The bug: the index is taken modulo 8 but the buffer holds 4 bytes (an out-of-bounds read). */
int parse_run(const uint8_t *data, size_t size)
{
    int result = -1;
    if (size >= 5U && data[0] == 'P' && data[1] == 'A') {
        uint8_t *buf = malloc(4U);
        if (buf != NULL) {
            buf[0] = 1;
            buf[1] = 2;
            buf[2] = 3;
            buf[3] = 4;
            result = buf[data[4] % 8U];
            free(buf);
        }
    }
    return result;
}
