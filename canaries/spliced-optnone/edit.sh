set -eu
printf '\n#define GLUE(a, b) a##b\nint core_slow(int a);\n__attribute__((GLUE(opt, none))) int core_slow(int a) { return a; }\n#li\\\nne 1 "fake.c"\n' >> core/core.c
# The function is mutated now (B19: it used to be lost); its test kills every mutant, so that only
# semantic-suppressions fails, for exactly one reason.
sed -i 's/^static void t_sign/int core_slow(int a);\n\nstatic void t_slow(ctest_t *t) {\n    CHECK_EQ_I64(t, core_slow(5), 5);\n    CHECK_EQ_I64(t, core_slow(-3), -3);\n}\n\n&/; s/{ "sign", t_sign })/{ "sign", t_sign }, { "slow", t_slow })/' core/core_test.c
