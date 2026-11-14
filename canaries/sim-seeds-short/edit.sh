set -eu
F="$CANARY_DIR/../_sim/files"
mkdir simw
cp "$F/BUCK" simw/BUCK
cp "$F/world.c" simw/world.c
