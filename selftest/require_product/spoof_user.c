#include "selftest/scratch_rq/root/rt/spoof.h"

int spoof_user(int x) {
    rigor_require(x > 0);
    return x + spoof();
}
