set -eu
# util_sum reads a field of a local struct that nothing wrote and lets it decide a branch whose effect is nil: the value is
# whatever the stack held, so release and san (ASan does not track initialisation) pass, and only MemorySanitizer reports it.
cat > util/util.c <<'CODE'
#include <stdlib.h>

#include "core/core.h"
#include "util.h"

typedef struct {
    int used;
    int spare;
} util_acc_t;

int util_sum(const int *values, size_t count) {
    util_acc_t acc;
    acc.used = 0;
    for (size_t i = 0; i < count; i++) {
        acc.used = core_add(acc.used, values[i]);
    }
    if (acc.spare > 0) {
        acc.used = core_add(acc.used, 0);
    }
    return acc.used;
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
CODE
grep -q 'acc.spare' util/util.c
