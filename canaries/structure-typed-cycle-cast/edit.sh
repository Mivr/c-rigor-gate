set -eu
# core_hidden (unsigned (unsigned)) is cast through void (*)(void) to the int (*)(int) that core_run_step calls
# through, and calls core_run_step: statically a cycle through a value between two different function types.
# (The cast pointer is never called, so the sanitizers that check function types stay quiet and the tests
# keep every mutant killed. The point is what the gate believes.)
python3 - <<'PY'
def edit(path, old, new):
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

edit("core/core.h", "int core_sign(int value);\n",
     "int core_sign(int value);\n\ntypedef int (*core_step_fn)(int);\ntypedef void (*core_any_fn)(void);\n\n"
     "int core_run_step(core_step_fn fn, int value);\nunsigned core_hidden(unsigned value);\n"
     "core_step_fn core_register(void);\n")
open("core/core.c", "a", encoding="utf-8").write(
    "\nint core_run_step(core_step_fn fn, int value) {\n    return fn(value);\n}\n"
    "\nstatic int core_identity(int value) {\n    return value;\n}\n"
    "\nunsigned core_hidden(unsigned value) {\n    return (unsigned)core_run_step(core_identity, (int)value);\n}\n"
    "\ncore_step_fn core_register(void) {\n    return (core_step_fn)(core_any_fn)core_hidden;\n}\n")
edit("core/core_test.c", "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign })",
     "static int t_inc(int value) {\n    return value + 1;\n}\n\n"
     "static void t_step(ctest_t *t) {\n    CHECK_EQ_I64(t, core_run_step(t_inc, 4), 5);\n"
     "    CHECK_EQ_I64(t, core_hidden(7u), 7);\n    CHECK_EQ_I64(t, core_register() != 0, 1);\n}\n\n"
     "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign }, { \"step\", t_step })")
PY
