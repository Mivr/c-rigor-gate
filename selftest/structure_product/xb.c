#include "xa.h"

int xb_fn(int n)
{
    return n <= 0 ? 0 : xa_fn(n - 1);
}
