set -eu
# Head: a strong new check in //util:core_test, a test of util's package that lists //core:core directly. It is not
# one of core's tests (they are core's own package's), so core's test surface is unchanged: W = {//util:util}, and the
# bundle of this canary, which has no entry for the L3 module core, is complete.
sed -i 's|^    CHECK_EQ_I64(t, util_sum(values, 3), core_add(core_add(7, -7), 5));$|&\n    CHECK_EQ_I64(t, util_sum(values, 2), 0);|' util/util_core_test.c
grep -q 'util_sum(values, 2), 0' util/util_core_test.c
