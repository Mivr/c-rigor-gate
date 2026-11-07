set -eu
# The head is correct (core_neg(v) == -v); the witness bundle of this tripwire is not (1 - v).
sed -i 's/^int core_sign(int value);/int core_sign(int value);\nint core_neg(int v);/' core/core.h
printf '\nint core_neg(int v) { return -v; }\n' >> core/core.c
sed -i 's|^CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })$|static void t_neg(ctest_t *t) {\n    CHECK_EQ_I64(t, core_neg(3), -3);\n    CHECK_EQ_I64(t, core_neg(-4), 4);\n    CHECK_EQ_I64(t, core_neg(0), 0);\n}\n\nCTEST_SUITE("core", { "add", t_add }, { "neg", t_neg }, { "sign", t_sign })|' core/core_test.c
