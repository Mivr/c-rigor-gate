set -eu
mkdir -p third_party/mini
printf 'load("@gate//rules:c.bzl", "c_library")\n\nc_library(name = "mini", srcs = ["mini.c"], visibility = ["PUBLIC"])\n' > third_party/mini/BUCK
printf 'int mini_one(void) { return 1; }\n' > third_party/mini/mini.c
