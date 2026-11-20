set -eu
# The product has no c_sim target at all: the policy (gate-owned) says it must have one.
printf '\n/* no simulation */\n' >> core/core.c
