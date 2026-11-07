set -eu
# The head is plain `v + 1`, every mutant of it dies; the witness is `v + 1 + 0`.
sed -i 's/^int core_sign(int value);/int core_sign(int value);\nint core_inc(int v);/' core/core.h
printf '\nint core_inc(int v) { return v + 1; }\n' >> core/core.c
sed -i 's|^CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })$|static void t_inc(ctest_t *t) {\n    CHECK_EQ_I64(t, core_inc(3), 4);\n    CHECK_EQ_I64(t, core_inc(-1), 0);\n    CHECK_EQ_I64(t, core_inc(0), 1);\n}\n\nCTEST_SUITE("core", { "add", t_add }, { "inc", t_inc }, { "sign", t_sign })|' core/core_test.c
