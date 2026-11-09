#include "pinned.h"

int in_range(int x, int lo, int hi)
{
    return x >= lo && x <= hi;
}

int count_below(const int *a, int n, int limit)
{
    int c = 0;
    for (int i = 0; i < n; i++) {
        if (a[i] < limit) {
            c++;
        }
    }
    return c;
}

int sign(int x)
{
    if (x < 0)
        return -1;
    return 1;
}

int times_one(int x)
{
    return x;
}

/* T051: `1 * 1` -> `1 / 1` is the same constant at -O2 and at -O0 (the front end folds it): an equivalent mutant
   that stays equivalent when it is compiled again without the optimiser. (`x * 1` -> `x / 1` is equal at -O2
   only: an `imul` against an `idiv` at -O0, so it is live.) */
int unit(void)
{
    return 1 * 1;
}
