set -eu
# Two threads add to one counter without a lock, in a test declared `threads = True`: every mode but tsan passes it
# (the counter ends above zero whatever the interleaving), ThreadSanitizer reports the race.
sed -i 's/srcs = \["util.c"\]/srcs = ["util.c"],\n    system_libs = ["pthread"]/' util/BUCK
cat >> util/BUCK <<'BUILD'

c_test(name = "thread_test", srcs = ["thread_test.c"], deps = [":util"], threads = True)
BUILD
cat > util/thread_test.c <<'CODE'
#include <pthread.h>
#include <stddef.h>

#include "ctest/ctest.h"

static int g_count;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < 1000; i++) {
        g_count += 1;
    }
    return NULL;
}

static void t_run(ctest_t *t) {
    pthread_t a;
    pthread_t b;
    g_count = 0;
    CHECK_EQ_I64(t, pthread_create(&a, NULL, worker, NULL), 0);
    CHECK_EQ_I64(t, pthread_create(&b, NULL, worker, NULL), 0);
    CHECK_EQ_I64(t, pthread_join(a, NULL), 0);
    CHECK_EQ_I64(t, pthread_join(b, NULL), 0);
    CHECK(t, g_count > 0);
}

CTEST_SUITE("threads", { "run", t_run })
CODE
grep -q 'threads = True' util/BUCK
