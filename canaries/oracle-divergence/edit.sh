set -eu
F="$CANARY_DIR/../_oracle/files"
mkdir oraclew
cp "$F/BUCK" oraclew/BUCK
cp "$F/replay.c" oraclew/replay.c
# The bug: `cancel` clears the digits only when more than one was entered.
python3 - oraclew/replay.c <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
old = "        pad->entered = 0;\n    } else if (has_op(line, \"submit\"))"
new = "        pad->entered = pad->entered > 1 ? 0 : pad->entered;\n    } else if (has_op(line, \"submit\"))"
assert old in text
open(path, "w").write(text.replace(old, new))
PY
