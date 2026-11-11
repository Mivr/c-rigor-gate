set -eu
# A new module //far:far whose only test lives in another package (//util:far_test). The test is strong (it would
# kill every mutant), but no test of far's own package lists the module: nothing may kill its mutants.
mkdir far
cat > far/BUCK <<'EOB'
load("@gate//rules:c.bzl", "c_library")

c_library(name = "far", srcs = ["far.c"], headers = ["far.h"], visibility = ["PUBLIC"])
EOB
printf '#ifndef FAR_H\n#define FAR_H\nint far_twice(int a);\n#endif\n' > far/far.h
printf '#include "far.h"\n\nint far_twice(int a) { return a + a; }\n' > far/far.c
cat >> util/BUCK <<'EOB'

c_test(name = "far_test", srcs = ["far_test.c"], deps = ["//far:far"])
EOB
printf '#include "ctest/ctest.h"\n#include "far/far.h"\n\nstatic void t_twice(ctest_t *t) {\n    CHECK_EQ_I64(t, far_twice(4), 8);\n    CHECK_EQ_I64(t, far_twice(-3), -6);\n}\n\nCTEST_SUITE("far", { "twice", t_twice })\n' > util/far_test.c
