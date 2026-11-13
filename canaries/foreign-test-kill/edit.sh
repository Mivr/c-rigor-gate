set -eu
# Every core_sign check but one moves from core's own test (//core:core_test) to a test of another package
# (//util:core_test, which lists //core:core directly). The checks still run and still pass, but a module's mutants
# run against its own package's tests only: the core_sign mutants that only the util test would kill survive.
# core_add stays pinned by the own test (its mutants die), and util is killed by its own tests as always.
sed -i '/core_sign(-5), -1/d; /core_sign(-1), -1/d; /core_sign(1), 1/d; /core_sign(9), 1/d' core/core_test.c
sed -i 's|^    CHECK_EQ_I64(t, util_sum(values, 3), core_add(core_add(7, -7), 5));$|&\n    CHECK_EQ_I64(t, core_sign(-5), -1);\n    CHECK_EQ_I64(t, core_sign(-1), -1);\n    CHECK_EQ_I64(t, core_sign(1), 1);\n    CHECK_EQ_I64(t, core_sign(9), 1);|' util/util_core_test.c
grep -q 'core_sign(0), 0' core/core_test.c
if grep -q 'core_sign(9), 1' core/core_test.c; then exit 1; fi
grep -q 'core_sign(9), 1' util/util_core_test.c
grep -q 'core_sign(-5), -1' util/util_core_test.c
