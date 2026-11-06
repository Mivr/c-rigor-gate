set -eu
# R003 G4 (T050), S1s: `core_pair` returns a struct and is only called, never checked. Before T050 a struct
# return got no mutant at all (info `no-mutable-token`), so the module passed L3 with the function untested.
python3 - <<'PY'
def edit(path, old, new):
    text = open(path, encoding="utf-8").read()
    assert old in text, (path, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

edit("core/core.h", "int core_sign(int value);\n",
     "int core_sign(int value);\nstruct core_pair { int lo; int hi; };\nstruct core_pair core_pair(int a, int b);\n")
open("core/core.c", "a", encoding="utf-8").write(
    "\nstruct core_pair core_pair(int a, int b)\n{\n    struct core_pair p;\n    p.lo = a;\n    p.hi = b;\n    return p;\n}\n")
edit("core/core_test.c", "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign })",
     "static void t_pair(ctest_t *t) {\n    struct core_pair p = core_pair(1, 2);\n    (void)p;\n    CHECK(t, 1);\n}\n\n"
     "CTEST_SUITE(\"core\", { \"add\", t_add }, { \"sign\", t_sign }, { \"pair\", t_pair })")
PY
