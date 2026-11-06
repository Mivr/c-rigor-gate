set -eu
sed -i 's/return a + b; }$/return a + b + 1; }/' core/core.c
