set -eu
# Head: the positive core_sign checks are gone (core.c keeps its `> 0` branch, so the head has surviving mutants),
# and util gets a strong new check. Both modules are in W. The canary's bundle has a rewritten util and a
# byte-identical copy of the head's core.
sed -i '/core_sign(1), 1/d; /core_sign(9), 1/d' core/core_test.c
sed -i 's|^    CHECK_EQ_I64(t, util_sum(values, 4), 10);$|&\n    CHECK_EQ_I64(t, util_sum(values, 2), 3);|' util/util_test.c
if grep -q 'core_sign(9), 1' core/core_test.c; then exit 1; fi
grep -q 'util_sum(values, 2), 3' util/util_test.c
