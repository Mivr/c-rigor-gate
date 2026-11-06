set -eu
printf '\nint util_fact(int n);\nint util_fact(int n) { return n <= 1 ? 1 : n * util_fact(n - 1); }\n' >> util/util.c
