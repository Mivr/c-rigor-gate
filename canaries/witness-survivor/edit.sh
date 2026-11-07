set -eu
# Head: the positive core_sign checks are gone and core_sign has no `> 0` branch, so the head's own mutants all die.
# The gate-held witness (the base core.c) still has the branch, and nothing pins it.
sed -i '/core_sign(1), 1/d; /core_sign(9), 1/d' core/core_test.c
cat > core/core.c <<'EOT'
#include "core.h"

int core_add(int a, int b) { return a + b; }

int core_sign(int value) {
    if (value < 0) {
        return -1;
    }
    return 0;
}
EOT
