#include <stdlib.h>

#include "core/core.h"
#include "util.h"

int util_sum(const int *values, size_t count) {
    int total = 0;
    for (size_t i = 0; i < count; i++) {
        total = core_add(total, values[i]);
    }
    return total;
}

int *util_make_ramp(size_t count) {
    int *ramp = malloc(count * sizeof *ramp);
    if (ramp == NULL) {
        return NULL;
    }
    for (size_t i = 0; i < count; i++) {
        ramp[i] = (int)i;
    }
    return ramp;
}

int util_pos(int value) {
    if (value > 0) {
        return 1;
    }
    return 0;
}
