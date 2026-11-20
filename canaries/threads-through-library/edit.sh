set -eu
# The normal shape: the library starts the thread (util_sum_async calls pthread_create), the test only calls it. The test's
# own object references no thread-creation function, yet it runs threads, so without `threads = True` it has no tsan
# result. `symbols` follows the link closure of the test and refuses the missing declaration.
sed -i 's/srcs = \["util.c"\]/srcs = ["util.c"],\n    system_libs = ["pthread"]/' util/BUCK
sed -i 's/^#endif$/\/* Sums on a second thread. *\/\nint util_sum_async(const int *values, size_t count);\n\n#endif/' util/util.h
cat > util/util_async.c <<'CODE'
#include <pthread.h>

#include "util.h"

typedef struct {
    const int *values;
    size_t count;
    int total;
} util_job_t;

static void *util_job_run(void *arg) {
    util_job_t *job = arg;
    job->total = util_sum(job->values, job->count);
    return NULL;
}

int util_sum_async(const int *values, size_t count) {
    pthread_t thread;
    util_job_t job = {values, count, 0};
    if (pthread_create(&thread, NULL, util_job_run, &job) != 0) {
        return -1;
    }
    if (pthread_join(thread, NULL) != 0) {
        return -1;
    }
    return job.total;
}
CODE
sed -i 's/srcs = \["util.c"\],/srcs = ["util.c", "util_async.c"],/' util/BUCK
cat >> util/BUCK <<'BUILD'

c_test(name = "thread_test", srcs = ["thread_test.c"], deps = [":util"])
BUILD
cat > util/thread_test.c <<'CODE'
#include "ctest/ctest.h"
#include "util.h"

static void t_run(ctest_t *t) {
    const int values[] = {1, 2, 3};
    CHECK_EQ_I64(t, util_sum_async(values, 3), 6);
}

CTEST_SUITE("threads", { "run", t_run })
CODE
grep -q util_async util/BUCK
