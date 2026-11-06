set -eu
printf 'native.cxx_library(name = "core", srcs = ["core.c"], visibility = ["PUBLIC"])\n' > core/BUCK.v2
