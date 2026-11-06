set -eu
# Head: a strong new check that the base implementation (the witness) also satisfies.
sed -i 's|    CHECK_EQ_I64(t, core_add(2, 3), 5);|&\n    CHECK_EQ_I64(t, core_add(10, -3), 7);|' core/core_test.c
grep -q 'core_add(10, -3), 7' core/core_test.c
