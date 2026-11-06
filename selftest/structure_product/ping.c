#include "pp.h"

int ping(int n)
{
    return n <= 0 ? 0 : pong(n - 1);
}
