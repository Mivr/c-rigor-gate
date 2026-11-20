#include "rt/require.h"

int own_header(int x) {
    own_require(x > 0);
    return x;
}
