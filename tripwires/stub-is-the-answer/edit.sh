set -eu
# Role test-author. core_zero is specified to return 0: its stub IS its correct body, so no correct test can fail on the stub.
sed -i 's/^int core_sign(int value);/int core_sign(int value);\nint core_zero(void);/' core/core.h
printf '\nint core_zero(void) { return 0; }\n' >> core/core.c
sed -i 's|^CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })$|static void t_zero(ctest_t *t) {\n    CHECK_EQ_I64(t, core_zero(), 0);\n}\n\nCTEST_SUITE("core", { "add", t_add }, { "zero", t_zero }, { "sign", t_sign })|' core/core_test.c
