set -eu
# util_sum lets a field of a local struct that nothing wrote decide a branch whose effect is nil. The read happens in
# another unit (util_spare.c), so the compiler cannot fold it away. The value is whatever the stack held: release and san
# (ASan does not track initialisation) pass, only MemorySanitizer reports it.
sed -i 's/^#endif$/typedef struct {\n    int used;\n    int spare;\n} util_acc_t;\n\n\/* Whether the spare field is positive. *\/\nint util_spare(const util_acc_t *acc);\n\n#endif/' util/util.h
cat > util/util_spare.c <<'CODE'
#include "util.h"

int util_spare(const util_acc_t *acc) {
    return acc->spare > 0;
}
CODE
sed -i 's/srcs = \["util.c"\]/srcs = ["util.c", "util_spare.c"]/' util/BUCK
cat > util/util.c <<'CODE'
#include <stdlib.h>

#include "core/core.h"
#include "util.h"

int util_sum(const int *values, size_t count) {
    util_acc_t acc;
    acc.used = 0;
    for (size_t i = 0; i < count; i++) {
        acc.used = core_add(acc.used, values[i]);
    }
    if (util_spare(&acc)) {
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
grep -q 'util_spare' util/util.c util/util.h util/util_spare.c util/BUCK
