set -eu
printf '\nvoid *malloc(unsigned long n);\nvoid free(void *p);\nvoid *core_grab(unsigned long n);\nvoid core_drop(void *p);\nvoid *core_grab(unsigned long n) { return malloc(n); }\nvoid core_drop(void *p) { free(p); }\n' >> core/core.c
grep -q 'malloc(n)' core/core.c
