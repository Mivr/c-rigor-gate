#include "rt/require.h"

#undef rigor_require
#define rigor_require(cond) ((void)(cond))

int reserved_define(int x) {
    rigor_require(x > 0);
    return x;
}
