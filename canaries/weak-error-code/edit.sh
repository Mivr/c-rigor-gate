set -eu
# R003 G3 (T035): the tests pin "it failed" (`!= CORE_OK`) but never which error: the enumerator
# `CORE_ERR_RANGE` can become `CORE_ERR_NULL` unnoticed (`enum-constant`).
python3 - <<'PY'
def edit(path, old, new):
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

edit("core/core.h", "#define CORE_H\n", "#define CORE_H\n\ntypedef enum { CORE_OK = 0, CORE_ERR_RANGE = 1, CORE_ERR_NULL = 2 } core_status;\n")
edit("core/core.h", "int core_sign(int value);\n", "int core_sign(int value);\ncore_status core_check(const int *p, int v);\n")
open("core/core.c", "a", encoding="utf-8").write(
    "\ncore_status core_check(const int *p, int v) {\n    if (p == 0) {\n        return CORE_ERR_NULL;\n    }\n"
    "    if (v < 0 || v > 9) {\n        return CORE_ERR_RANGE;\n    }\n    return CORE_OK;\n}\n")
edit("core/core_test.c", "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign })",
     "static void t_check(ctest_t *t) {\n    int v = 5;\n    CHECK_EQ_I64(t, core_check(&v, 5), CORE_OK);\n"
     "    CHECK_EQ_I64(t, core_check(&v, 0), CORE_OK);\n    CHECK_EQ_I64(t, core_check(&v, 9), CORE_OK);\n"
     "    CHECK(t, core_check(&v, -1) != CORE_OK);\n    CHECK(t, core_check(&v, 10) != CORE_OK);\n"
     "    CHECK(t, core_check(0, 5) != CORE_OK);\n}\n\n"
     "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign }, { \"check\", t_check })")
PY
