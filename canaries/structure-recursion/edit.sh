set -eu
printf '\nint core_fact(int n);\nint core_fact(int n) { return n <= 1 ? 1 : n * core_fact(n - 1); }\n' >> core/core.c
