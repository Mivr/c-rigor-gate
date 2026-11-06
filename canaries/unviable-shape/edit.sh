set -eu
sed -i 's/^#endif/unsigned core_sum_ff(void);\n\n#endif/' core/core.h
{ printf '\nunsigned core_sum_ff(void) {\n    static const unsigned char table[32] = {'
  for i in $(seq 1 32); do printf '255, '; done
  printf '};\n    unsigned total = 0;\n    for (unsigned i = 0; i < 32; i++) {\n        total += table[i];\n    }\n    return total;\n}\n'
} >> core/core.c
sed -i 's/^    CHECK_EQ_I64(t, core_add(-4, 4), 0);/&\n    CHECK_EQ_I64(t, core_sum_ff(), 8160);/' core/core_test.c
grep -q core_sum_ff core/core_test.c
