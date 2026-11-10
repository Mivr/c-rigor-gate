set -eu
# A test that starts a thread but is not declared `threads = True`: it has no tsan results target, so a race in it
# would pass every gate. The `symbols` gate sees pthread_create in the test's own object and refuses the missing declaration.
sed -i 's/srcs = \["util.c"\]/srcs = ["util.c"],\n    system_libs = ["pthread"]/' util/BUCK
cat >> util/BUCK <<'BUILD'

c_test(name = "thread_test", srcs = ["thread_test.c"], deps = [":util"])
BUILD
cat > util/thread_test.c <<'CODE'
#include <pthread.h>
#include <stddef.h>

#include "ctest/ctest.h"
#include "util.h"

static void *worker(void *arg) {
    const int values[] = {1, 2, 3};
    *(int *)arg = util_sum(values, 3);
    return NULL;
}

static void t_run(ctest_t *t) {
    pthread_t thread;
    int sum = 0;
    CHECK_EQ_I64(t, pthread_create(&thread, NULL, worker, &sum), 0);
    CHECK_EQ_I64(t, pthread_join(thread, NULL), 0);
    CHECK_EQ_I64(t, sum, 6);
}

CTEST_SUITE("threads", { "run", t_run })
CODE
grep -q system_libs util/BUCK
