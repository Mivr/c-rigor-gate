set -eu
# util_test lists //core:core, includes none of its headers and its object references none of its symbols.
sed -i 's|c_test(name = "util_test", srcs = \["util_test.c"\], deps = \[":util"\])|c_test(name = "util_test", srcs = ["util_test.c"], deps = [":util", "//core:core"])|' util/BUCK
grep -q 'deps = \[":util", "//core:core"\])' util/BUCK
grep -c '"//core:core"' util/BUCK | grep -qx 3

# An integration test: a package with a test and no module.
mkdir flow
cat > flow/BUCK <<'EOB'
load("@gate//rules:c.bzl", "c_test")

c_test(name = "flow_test", srcs = ["flow_test.c"], deps = ["//util:util"])
EOB
printf '#include "ctest/ctest.h"\n#include "util/util.h"\n\nstatic void t_sum(ctest_t *t) {\n    const int values[] = {2, 3};\n    CHECK_EQ_I64(t, util_sum(values, 2), 5);\n}\n\nCTEST_SUITE("flow", { "sum", t_sum })\n' > flow/flow_test.c
# The frozen header of the contract gains a declaration; nothing that was there changes.
sed -i 's|^#endif$|typedef int core_value_t;\n\n#endif|' core/core.h
grep -q '^typedef int core_value_t;$' core/core.h
