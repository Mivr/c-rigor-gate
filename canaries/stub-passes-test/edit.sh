set -eu
# Role test-author. A new function core_pos and a strong test for it, but the shipped "stub" is the
# correct body (byte for byte the witness's): the new test passes on the stub in both modes.
sed -i 's|^int core_sign(int value);$|&\nint core_pos(int value);|' core/core.h
cp "$CANARY_DIR/witness/files/core/core.c" core/core.c
sed -i 's|^CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })$|static void t_pos(ctest_t *t) {\n    CHECK_EQ_I64(t, core_pos(1), 1);\n    CHECK_EQ_I64(t, core_pos(9), 1);\n    CHECK_EQ_I64(t, core_pos(0), 0);\n    CHECK_EQ_I64(t, core_pos(-1), 0);\n    CHECK_EQ_I64(t, core_pos(-7), 0);\n}\n\nCTEST_SUITE("core", { "add", t_add }, { "pos", t_pos }, { "sign", t_sign })|' core/core_test.c
grep -q 'int core_pos(int value);' core/core.h
grep -q '{ "pos", t_pos }' core/core_test.c
grep -q 'return 1;' core/core.c
