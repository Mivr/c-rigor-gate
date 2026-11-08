set -eu
# T102: every glob spelling beyond the two accepted forms stays a bad-argument (one call each, so none hides another).
cat >> core/BUCK <<'BUCK'

c_library(name = "g1", srcs = glob(["**/*.c"]))
c_library(name = "g2", srcs = glob(["../util/*.c"]))
c_library(name = "g3", srcs = glob(["src/*.c"], exclude = ["src/x.c"]))
c_library(name = "g4", srcs = ["core.c"], deps = glob(["src/*.c"]))
c_test(name = "g5", srcs = glob(["tests/**"]), deps = [":core"])
c_library(name = "g6", srcs = glob(["src/*.c"]) + glob(["src/*.h"]))
BUCK
grep -q 'glob(\["tests/\*\*"\])' core/BUCK
