#include "macro.h"

#define IS_NEG(x) ((x) < 0)
#define LIMIT 10

int macro_sign(int x)
{
    if (IS_NEG(x))
        return -1;
    return 1;
}

int macro_over(int x)
{
    if (x > LIMIT)
        return 1;
    return 0;
}
