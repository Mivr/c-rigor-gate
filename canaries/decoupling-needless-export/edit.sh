set -eu
sed -i 's|    deps = \["//core:core"\],|    exported_deps = ["//core:core"],|' util/BUCK
grep -q '^    exported_deps = \["//core:core"\],$' util/BUCK
