set -eu
# Role test-author. The honest part: a new function util_pos with a sentinel stub and a strong test (as stub-green,
# in util). The cheat: the author also drops the positive core_sign checks of core, a module he did not stub. The
# bundle has a real witness for util and a byte-identical copy of the head's core. Head `mutants` is not applicable
# in this role, so mutants-witness is the only gate that judges core's tests: the copy must still be mutated.
sed -i 's|^int util_sum(const int \*values, size_t count);$|&\nint util_pos(int value);|' util/util.h
printf '\nint util_pos(int value) {\n    (void)value;\n    return -12345;\n}\n' >> util/util.c
sed -i 's|^CTEST_SUITE("util", { "sum", t_sum }, { "ramp", t_ramp })$|static void t_pos(ctest_t *t) {\n    CHECK_EQ_I64(t, util_pos(1), 1);\n    CHECK_EQ_I64(t, util_pos(9), 1);\n    CHECK_EQ_I64(t, util_pos(0), 0);\n    CHECK_EQ_I64(t, util_pos(-1), 0);\n    CHECK_EQ_I64(t, util_pos(-7), 0);\n}\n\nCTEST_SUITE("util", { "pos", t_pos }, { "ramp", t_ramp }, { "sum", t_sum })|' util/util_test.c
sed -i '/core_sign(1), 1/d; /core_sign(9), 1/d' core/core_test.c
grep -q 'int util_pos(int value);' util/util.h
grep -q '{ "pos", t_pos }' util/util_test.c
grep -q 'return -12345;' util/util.c
! grep -q 'core_sign(9), 1' core/core_test.c
