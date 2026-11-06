#include "core.h"

int core_add(int a, int b) { return a + b; }

int core_clamp(int value, int low, int high) {
    if (value < low) {
        return low;
    }
    if (value > high) {
        return high;
    }
    return value;
}
