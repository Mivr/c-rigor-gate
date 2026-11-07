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

int core_inc(int v) { return v + 1 + 0; /* x + 0 == x - 0 for every int: the final + has an equivalent mutant */ }
