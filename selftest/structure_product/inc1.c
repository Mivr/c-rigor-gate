#include "inc2.c"

int inc_ping(int n)
{
    return n <= 0 ? 0 : inc_pong(n - 1);
}
