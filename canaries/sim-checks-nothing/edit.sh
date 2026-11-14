set -eu
F="$CANARY_DIR/../_sim/files"
mkdir simw
cp "$F/BUCK" simw/BUCK
# The bug: the world runs, and its trace differs from seed to seed (so there are 20 distinct hashes), but it reports nothing
# to `world_stats`: no gauge, no counter, no sync, no screen, and no fault ever has an effect. Whatever the gate's invariants
# could have said about it, they had nothing to look at: the run checks nothing.
cp "$F/world.c" simw/world.c
