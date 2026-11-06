set -eu
sed -i 's/srcs = \["core.c"\],/srcs = ["core.c"] + [],/' core/BUCK
grep -q '\] + \[\]' core/BUCK
