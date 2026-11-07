set -eu
# Honest code with a truly equivalent mutant (proof in the comment) and no approval: `mutants` must FAIL as a survivor.
sed -i 's/^int core_sign(int value);/int core_sign(int value);\nint core_clamp0(int v);/' core/core.h
cat >> core/core.c <<'EOT'

/* core_clamp0: negative values become 0. The mutant `v < 0` -> `v <= 0` (and `0` -> `1` in the condition) is EQUIVALENT:
   the two bodies differ only for v == 0, and both return 0 there (the branch returns 0, the fall-through returns v == 0).
   No test can tell them apart, and the product carries no approval for it. */
int core_clamp0(int v) {
    if (v < 0) {
        return 0;
    }
    return v;
}

EOT
sed -i 's|^CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })$|static void t_clamp0(ctest_t *t) {\n    CHECK_EQ_I64(t, core_clamp0(-5), 0);\n    CHECK_EQ_I64(t, core_clamp0(-1), 0);\n    CHECK_EQ_I64(t, core_clamp0(0), 0);\n    CHECK_EQ_I64(t, core_clamp0(1), 1);\n    CHECK_EQ_I64(t, core_clamp0(9), 9);\n}\n\nCTEST_SUITE("core", { "add", t_add }, { "clamp0", t_clamp0 }, { "sign", t_sign })|' core/core_test.c
