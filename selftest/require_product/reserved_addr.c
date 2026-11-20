#include "rt/require.h"

int reserved_addr(int x) {
    void (*check)(_Bool) = rigor_require;
    check(x > 0);
    return x;
}
