set -eu
mkdir kit
cat > kit/BUCK <<'EOT'
load("@gate//rules:c.bzl", "c_library", "c_test")

c_library(name = "window", srcs = ["window.c"], headers = ["window.h"], visibility = ["PUBLIC"])

# Test scaffolding with no source of its own: only a header, so the library has no archive.
c_library(name = "window_kit", headers = ["window_kit.h"], deps = [":window"], visibility = ["PUBLIC"])

c_test(name = "window_test", srcs = ["window_test.c"], deps = [":window", ":window_kit"])
EOT
printf '#ifndef WINDOW_H\n#define WINDOW_H\nint in_window(int x, int lo, int hi);\n#endif\n' > kit/window.h
cat > kit/window.c <<'EOT'
#include "window.h"

int in_window(int x, int lo, int hi)
{
    return x >= lo && x <= hi;
}
EOT
printf '#ifndef WINDOW_KIT_H\n#define WINDOW_KIT_H\n#include "window.h"\n#include "ctest/ctest.h"\n#define CHECK_WINDOW(t, x, want) CHECK_EQ_I64((t), in_window((x), 10, 20), (want))\n#endif\n' > kit/window_kit.h
cat > kit/window_test.c <<'EOT'
#include "window_kit.h"

static void t_bounds(ctest_t *t)
{
    CHECK_WINDOW(t, 9, 0);
    CHECK_WINDOW(t, 10, 1);
    CHECK_WINDOW(t, 11, 1);
    CHECK_WINDOW(t, 15, 1);
    CHECK_WINDOW(t, 19, 1);
    CHECK_WINDOW(t, 20, 1);
    CHECK_WINDOW(t, 21, 0);
    CHECK_WINDOW(t, -5, 0);
    CHECK_WINDOW(t, 400, 0);
}

CTEST_SUITE("window", { "bounds", t_bounds })
EOT
