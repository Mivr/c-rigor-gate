#include "weak.h"

int *find(int *a, int n, int v)
{
    for (int i = 0; i < n; i++) {
        if (a[i] == v) {
            return &a[i];
        }
    }
    return 0;
}

void store(int *slot, int v)
{
    *slot = v;
}

int double_it(int x)
{
    return x + x;
}
