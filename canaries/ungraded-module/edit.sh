set -eu
mkdir -p extra
printf 'load("@gate//rules:c.bzl", "c_library")\n\nc_library(name = "extra", srcs = ["extra.c"], visibility = ["PUBLIC"])\n' > extra/BUCK
printf 'int extra_one(void) { return 1; }\n' > extra/extra.c
