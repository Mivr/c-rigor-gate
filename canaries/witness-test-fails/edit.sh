set -eu
# Head: a strong new check that the head's own core_add passes; the witness's core_add is wrong.
sed -i 's|    CHECK_EQ_I64(t, core_add(2, 3), 5);|&\n    CHECK_EQ_I64(t, core_add(1, 1), 2);|' core/core_test.c
grep -q 'core_add(1, 1), 2' core/core_test.c
