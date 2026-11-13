set -eu
sed -i 's|^int core_add(int a, int b);$|int core_add(int left, int b);|' core/core.h
grep -q '^int core_add(int left, int b);$' core/core.h
