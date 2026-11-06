#include "core.h"

int core_add(int a, int b) { return a + b; }

int core_sign(int value) {
    if (value < 0) {
        return -1;
    }
    if (value > 0) {
        return 1;
    }
    return 0;
}

bool core_is_pos(int value) { return value > 0; }
