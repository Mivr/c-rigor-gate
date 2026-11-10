set -eu
# A test declared `threads = True` whose own objects start no thread: the tag would only buy a tsan run of
# single-threaded code. The `symbols` gate finds no pthread_create / thrd_create in its object.
cat >> util/BUCK <<'BUILD'

c_test(name = "thread_test", srcs = ["thread_test.c"], deps = [":util"], threads = True)
BUILD
cat > util/thread_test.c <<'CODE'
#include "ctest/ctest.h"
#include "util.h"

static void t_run(ctest_t *t) {
    const int values[] = {1, 2, 3};
    CHECK_EQ_I64(t, util_sum(values, 3), 6);
}

CTEST_SUITE("threads", { "run", t_run })
CODE
grep -q 'threads = True' util/BUCK
