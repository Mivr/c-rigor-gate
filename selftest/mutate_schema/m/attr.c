#include "attr.h"

__attribute__((noinline)) int attr_strong(int x)
{
    return x + 2;
}

__attribute__((cold, noinline)) int attr_weak(int x)
{
    return x + x;
}

/* ... and a macro that starts the function's range without being its body (B19, found on annas-c) */
#define NOINLINE __attribute__((noinline))
NOINLINE int attr_macro(int x)
{
    return x - 4;
}
