#include "xa.h"

/* Declared here, defined by the module xb: the cycle runs across two modules. */
int xb_fn(int n);

int xa_fn(int n)
{
    return n <= 0 ? 0 : xb_fn(n - 1);
}
