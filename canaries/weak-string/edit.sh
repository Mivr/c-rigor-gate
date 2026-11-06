set -eu
# R003 G3 (T035): the test only checks that the name function returns something (`!= NULL`), so the text can
# become empty or change by a byte unnoticed (`string-literal`).
python3 - <<'PY'
def edit(path, old, new):
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

edit("core/core.h", "int core_sign(int value);\n", "int core_sign(int value);\nconst char *core_label(void);\n")
open("core/core.c", "a", encoding="utf-8").write("\nconst char *core_label(void) { return \"core\"; }\n")
edit("core/core_test.c", "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign })",
     "static void t_label(ctest_t *t) {\n    CHECK(t, core_label() != 0);\n}\n\n"
     "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign }, { \"label\", t_label })")
PY
