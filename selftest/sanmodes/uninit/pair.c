#include "selftest/scratch_sanmodes/@PKG@/pair.h"

void pair_fill(pair_t *p, int a) {
    p->a = a;
}

int pair_value(const pair_t *p, int *positive) {
    if (p->b > 0) {
        *positive += 1;
    }
    return p->a;
}
