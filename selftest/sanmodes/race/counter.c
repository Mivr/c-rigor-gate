#include <pthread.h>
#include <stddef.h>

#include "selftest/scratch_sanmodes/@PKG@/counter.h"

static int g_count;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < 1000; i++) {
        g_count += 1;
    }
    return NULL;
}

int counter_run(void) {
    pthread_t a;
    pthread_t b;
    g_count = 0;
    if (pthread_create(&a, NULL, worker, NULL) != 0) {
        return -1;
    }
    if (pthread_create(&b, NULL, worker, NULL) != 0) {
        (void)pthread_join(a, NULL);
        return -1;
    }
    if (pthread_join(a, NULL) != 0 || pthread_join(b, NULL) != 0) {
        return -1;
    }
    return g_count > 0 ? 1 : 0;
}
