set -eu
F="$CANARY_DIR/../_sim/files"
mkdir simw
cp "$F/BUCK" simw/BUCK
# The bug: one seed in four writes through a null pointer after ten virtual seconds.
python3 - "$F/world.c" simw/world.c <<'PY'
import sys
text = open(sys.argv[1]).read()
old = "    (void)seed;\n    (void)virtual_ms;\n} /* STEP */"
new = "    (void)seed;\n    if (seed % 4U == 3U && virtual_ms > 10000U) {\n        *(volatile int *)0 = 1;\n    }\n} /* STEP */"
assert old in text
open(sys.argv[2], "w").write(text.replace(old, new))
PY
