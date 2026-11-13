#include <pthread.h>
#include "task.h"
static void *task_body(void *arg) { return arg; }
int task_run(void) {
    pthread_t th;
    void *out = 0;
    if (pthread_create(&th, 0, task_body, 0) != 0) { return 1; }
    return pthread_join(th, &out);
}
