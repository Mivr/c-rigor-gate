set -eu
F="$CANARY_DIR/../_sim/files"
mkdir simw
cp "$F/BUCK" simw/BUCK
# The bug: the world ignores what the workload does to it (no intent, fault or restart reaches the trace or the state),
# so every seed of the club day looks the same and no invariant would ever see anything.
python3 - "$F/world.c" simw/world.c <<'PY'
import sys
text = open(sys.argv[1]).read()
for old, new in (
    ("    emit(w, (uint32_t)intent.kind, intent.arg);\n    w->sum += intent.arg + 1U;\n",
     "    (void)w;\n    (void)intent;\n"),
    ("    emit(w, 100U + (uint32_t)fault.kind, fault.duration_ms);\n", "    (void)w;\n    (void)fault;\n"),
    ("    emit(w, 200, 0);\n", "    (void)w;\n"),
):
    assert old in text
    text = text.replace(old, new)
open(sys.argv[2], "w").write(text)
PY
