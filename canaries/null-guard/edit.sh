set -eu
# R003 G2 (T035): a NULL-tolerant accessor whose test never passes a non-NULL pointer to anything but a zero.
# `core_get_or_zero` guards `*p` with `p != NULL`; the test only calls it with a pointer to 0, so skipping the read
# (the `condition` and `relational` mutants of a condition that contains the toolchain's `NULL`) goes unnoticed.
python3 - <<'PY'
def edit(path, old, new):
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

edit("core/core.h", "int core_sign(int value);\n", "int core_sign(int value);\nint core_get_or_zero(const int *p);\n")
edit("core/core.c", '#include "core.h"\n', '#include "core.h"\n\n#include <stddef.h>\n')
open("core/core.c", "a", encoding="utf-8").write(
    "\nint core_get_or_zero(const int *p) {\n    int v = 0;\n    if (p != NULL) {\n        v = *p;\n    }\n    return v;\n}\n")
edit("core/core_test.c", "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign })",
     "static void t_get(ctest_t *t) {\n    int zero = 0;\n    CHECK_EQ_I64(t, core_get_or_zero(&zero), 0);\n}\n\n"
     "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign }, { \"get\", t_get })")
PY
