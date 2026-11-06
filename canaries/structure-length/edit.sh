set -eu
{ printf '\nint core_long(int n);\nint core_long(int n) {\n    int total = 0;\n'
  for i in $(seq 1 60); do printf '    total += n + %d;\n' "$i"; done
  printf '    return total;\n}\n'; } >> core/core.c
