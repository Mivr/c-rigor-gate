set -eu
sed -i 's/srcs = \["core.c"\],/srcs = [("core.c", ["-DNDEBUG"])],/' core/BUCK
grep -q DNDEBUG core/BUCK
