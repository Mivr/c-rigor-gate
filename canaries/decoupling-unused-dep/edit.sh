set -eu
# util_test lists //core:core, includes none of its headers and its object references none of its symbols.
sed -i 's|c_test(name = "util_test", srcs = \["util_test.c"\], deps = \[":util"\])|c_test(name = "util_test", srcs = ["util_test.c"], deps = [":util", "//core:core"])|' util/BUCK
grep -q 'deps = \[":util", "//core:core"\])' util/BUCK
grep -c '"//core:core"' util/BUCK | grep -qx 3
