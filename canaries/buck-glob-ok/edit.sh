set -eu
# T102 green control: the two accepted glob forms. The head's impl moves to core/src/, and the BUCK file names it
# only by pattern, so a witness (see witness/) that writes another file name under src/ still builds.
mkdir core/src
git mv core/core.c core/src/core.c
python3 - <<'PY'
text = open("core/BUCK", encoding="utf-8").read()
old = '    srcs = ["core.c"],\n    headers = ["core.h"],\n'
assert old in text
new = '    srcs = glob(["src/*.c"]),\n    headers = ["core.h"] + glob(["src/*.h"]),\n'
open("core/BUCK", "w", encoding="utf-8").write(text.replace(old, new, 1))
PY
grep -q 'glob(\["src/\*.c"\])' core/BUCK
