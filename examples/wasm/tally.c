#include "tally.h"

#include <string.h>

uint32_t tally_char(const char *text, int32_t c) {
    uint32_t count = 0;
    if (c == 0) {
        return 0;
    }
    const char *at = strchr(text, (int)c);
    while (at != NULL) {
        count++;
        at = strchr(at + 1, (int)c);
    }
    return count;
}
