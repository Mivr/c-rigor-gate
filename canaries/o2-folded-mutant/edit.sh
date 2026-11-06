set -eu
# core_flag tests only the defined range. `a + 1 < a` is false for every defined int (signed overflow is undefined), so
# -O2 deletes the branch and a mutation inside it (7 -> 8, 1 -> 2, ...) compiles to the baseline object: before the
# -O0 cross-check (T051) those mutants were `equivalent` and never ran. At -O0 the branch exists, they run, and no
# test pins them.
sed -i 's/^int core_sign(int value);/int core_sign(int value);\nint core_flag(int a);/' core/core.h
cat >> core/core.c <<'EOT'

int core_flag(int a) {
    return (a + 1 < a) ? 7 : 3;
}
EOT
sed -i 's/^    CHECK_EQ_I64(t, core_sign(9), 1);/&\n    CHECK_EQ_I64(t, core_flag(0), 3);\n    CHECK_EQ_I64(t, core_flag(5), 3);/' core/core_test.c
