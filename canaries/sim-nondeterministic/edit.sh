set -eu
F="$CANARY_DIR/../_sim/files"
mkdir simw
cp "$F/BUCK" simw/BUCK
# The bug: a counter that survives world_init (state outside the world) leaks into the trace stamp, so the second run of a seed differs.
python3 - "$F/world.c" simw/world.c <<'PY'
import sys
text = open(sys.argv[1]).read()
old = "static uint64_t stamp(uint64_t virtual_ms) {\n    return virtual_ms;\n}"
new = "static uint64_t g_leak;\n\nstatic uint64_t stamp(uint64_t virtual_ms) {\n    return virtual_ms + (g_leak++ / 7U);\n}"
assert old in text
open(sys.argv[2], "w").write(text.replace(old, new))
PY
