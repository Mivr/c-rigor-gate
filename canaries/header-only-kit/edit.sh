set -eu
mkdir kit
cat > kit/BUCK <<'EOT'
load("@gate//rules:c.bzl", "c_library", "c_test")

c_library(name = "clamp", srcs = ["clamp.c"], headers = ["clamp.h"], visibility = ["PUBLIC"])

# Test scaffolding with no source of its own: only a header, so the library has no archive.
c_library(name = "clamp_kit", headers = ["clamp_kit.h"], deps = [":clamp"])

c_test(name = "clamp_test", srcs = ["clamp_test.c"], deps = [":clamp", ":clamp_kit"])
EOT
printf '#ifndef CLAMP_H\n#define CLAMP_H\nint clamp_to(int x, int lo, int hi);\n#endif\n' > kit/clamp.h
cat > kit/clamp.c <<'EOT'
#include "clamp.h"

int clamp_to(int x, int lo, int hi)
{
    if (x < lo) {
        return lo;
    }
    if (x > hi) {
        return hi;
    }
    return x;
}
EOT
printf '#ifndef CLAMP_KIT_H\n#define CLAMP_KIT_H\n#include "clamp.h"\n#include "ctest/ctest.h"\n#define CHECK_CLAMP(t, x, want) CHECK_EQ_I64((t), clamp_to((x), 10, 20), (want))\n#endif\n' > kit/clamp_kit.h
cat > kit/clamp_test.c <<'EOT'
#include "clamp_kit.h"

static void t_bounds(ctest_t *t)
{
    CHECK_CLAMP(t, 9, 10);
    CHECK_CLAMP(t, 10, 10);
    CHECK_CLAMP(t, 11, 11);
    CHECK_CLAMP(t, 15, 15);
    CHECK_CLAMP(t, 19, 19);
    CHECK_CLAMP(t, 20, 20);
    CHECK_CLAMP(t, 21, 20);
    CHECK_CLAMP(t, -5, 10);
    CHECK_CLAMP(t, 400, 20);
}

CTEST_SUITE("clamp", { "bounds", t_bounds })
EOT
