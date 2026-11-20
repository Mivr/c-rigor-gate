set -eu
F="$CANARY_DIR/../_oracle/files"
mkdir oraclew
cp "$F/BUCK" oraclew/BUCK
cp "$F/replay.c" oraclew/replay.c
