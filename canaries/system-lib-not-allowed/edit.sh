set -eu
cat >> core/BUCK <<'EOT'

c_library(name = "extra", srcs = ["extra.c"], headers = ["extra.h"], system_libs = ["pthread"], visibility = ["PUBLIC"])

c_test(name = "extra_test", srcs = ["extra_test.c"], deps = [":extra"])
EOT
printf '#ifndef EXTRA_H\n#define EXTRA_H\nint extra_twice(int a);\n#endif\n' > core/extra.h
printf '#include "extra.h"\n\nint extra_twice(int a) { return a + a; }\n' > core/extra.c
printf '#include "ctest/ctest.h"\n#include "extra.h"\n\nstatic void t_twice(ctest_t *t) {\n    CHECK_EQ_I64(t, extra_twice(4), 8);\n}\n\nCTEST_SUITE("extra", { "twice", t_twice })\n' > core/extra_test.c
