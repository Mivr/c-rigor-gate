set -eu
# core_hidden (unsigned (unsigned)) is cast through void (*)(void) to the int (*)(int) that core_run_step calls
# through, and calls core_run_step: a cycle through a value, between two different function types. The ABI is the
# same for the small values the test uses; the point is what the gate believes, not what the machine does.
python3 - <<'PY'
def edit(path, old, new):
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

edit("core/core.h", "int core_sign(int value);\n",
     "int core_sign(int value);\n\ntypedef int (*core_step_fn)(int);\ntypedef void (*core_any_fn)(void);\n\n"
     "int core_run_step(core_step_fn fn, int value);\nunsigned core_hidden(unsigned value);\n")
open("core/core.c", "a", encoding="utf-8").write(
    "\nint core_run_step(core_step_fn fn, int value) {\n    return fn(value);\n}\n"
    "\nunsigned core_hidden(unsigned value) {\n    if (value == 0u) {\n        return 0u;\n    }\n"
    "    return 1u + (unsigned)core_run_step((core_step_fn)(core_any_fn)core_hidden, (int)(value - 1u));\n}\n")
edit("core/core_test.c", "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign })",
     "static int t_inc(int value) {\n    return value + 1;\n}\n\n"
     "static void t_step(ctest_t *t) {\n    CHECK_EQ_I64(t, core_run_step(t_inc, 4), 5);\n"
     "    CHECK_EQ_I64(t, core_hidden(0u), 0);\n    CHECK_EQ_I64(t, core_hidden(1u), 1);\n"
     "    CHECK_EQ_I64(t, core_hidden(3u), 3);\n}\n\n"
     "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign }, { \"step\", t_step })")
PY
