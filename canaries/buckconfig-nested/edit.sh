set -eu
printf '[cxx]\n  cflags = -W\\\nno-error\n' > core/.buckconfig
sed -i 's/^int core_add(int a, int b) { return a + b; }/int core_add(int a, int b) { int unused_value = 3; return a + b; }/' core/core.c
grep -q unused_value core/core.c
