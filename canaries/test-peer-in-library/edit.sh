set -eu
sed -i 's|deps = \["//core:core"\],|deps = ["//core:core", "//core:core_test"],|' util/BUCK
grep -q core_test util/BUCK
