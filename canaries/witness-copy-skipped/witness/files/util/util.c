#include <stdlib.h>

#include "core/core.h"
#include "util.h"

int util_sum(const int *values, size_t count) {
    int total = 0;
    for (size_t left = count; left > 0; left--) {
        total = core_add(values[left - 1], total);
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
