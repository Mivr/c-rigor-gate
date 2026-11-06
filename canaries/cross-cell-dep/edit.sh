set -eu
sed -i 's|deps = \["//core:core"\],|deps = ["//core:core", "toolchains//:libc_symbols"],|' util/BUCK
grep -q toolchains util/BUCK
