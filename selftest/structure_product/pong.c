#include "pp.h"

int pong(int n)
{
    return n <= 0 ? 0 : ping(n - 1);
}
