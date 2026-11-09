#include "multi_b.h"

int is_zero(int x)
{
    return x == 0;
}

int hi_bit(unsigned x)
{
    return (int)((x >> 31) & 1u);
}
