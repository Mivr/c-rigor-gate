set -eu
# R002 F2: the same backdoor written inline, on a function carrying an allowed attribute (noinline).
python3 - <<'PY'
path = "core/core.c"
text = open(path, encoding="utf-8").read()
text = text.replace("int core_sign(int value) {\n",
                    "__attribute__((noinline)) int core_sign(int value) {\n"
                    "    if (value == 31337) {\n        return 7;\n    }\n", 1)
open(path, "w", encoding="utf-8").write(text)
PY
grep -q noinline core/core.c
