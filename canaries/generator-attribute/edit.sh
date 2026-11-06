set -eu
printf '\nint core_twice(int a) __attribute__((noinline));\nint core_twice(int a) { return a + a; }\n' >> core/core.c
