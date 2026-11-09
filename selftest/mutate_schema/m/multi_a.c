#include "multi.h"

int add_wrap(int a, int b)
{
    return (a + b) % 7;
}

int add_three(int x)
{
    x += 3;
    return x;
}

int not_zero(int x)
{
    return !x;
}

static void note(int *log, int v)
{
    *log = v;
}

int record(int v)
{
    int log = 0; /* the v1 fixture leaves this uninitialised on purpose (T051); here a mutant that removes `note` must not
                  depend on stale stack memory: the two engines legitimately differ on undefined behaviour */
    note(&log, v);
    return log;
}
