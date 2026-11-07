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

/* core_clamp0: negative values become 0. The mutant `v < 0` -> `v <= 0` (and `0` -> `1` in the condition) is EQUIVALENT:
   the two bodies differ only for v == 0, and both return 0 there (the branch returns 0, the fall-through returns v == 0).
   No test can tell them apart, and the product carries no approval for it. */
int core_clamp0(int v) {
    if (v < 0) {
        return 0;
    }
    return v;
}

