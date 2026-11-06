set -eu
{ printf '\nint util_long(int n);\nint util_long(int n) {\n    int total = 0;\n'
  for i in $(seq 1 90); do printf '    total += n + %d;\n' "$i"; done
  printf '    return total;\n}\n'; } >> util/util.c
