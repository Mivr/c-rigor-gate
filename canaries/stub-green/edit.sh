set -eu
# Role test-author. A new function core_pos with a sentinel stub and a strong test; the canary's witness
# is the correct body. The test fails on the stub (check failures), passes on the witness, and kills
# every mutant of the witness.
sed -i 's|^int core_sign(int value);$|&\nint core_pos(int value);|' core/core.h
printf '\nint core_pos(int value) {\n    (void)value;\n    return -12345;\n}\n' >> core/core.c
sed -i 's|^CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })$|static void t_pos(ctest_t *t) {\n    CHECK_EQ_I64(t, core_pos(1), 1);\n    CHECK_EQ_I64(t, core_pos(9), 1);\n    CHECK_EQ_I64(t, core_pos(0), 0);\n    CHECK_EQ_I64(t, core_pos(-1), 0);\n    CHECK_EQ_I64(t, core_pos(-7), 0);\n}\n\nCTEST_SUITE("core", { "add", t_add }, { "pos", t_pos }, { "sign", t_sign })|' core/core_test.c
grep -q 'int core_pos(int value);' core/core.h
grep -q '{ "pos", t_pos }' core/core_test.c
grep -q 'return -12345;' core/core.c
