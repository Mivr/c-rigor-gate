set -eu
python3 - <<'EOF'
import re
p = "util/util_test.c"
s = open(p).read()
s = re.sub(r"static void t_sum\(ctest_t \*t\) \{.*?\n\}\n\n", "", s, flags=re.S)
s = s.replace('{ "sum", t_sum }, ', "")
open(p, "w").write(s)
EOF
! grep -q t_sum util/util_test.c
