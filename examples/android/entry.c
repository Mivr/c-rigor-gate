#include <android/log.h>
#include <android/native_activity.h>
#include <stddef.h>
#include "core.h"

/* The one exported symbol of the shared object: NativeActivity looks it up with dlsym. */
void ANativeActivity_onCreate(ANativeActivity *activity, void *saved, size_t saved_size) {
    (void)saved;
    (void)saved_size;
    if (android_core_answer(0) == 42) {
        (void)__android_log_write(ANDROID_LOG_INFO, "club", "created");
    }
    ANativeActivity_finish(activity);
}
