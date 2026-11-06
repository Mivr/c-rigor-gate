set -eu
# R002 F3, a green control: an honest `bool` function (the return type is the macro `bool` of <stdbool.h>),
# with a test that pins it, must be mutated like any other: no unmutated-function, no survivor.
python3 - <<'PY'
def edit(path, old, new):
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

edit("core/core.h", "#define CORE_H\n", "#define CORE_H\n\n#include <stdbool.h>\n")
edit("core/core.h", "int core_sign(int value);\n", "int core_sign(int value);\nbool core_is_pos(int value);\n")
open("core/core.c", "a", encoding="utf-8").write("\nbool core_is_pos(int value) { return value > 0; }\n")
edit("core/core_test.c", "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign })",
     "static void t_is_pos(ctest_t *t) {\n"
     "    CHECK_EQ_I64(t, core_is_pos(2), 1);\n"
     "    CHECK_EQ_I64(t, core_is_pos(1), 1);\n"
     "    CHECK_EQ_I64(t, core_is_pos(0), 0);\n"
     "    CHECK_EQ_I64(t, core_is_pos(-1), 0);\n"
     "}\n\n"
     "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign }, { \"is_pos\", t_is_pos })")
PY
